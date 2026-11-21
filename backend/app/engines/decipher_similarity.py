"""Whole-file similarity between two Decipher survey XML files.

Compares everything a respondent and a data user would notice:

* questions: which exist in both, element type, wording, answer rows and scale
  columns (labels, values, and text), and the settings that change behaviour
  (row piping, number range, total, shuffle, select limits, exclusive and open rows);
* logic: show-if conditions (including the block around a question) and terminates,
  compared by meaning. Both files are fed the same simulated respondents and a
  condition matches when it is true for exactly the same ones;
* everything else: hidden variables, quotas, scripts, styles, and survey settings,
  counted and matched by label.

Each check is pass or fail; the report lists every failure.
"""

import difflib
import html
import random
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

from app.engines.decipher_compare import _parse

QUESTION_TAGS = {"radio", "checkbox", "number", "float", "text", "textarea", "select"}
SAMPLES = 400


@dataclass
class Check:
    """One comparison."""

    area: str
    item: str
    check: str
    passed: bool
    detail: str = ""


@dataclass
class Similarity:
    """The full comparison."""

    checks: list[Check] = field(default_factory=list)
    inventory: dict[str, tuple[int, int, int]] = field(
        default_factory=dict
    )  # kind -> (ref, ours, both)
    only_reference: dict[str, list[str]] = field(default_factory=dict)
    only_generated: dict[str, list[str]] = field(default_factory=dict)

    def add(self, area: str, item: str, check: str, passed: bool, detail: str = "") -> None:
        self.checks.append(Check(area, item, check, passed, detail))

    def score(self, area: str | None = None) -> tuple[int, int]:
        """Passed and total checks, for one area or all."""
        chosen = [c for c in self.checks if area is None or c.area == area]
        return sum(c.passed for c in chosen), len(chosen)

    def by(self, area: str) -> dict[str, tuple[int, int]]:
        """Passed and total per check name within an area."""
        out: dict[str, list[int]] = {}
        for c in self.checks:
            if c.area == area:
                out.setdefault(c.check, [0, 0])
                out[c.check][0] += c.passed
                out[c.check][1] += 1
        return {k: (a, b) for k, (a, b) in out.items()}


@dataclass
class _Q:
    label: str
    tag: str
    node: ET.Element
    hidden: bool
    cond: str
    rows: list[ET.Element]
    cols: list[ET.Element]


def compare_files(generated: str, reference: str, seed: int = 7) -> Similarity:
    """Compare a generated survey with a reference survey.

    Args:
        generated: Survey XML to score.
        reference: Survey XML taken as correct.
        seed: Seed for the simulated respondents.

    Returns:
        Every check and the inventory of elements in each file.
    """
    ours_root, ref_root = _parse(generated), _parse(reference)
    ours, ref = _questions(ours_root), _questions(ref_root)
    result = Similarity()
    respondents = _respondents({**ours, **ref}, seed)

    visible_ref = {k: q for k, q in ref.items() if not q.hidden}
    visible_ours = {k: q for k, q in ours.items() if not q.hidden}
    _inventory(result, "Questions respondents see", visible_ref, visible_ours)
    hidden_ref = {k: q for k, q in ref.items() if q.hidden}
    hidden_ours = {k: q for k, q in ours.items() if q.hidden}
    _inventory(result, "Hidden questions and variables", hidden_ref, hidden_ours)

    for key, theirs in visible_ref.items():
        mine = visible_ours.get(key) or ours.get(key)
        result.add(
            "Questions", theirs.label, "present", mine is not None, "" if mine else "missing"
        )
        if mine is not None:
            _question(result, theirs, mine, respondents)
    for key, theirs in hidden_ref.items():
        mine = ours.get(key)
        result.add(
            "Hidden variables", theirs.label, "present", mine is not None, "" if mine else "missing"
        )
        if mine is not None:
            _rows_cols(result, "Hidden variables", theirs, mine)

    _terms(result, ref_root, ours_root, respondents)
    _counted(result, "Quotas", ref_root, ours_root, "quota")
    _counted(result, "Scripts (exec)", ref_root, ours_root, "exec")
    _counted(result, "Styles", ref_root, ours_root, "style")
    _counted(result, "Display text (html)", ref_root, ours_root, "html")
    _counted(result, "Blocks", ref_root, ours_root, "block")
    _settings(result, ref_root, ours_root)
    return result


# ---------------------------------------------------------------- questions


def _questions(root: ET.Element) -> dict[str, _Q]:
    parents = {child: parent for parent in root.iter() for child in parent}
    found: dict[str, _Q] = {}
    for node in root.iter():
        label = node.get("label")
        if node.tag not in QUESTION_TAGS or not label or _key(label) in found:
            continue
        where = node.get("where") or ""
        own = (node.get("cond") or "").strip()
        hidden = (
            own == "0"
            or ("execute" in where and "survey" not in where.replace("execute", ""))
            or where == "execute"
        )
        if "execute" in where and "survey" in where:
            hidden = True  # computed variables are shown in reports, not to respondents
        conds = [own] if own not in {"", "1"} else []
        parent = parents.get(node)
        while parent is not None and parent.tag in {"block", "loop"}:
            block = (parent.get("cond") or "").strip()
            if block not in {"", "1"}:
                conds.append(block)
            parent = parents.get(parent)
        found[_key(label)] = _Q(
            label=label,
            tag=node.tag,
            node=node,
            hidden=hidden,
            cond=" and ".join(f"({c})" for c in conds),
            rows=[c for c in node if c.tag in {"row", "noanswer"}],
            cols=[c for c in node if c.tag in {"col", "choice"}],
        )
    return found


def _question(result: Similarity, ref: _Q, ours: _Q, respondents: list[dict[str, Any]]) -> None:
    same_tag = (
        ref.tag == ours.tag
        or {ref.tag, ours.tag} <= {"text", "textarea"}
        or {ref.tag, ours.tag} <= {"number", "float"}
    )
    result.add("Questions", ref.label, "type", same_tag, f"{ours.tag} instead of {ref.tag}")
    ratio = _text_ratio(_title(ref.node), _title(ours.node))
    result.add("Wording", ref.label, "question text", ratio >= 0.9, f"{ratio:.0%} similar")
    _rows_cols(result, "Questions", ref, ours)
    _behaviour(result, ref, ours)
    if ref.cond or ours.cond:
        agree, readable = _agreement(_effective_cond(ref), _effective_cond(ours), respondents)
        detail = f"ours: {ours.cond or 'always'} | reference: {ref.cond or 'always'}" + (
            "" if readable else " (could not be evaluated)"
        )
        result.add(
            "Logic",
            ref.label,
            "show-if",
            readable and agree == 1.0,
            f"{agree:.0%} same respondents; {detail}",
        )


# rowCond="Q5[row]": only the rows chosen at Q5 show.
_PIPED_FROM = re.compile(r"^(\w+)\[row\]$")


def _effective_cond(q: _Q) -> str:
    """Who sees the question: its cond, plus "something chosen at the source" for piped rows.

    Decipher skips a question whose rowCond leaves no rows, so ``rowCond="Q5[row]"``
    with no cond and ``cond="Q5.any"`` reach the same respondents.
    """
    cond = q.cond or "1"
    piped = _PIPED_FROM.match(_has(q, "rowCond"))
    if piped is None:
        return cond
    return f"({cond}) and {piped.group(1)}.any"


def _rows_cols(result: Similarity, area: str, ref: _Q, ours: _Q) -> None:
    for kind, theirs, mine in (("rows", ref.rows, ours.rows), ("columns", ref.cols, ours.cols)):
        if not theirs and not mine:
            continue
        ref_map = {r.get("label"): r for r in theirs}
        our_map = {r.get("label"): r for r in mine}
        result.add(
            area,
            ref.label,
            f"{kind} (labels)",
            set(ref_map) == set(our_map),
            f"ours {sorted(our_map)[:10]} vs reference {sorted(ref_map)[:10]}",
        )
        if kind == "columns":
            values = all(_value(ref_map[k]) == _value(our_map[k]) for k in ref_map if k in our_map)
            result.add(
                area,
                ref.label,
                "columns (values)",
                values,
                f"ours {[_value(our_map[k]) for k in our_map][:8]} vs reference {[_value(ref_map[k]) for k in ref_map][:8]}",
            )
        if area == "Questions":
            common = [k for k in ref_map if k in our_map]
            if common:
                ratios = [_text_ratio(_text(ref_map[k]), _text(our_map[k])) for k in common]
                low = [k for k, r in zip(common, ratios) if r < 0.9]
                result.add(
                    "Wording",
                    ref.label,
                    f"{kind} text",
                    not low,
                    f"{len(common) - len(low)}/{len(common)} match"
                    + (f"; differ: {low[:6]}" if low else ""),
                )


def _behaviour(result: Similarity, ref: _Q, ours: _Q) -> None:
    pairs = {
        "row piping": (_row_cond(ref), _row_cond(ours)),
        "number range": (_range(ref.node), _range(ours.node)),
        "total": (ref.node.get("amount"), ours.node.get("amount")),
        "shuffle": (
            "rows" in (ref.node.get("shuffle") or ""),
            "rows" in (ours.node.get("shuffle") or ""),
        ),
        "select limits": (
            (ref.node.get("atleast"), ref.node.get("atmost")),
            (ours.node.get("atleast"), ours.node.get("atmost")),
        ),
        "exclusive rows": (_flagged(ref, "exclusive"), _flagged(ours, "exclusive")),
        "open (specify) rows": (_flagged(ref, "open"), _flagged(ours, "open")),
        "no-answer box": (_noanswer(ref), _noanswer(ours)),
    }
    for name, (theirs, mine) in pairs.items():
        if not theirs and not mine:
            continue
        if (
            name == "select limits"
            and theirs[1] is None
            and mine[1] is None
            and (theirs[0] or "1") == (mine[0] or "1")
        ):
            continue
        result.add(
            "Behaviour", ref.label, name, theirs == mine, f"ours {mine} vs reference {theirs}"
        )


def _has(q: _Q, attr: str) -> str:
    value = (q.node.get(attr) or "").replace(" ", "")
    return value


# Q[row].c5 and Q.c5[row] pick the same cell of a grid.
_ROW_THEN_COL = re.compile(r"(\w+)\[row\]\.(c\w+)")


def _row_cond(q: _Q) -> str:
    return _ROW_THEN_COL.sub(r"\1.\2[row]", _has(q, "rowCond"))


def _flagged(q: _Q, attr: str) -> tuple[str, ...]:
    return tuple(sorted(r.get("label") for r in q.rows if r.get(attr) == "1"))


def _noanswer(q: _Q) -> bool:
    return any(r.tag == "noanswer" for r in q.rows)


def _range(node: ET.Element) -> str:
    match = re.search(r"range\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)", node.get("verify") or "")
    return f"{match.group(1)}-{match.group(2)}" if match else ""


def _value(col: ET.Element) -> str:
    value = col.get("value")
    return value if value is not None else re.sub(r"\D", "", col.get("label") or "")


# ---------------------------------------------------------------- logic by meaning


def _respondents(questions: dict[str, _Q], seed: int) -> list[dict[str, Any]]:
    """Random answer sets covering every question in either file."""
    rng = random.Random(seed)
    people = []
    for _ in range(SAMPLES):
        facts: dict[str, Any] = {}
        for q in questions.values():
            name = q.label
            rows = [r.get("label") for r in q.rows if r.get("label")]
            cols = [c.get("label") for c in q.cols if c.get("label")]
            if q.tag in {"number", "float"}:
                value = rng.choice(
                    [0, 1, 2, 3, 5, 10, 17, 18, 21, 25, 30, 35, 40, 45, 50, 55, 65, 80, 100]
                )
                facts[f"{name}.ival"] = facts[f"{name}.val"] = value
                for row in rows:
                    facts[f"{name}.{row}.ival"] = facts[f"{name}.{row}.val"] = rng.choice(
                        [0, 1, 2, 5, 10]
                    )
                facts[f"{name}.any"] = True
                continue
            if q.tag in {"text", "textarea"}:
                facts[f"{name}.val"] = rng.choice(["", "abc"])
                facts[f"{name}.any"] = bool(facts[f"{name}.val"])
                continue
            multi = q.tag == "checkbox"
            if cols and rows:
                any_cell = False
                for row in rows:
                    picks = (
                        [c for c in cols if rng.random() < 0.35] if multi else [rng.choice(cols)]
                    )
                    for col in cols:
                        hit = col in picks
                        facts[f"{name}.{row}.{col}"] = hit
                        facts[f"{name}.{col}"] = facts.get(f"{name}.{col}", False) or hit
                        any_cell |= hit
                    facts[f"{name}.{row}.any"] = bool(picks)
                    facts[f"{name}.{row}"] = bool(picks)
                facts[f"{name}.any"] = any_cell
                continue
            if rows:
                picks = [r for r in rows if rng.random() < 0.35] if multi else [rng.choice(rows)]
                for index, row in enumerate(rows):
                    facts[f"{name}.{row}"] = row in picks
                facts[f"{name}.any"] = bool(picks)
                facts[f"{name}.count"] = len(picks)
                if not multi:
                    facts[f"{name}.val"] = rows.index(picks[0])
                    facts[f"{name}.ival"] = rows.index(picks[0])
        people.append(facts)
    return people


_OPS = {
    " gt ": " > ",
    " lt ": " < ",
    " ge ": " >= ",
    " le ": " <= ",
    " eq ": " == ",
    " ne ": " != ",
}


def _agreement(a: str, b: str, respondents: list[dict[str, Any]]) -> tuple[float, bool]:
    """Share of respondents for whom both conditions give the same answer."""
    same = 0
    for facts in respondents:
        left, right = _holds(a, facts), _holds(b, facts)
        if left is None or right is None:
            return 0.0, False
        same += left == right
    return same / len(respondents), True


def _holds(condition: str, facts: dict[str, Any]) -> bool | None:
    """Evaluate a condition with Python's own boolean rules over looked-up facts; None when unreadable."""
    text = " " + html.unescape(condition) + " "
    for word, op in _OPS.items():
        text = text.replace(word, op)

    def but(match: re.Match) -> str:
        """Q.but(Q.r3, Q.r4).any: any row selected other than the listed ones."""
        name, excluded = match.group(1), set(re.findall(r"\.(r\w+)", match.group(2)))
        rows = {
            key.split(".")[1]
            for key in facts
            if key.startswith(f"{name}.r") and key.count(".") == 1
        }
        return repr(any(facts.get(f"{name}.{row}") for row in rows - excluded))

    text = re.sub(r"\b([A-Za-z_]\w*)\.but\(([^)]*)\)\.any", but, text)
    if re.search(r"\[|\]|\.but\(|lambda|__|import|\bp\.|\bgv\.", text):
        return None

    def lookup(match: re.Match) -> str:
        name = match.group(0)
        if name in {"and", "or", "not", "True", "False", "None"}:
            return name
        value = facts.get(name)
        if value is None and "." not in name and name.isidentifier():
            value = facts.get(f"{name}.val")
        return repr(value if value is not None else False)

    expr = re.sub(r"(?<![\w.'\"])[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", lookup, text)
    if not re.fullmatch(r"[\s()'\"\w.<>=!+-]*", expr):
        return None
    try:
        # Reason: every name was replaced by a literal; only comparisons and and/or/not remain.
        return bool(eval(expr, {"__builtins__": {}}, {}))  # noqa: S307
    except Exception:  # noqa: BLE001
        return None


def _terms(
    result: Similarity,
    ref_root: ET.Element,
    ours_root: ET.Element,
    respondents: list[dict[str, Any]],
) -> None:
    """Each reference terminate should screen out the same respondents as one of ours."""
    ours = [(t.get("label"), (t.get("cond") or "").strip()) for t in ours_root.iter("term")]
    theirs = [(t.get("label"), (t.get("cond") or "").strip()) for t in ref_root.iter("term")]
    result.inventory["Terminates"] = (len(theirs), len(ours), 0)
    matched = 0
    for label, cond in theirs:
        if cond in {"", "0"}:
            result.add(
                "Terminates", label, "matching terminate", True, "switched off in the reference"
            )
            matched += 1
            continue
        best, best_label, readable_any = 0.0, "", False
        for our_label, our_cond in ours:
            agree, readable = _agreement(cond, our_cond, respondents)
            readable_any |= readable
            if readable and agree > best:
                best, best_label = agree, our_label
        if best < 1.0 and readable_any:
            # Reason: one reference terminate can be several of ours (one per age band).
            parts = [
                our_cond
                for _, our_cond in ours
                if all(_holds(cond, facts) or not _holds(our_cond, facts) for facts in respondents)
            ]
            if parts:
                union = " or ".join(f"({part})" for part in parts)
                agree, readable = _agreement(cond, union, respondents)
                if readable and agree > best:
                    best, best_label = agree, f"{len(parts)} terminates together"
        ok = best == 1.0
        matched += ok
        result.add(
            "Terminates",
            label,
            "matching terminate",
            ok,
            f"closest: {best_label} ({best:.0%} same respondents)"
            if readable_any
            else f"condition could not be evaluated: {cond[:90]}",
        )
    result.inventory["Terminates"] = (len(theirs), len(ours), matched)


def _counted(
    result: Similarity, kind: str, ref_root: ET.Element, ours_root: ET.Element, tag: str
) -> None:
    theirs = list(ref_root.iter(tag))
    ours = list(ours_root.iter(tag))
    ref_labels = {e.get("label") or e.get("name") for e in theirs} - {None}
    our_labels = {e.get("label") or e.get("name") for e in ours} - {None}
    both = len(ref_labels & our_labels) if ref_labels else min(len(theirs), len(ours))
    result.inventory[kind] = (len(theirs), len(ours), both)
    if ref_labels - our_labels:
        result.only_reference[kind] = sorted(ref_labels - our_labels)
    if our_labels - ref_labels:
        result.only_generated[kind] = sorted(our_labels - ref_labels)
    for label in sorted(ref_labels):
        result.add(kind, label, "present", label in our_labels)


def _settings(result: Similarity, ref_root: ET.Element, ours_root: ET.Element) -> None:
    ignore = {
        "alt",
        "name",
        "remerged",
        "state",
        "version",
        "builder:wizardCompleted",
        "wizardCompleted",
        "theme",
    }
    theirs = {k: v for k, v in ref_root.attrib.items() if k not in ignore}
    mine = dict(ours_root.attrib)

    def same(a: str | None, b: str | None) -> bool:
        """Equal, or the same comma-separated list in another order."""
        if a is None or b is None:
            return a == b
        return a == b or sorted(a.split(",")) == sorted(b.split(","))

    for key, value in sorted(theirs.items()):
        result.add(
            "Survey settings",
            key,
            "same value",
            same(mine.get(key), value),
            f"ours {mine.get(key)!r} vs reference {value!r}",
        )


def _inventory(result: Similarity, kind: str, ref: dict[str, _Q], ours: dict[str, _Q]) -> None:
    both = set(ref) & set(ours)
    result.inventory[kind] = (len(ref), len(ours), len(both))
    if set(ref) - set(ours):
        result.only_reference[kind] = sorted(ref[k].label for k in set(ref) - set(ours))
    if set(ours) - set(ref):
        result.only_generated[kind] = sorted(ours[k].label for k in set(ours) - set(ref))


# ---------------------------------------------------------------- text helpers


def _key(label: str) -> str:
    return re.sub(r"[^a-z0-9]", "", label.lower())


def _text(node: ET.Element) -> str:
    raw = html.unescape("".join(node.itertext()))
    # Reason: ${"A<br/>b" if HidDevices.r2 else "A b"} switches wording by device;
    # the desktop text (after else) is compared.
    raw = re.sub(
        r'\$\{\s*"(?:[^"\\]|\\.)*"\s+if\s+[^}]*?\belse\s+"((?:[^"\\]|\\.)*)"\s*\}', r" \1 ", raw
    )
    raw = re.sub(r"\$\{[^}]*\}|\[pipe:[^\]]*\]", " ", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    return " ".join(raw.split()).lower()


def _title(node: ET.Element) -> str:
    title = node.find("title")
    return _text(title) if title is not None else ""


def _text_ratio(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


# ---------------------------------------------------------------- questionnaire scope

QUESTIONNAIRE_AREAS = ("Questions", "Wording", "Logic", "Behaviour", "Terminates")


def compare_questionnaire(
    generated: str, reference: str, questionnaire_ids: set[str]
) -> Similarity:
    """Compare only what the questionnaire defines.

    Reference questions the questionnaire does not have (panel, device, timing,
    quality-check variables) are left out, and so are show-ifs and terminates that
    depend on variables outside the questionnaire (country, panel source, quotas).
    Both are listed under ``only_reference`` so nothing disappears silently.

    Args:
        generated: Survey XML to score.
        reference: Survey XML taken as correct.
        questionnaire_ids: Question and derived-variable ids of the questionnaire.

    Returns:
        Checks in the questionnaire areas only.
    """
    scope = {_key(item) for item in questionnaire_ids}
    full = compare_files(generated, reference)
    ours_names = {_key(q.label) for q in _questions(_parse(generated)).values()}
    known = scope | ours_names
    result = Similarity(inventory=full.inventory)
    skipped_questions: list[str] = []
    skipped_logic: list[str] = []
    for check in full.checks:
        if check.area not in QUESTIONNAIRE_AREAS:
            continue
        if check.area != "Terminates" and _key(check.item) not in scope:
            if check.check == "present" and check.item not in skipped_questions:
                skipped_questions.append(check.item)
            continue
        if check.check in {"show-if", "matching terminate"} and not check.passed:
            names = (
                _cond_names(check.detail.split("reference:", 1)[-1])
                if check.check == "show-if"
                else set()
            )
            if check.check == "matching terminate":
                names = _cond_names(_term_cond(reference, check.item))
            outside = {name for name in names if _key(name) not in known}
            if outside:
                skipped_logic.append(
                    f"{check.item} ({check.check}: uses {', '.join(sorted(outside))})"
                )
                continue
        result.checks.append(check)
    for key in sorted(scope - {_key(q.label) for q in _questions(_parse(reference)).values()}):
        result.only_generated.setdefault(
            "In the questionnaire but not in the reference", []
        ).append(key)
    if skipped_questions:
        result.only_reference["Outside the questionnaire (not scored)"] = skipped_questions
    if skipped_logic:
        result.only_reference["Logic on variables outside the questionnaire (not scored)"] = (
            skipped_logic
        )
    return result


def _cond_names(condition: str) -> set[str]:
    """Variable names a condition refers to (the part before the first dot)."""
    names = set(re.findall(r"(?<![\w.'\"])([A-Za-z_]\w*)\s*(?:\.|\[)", html.unescape(condition)))
    return {name for name in names if name not in {"and", "or", "not"}}


def _term_cond(reference: str, label: str) -> str:
    for term in _parse(reference).iter("term"):
        if term.get("label") == label:
            return term.get("cond") or ""
    return ""
