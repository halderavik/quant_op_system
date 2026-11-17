"""Compute the numbers for each planned slide from the cleaned data.

Every figure a slide shows, and every fact its headline may use, comes from
here or from the analysis and coding agents. "Don't know" style codes are
already missing (``mask_off_scale``), and weights apply when the plan names one.
"""

import re
from typing import Any

import numpy as np
import pandas as pd

from app.engines.offscale import is_off_scale_label
from app.engines.report.data_fit import apply_filter
from app.schemas.report_plan import PlanSlide

_ITEM = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_]*\s+(.+?):\s")
_NUMERIC_BANDS = 8


class Labels:
    """Variable and value labels from the dataset dictionary."""

    def __init__(self, variables: list[dict[str, Any]]) -> None:
        self.by_name = {str(v["name"]): v for v in variables}

    def item(self, name: str) -> str:
        """The item a grid column measures ("BrewCo" from "Q2 BrewCo: ..."), else its label."""
        label = str((self.by_name.get(name) or {}).get("label") or name)
        match = _ITEM.match(label)
        if match:
            return match.group(1).strip()
        return re.sub(r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*:\s*", "", label).strip()[:60] or name

    def codes(self, name: str) -> dict[float, str]:
        raw = (self.by_name.get(name) or {}).get("value_labels") or {}
        out = {}
        for code, label in raw.items():
            try:
                out[float(code)] = str(label)
            except (TypeError, ValueError):
                continue
        return out


def compute_slide(
    slide: PlanSlide, data: pd.DataFrame, labels: Labels, weight: str = ""
) -> dict[str, Any]:
    """Numbers, chart data and headline facts for one question-based slide.

    Args:
        slide: Planned slide (not analysis or coding).
        data: Cleaned data with user-missing and off-scale codes already missing.
        labels: Dictionary labels.
        weight: Weight column, or empty.

    Returns:
        ``chart`` (kind, categories, series, number_format), ``facts`` (label, value,
        unit), ``base_n`` and ``base_text``.

    Raises:
        ValueError: The slide's variables are not in the data.
    """
    rows = apply_filter(data, slide.source.filter)
    frame = data.loc[rows]
    present = [v for v in slide.source.variables if v in frame.columns]
    if not present:
        raise ValueError("None of this slide's variables are in the data.")
    w = _weights(frame, weight)
    groups = _groups(frame, slide.source.banner, labels)
    kind = slide.kind
    if kind in {"distribution", "profile"} and len(present) == 1:
        out = _distribution(frame, present[0], w, groups, labels)
    elif kind in {"distribution", "profile"}:
        out = _multi(frame, present, w, groups, labels)
    elif kind == "grid_summary":
        out = _grid(frame, present, w, groups, labels, slide.source.statistic or "top2")
    elif kind == "mean_summary":
        out = _grid(frame, present, w, groups, labels, "mean")
    elif kind == "nps":
        out = _nps(frame, present, w, groups, labels)
    elif kind == "rank_summary":
        out = _rank(frame, present, w, labels)
    elif kind == "funnel":
        out = _funnel(frame, slide, w, labels)
    else:
        raise ValueError(f"'{kind}' slides are not computed from a single table.")
    answered = frame[present].notna().any(axis=1)
    base = int(answered.sum())
    out["base_n"] = base
    out["base_text"] = (
        f"Base: {'respondents where ' + slide.source.filter if slide.source.filter else 'all respondents'} "
        f"answering (n={base})" + (f"; weighted by {weight}" if weight else "")
    )
    return out


def _weights(frame: pd.DataFrame, weight: str) -> pd.Series:
    if weight and weight in frame.columns:
        return pd.to_numeric(frame[weight], errors="coerce").fillna(0.0)
    return pd.Series(1.0, index=frame.index)


def _groups(frame: pd.DataFrame, banner: str, labels: Labels) -> list[tuple[str, pd.Series]]:
    """Total first, then one mask per banner group (numeric banners are banded)."""
    out = [("Total", pd.Series(True, index=frame.index))]
    if not banner or banner not in frame.columns:
        return out
    values = pd.to_numeric(frame[banner], errors="coerce")
    codes = labels.codes(banner)
    if not codes and values.nunique() > _NUMERIC_BANDS:
        for name, low, high in _bands(values, labels, banner):
            out.append((name, (values >= low) & (values <= high)))
        return out
    for code in sorted(values.dropna().unique()):
        label = codes.get(float(code), _fmt_code(code))
        if is_off_scale_label(label):
            continue
        out.append((label, values == code))
    return out


def _bands(values: pd.Series, labels: Labels, name: str) -> list[tuple[str, float, float]]:
    """Fixed age bands for an age question, otherwise three equal-count bands."""
    label = str((labels.by_name.get(name) or {}).get("label") or "").lower()
    if "age" in label or "old" in label:
        return [("18-34", 0, 34), ("35-54", 35, 54), ("55+", 55, 200)]
    cuts = values.quantile([0, 1 / 3, 2 / 3, 1]).round().tolist()
    return [
        (f"{int(cuts[i])}-{int(cuts[i + 1])}", cuts[i] + (0.5 if i else 0), cuts[i + 1])
        for i in range(3)
    ]


def _pct(mask: pd.Series, answered: pd.Series, w: pd.Series) -> float | None:
    denom = float(w[answered].sum())
    if denom <= 0:
        return None
    return 100.0 * float(w[mask & answered].sum()) / denom


def _distribution(
    frame: pd.DataFrame, name: str, w: pd.Series, groups: list, labels: Labels
) -> dict[str, Any]:
    values = pd.to_numeric(frame[name], errors="coerce")
    codes = labels.codes(name)
    if not codes and values.nunique() > _NUMERIC_BANDS:
        cats = [
            (lbl, (values >= lo) & (values <= hi)) for lbl, lo, hi in _bands(values, labels, name)
        ]
    else:
        present = sorted(values.dropna().unique())
        cats = [
            (codes.get(float(c), _fmt_code(c)), values == c)
            for c in present
            if not is_off_scale_label(codes.get(float(c), ""))
        ]
    answered = values.notna()
    series = []
    for group, mask in groups:
        series.append(
            {"name": group, "values": [_r(_pct(m & mask, answered & mask, w)) for _, m in cats]}
        )
    facts = [
        {
            "label": label if len(series) == 1 else f"{label} ({series[0]['name']})",
            "value": val,
            "unit": "%",
        }
        for (label, _), val in zip(cats, series[0]["values"], strict=False)
    ]
    mean = _wmean(values, w)
    if not codes and mean is not None:
        facts.append({"label": "Average", "value": round(mean, 1), "unit": ""})
    return _chart([c for c, _ in cats], series, "pct", facts, sort=False)


def _multi(
    frame: pd.DataFrame, names: list[str], w: pd.Series, groups: list, labels: Labels
) -> dict[str, Any]:
    block = frame[names].apply(pd.to_numeric, errors="coerce")
    answered = block.notna().any(axis=1)
    cats = [labels.item(n) for n in names]
    series = [
        {"name": g, "values": [_r(_pct(block[n] == 1, answered & m, w)) for n in names]}
        for g, m in groups
    ]
    facts = [
        {"label": c, "value": v, "unit": "%"}
        for c, v in zip(cats, series[0]["values"], strict=False)
    ]
    return _chart(cats, series, "pct", facts, sort=True)


def _grid(
    frame: pd.DataFrame, names: list[str], w: pd.Series, groups: list, labels: Labels, stat: str
) -> dict[str, Any]:
    cats = [labels.item(n) for n in names]
    series = []
    for g, m in groups:
        values = []
        for n in names:
            col = pd.to_numeric(frame[n], errors="coerce")
            answered = col.notna() & m
            if stat == "mean":
                values.append(_r(_wmean(col[answered], w[answered]), 2))
            elif stat == "pct_yes":
                yes = _yes_code(labels.codes(n))
                values.append(_r(_pct(col == yes, answered, w)))
            else:
                top = _top_codes(labels.codes(n), col)
                values.append(_r(_pct(col.isin(top), answered, w)))
        series.append({"name": g, "values": values})
    unit = "" if stat == "mean" else "%"
    facts = [
        {"label": c, "value": v, "unit": unit}
        for c, v in zip(cats, series[0]["values"], strict=False)
    ]
    return _chart(cats, series, "mean" if stat == "mean" else "pct", facts, sort=True)


def _nps(
    frame: pd.DataFrame, names: list[str], w: pd.Series, groups: list, labels: Labels
) -> dict[str, Any]:
    cats = [labels.item(n) for n in names]
    facts = []
    if len(groups) == 1:
        det, pas, pro = [], [], []
        for n, cat in zip(names, cats, strict=False):
            col = pd.to_numeric(frame[n], errors="coerce")
            ans = col.notna()
            d, p, r = (
                _pct(col <= 6, ans, w),
                _pct((col >= 7) & (col <= 8), ans, w),
                _pct(col >= 9, ans, w),
            )
            det.append(_r(d))
            pas.append(_r(p))
            pro.append(_r(r))
            if d is not None and r is not None:
                facts.append({"label": f"{cat} NPS", "value": round(r - d), "unit": ""})
                facts.append({"label": f"{cat} promoters", "value": _r(r), "unit": "%"})
                facts.append({"label": f"{cat} base", "value": int(ans.sum()), "unit": "n"})
        series = [
            {"name": "Detractors (0-6)", "values": det},
            {"name": "Passives (7-8)", "values": pas},
            {"name": "Promoters (9-10)", "values": pro},
        ]
        return _chart(cats, series, "pct", facts, sort=False, kind="stacked")
    series = []
    for g, m in groups:
        values = []
        for n in names:
            col = pd.to_numeric(frame[n], errors="coerce")
            ans = col.notna() & m
            d, r = _pct(col <= 6, ans, w), _pct(col >= 9, ans, w)
            values.append(None if d is None or r is None else round(r - d))
        series.append({"name": g, "values": values})
    for g in series:
        for cat, v in zip(cats, g["values"], strict=False):
            if v is not None:
                facts.append({"label": f"{cat} NPS ({g['name']})", "value": v, "unit": ""})
    return _chart(cats, series, "score", facts, sort=False)


def _rank(frame: pd.DataFrame, names: list[str], w: pd.Series, labels: Labels) -> dict[str, Any]:
    cats = [labels.item(n) for n in names]
    first, means = [], []
    block = frame[names].apply(pd.to_numeric, errors="coerce")
    answered = block.notna().any(axis=1)
    for n in names:
        first.append(_r(_pct(block[n] == 1, answered, w)))
        means.append(_r(_wmean(block[n], w), 2))
    facts = [
        {"label": f"{c} ranked first", "value": v, "unit": "%"}
        for c, v in zip(cats, first, strict=False)
    ]
    facts += [
        {"label": f"{c} mean rank", "value": v, "unit": ""}
        for c, v in zip(cats, means, strict=False)
    ]
    out = _chart(cats, [{"name": "Ranked first", "values": first}], "pct", facts, sort=True)
    out["table"] = {
        "columns": ["Factor", "Ranked first (%)", "Mean rank (1 = most important)"],
        "rows": [[c, f, m] for c, f, m in zip(cats, first, means, strict=False)],
    }
    return out


def _funnel(frame: pd.DataFrame, slide: PlanSlide, w: pd.Series, labels: Labels) -> dict[str, Any]:
    """Stages are the slide's questions in order; brands are the items they share."""
    stages: dict[str, list[str]] = {}
    for name in slide.source.variables:
        if name in frame.columns:
            stages.setdefault(re.sub(r"r\d+$", "", name), []).append(name)
    stage_ids = [q for q in slide.source.question_ids if q in stages]
    brands = [labels.item(n) for n in stages[stage_ids[0]]] if stage_ids else []
    stage_names = {0: "Aware", 1: "Would consider", 2: "Bought (12 months)", 3: "Own now"}
    series = []
    facts = []
    for index, qid in enumerate(stage_ids):
        values = []
        for name in stages[qid]:
            col = pd.to_numeric(frame[name], errors="coerce")
            values.append(
                _r(
                    _pct(
                        col == _yes_code(labels.codes(name)), pd.Series(True, index=frame.index), w
                    )
                )
            )
        name = stage_names.get(index, qid)
        series.append({"name": name, "values": values[: len(brands)]})
        facts += [
            {"label": f"{b} {name.lower()}", "value": v, "unit": "%"}
            for b, v in zip(brands, values, strict=False)
        ]
    return _chart(brands, series, "pct", facts, sort=False, kind="column")


def _chart(
    categories: list[str],
    series: list[dict[str, Any]],
    fmt: str,
    facts: list[dict[str, Any]],
    *,
    sort: bool,
    kind: str = "",
) -> dict[str, Any]:
    categories = [_short_label(c) for c in categories]
    series = [{**item, "name": _short_label(item["name"])} for item in series]
    if sort and series:
        order = sorted(range(len(categories)), key=lambda i: -(series[0]["values"][i] or -1))
        categories = [categories[i] for i in order]
        series = [{**s, "values": [s["values"][i] for i in order]} for s in series]
    if not kind:
        kind = (
            "bar"
            if len(categories) > 6 or max((len(c) for c in categories), default=0) > 18
            else "column"
        )
    return {
        "chart": {"kind": kind, "categories": categories, "series": series, "number_format": fmt},
        "facts": [f for f in facts if f["value"] is not None],
    }


def _short_label(text: str) -> str:
    """A chart-friendly label: repaired dashes, and the part before a long colon list."""
    text = str(text).replace("�", "-").strip()
    if len(text) > 28 and ":" in text:
        text = text.split(":", 1)[0].strip()
    return text


def _yes_code(codes: dict[float, str]) -> float:
    for code, label in codes.items():
        if re.match(r"\s*(yes|selected)\b", label, re.I):
            return code
    return 1.0


def _top_codes(codes: dict[float, str], col: pd.Series) -> list[float]:
    scale = sorted(c for c, label in codes.items() if not is_off_scale_label(label)) or sorted(
        col.dropna().unique()
    )
    return scale[-2:]


def _wmean(values: pd.Series, w: pd.Series) -> float | None:
    mask = values.notna()
    total = float(w[mask].sum())
    if total <= 0:
        return None
    return float(np.average(values[mask].astype(float), weights=w[mask]))


def _r(value: float | None, digits: int = 0) -> float | None:
    if value is None:
        return None
    return round(float(value), digits) if digits else float(round(float(value)))


def _fmt_code(code: Any) -> str:
    number = float(code)
    return str(int(number)) if number.is_integer() else str(number)
