"""Benchmark questionnaire import and Decipher programming against hand-programmed surveys.

Each benchmark survey is a Word questionnaire and the Decipher XML a programmer
built from it. For each one the script:

1. imports the Word file exactly as written (word-for-word check, with retries),
2. plans the logic, builds the XML, and reviews it against the questionnaire,
3. scores the XML against the hand-programmed file on the questionnaire layer
   (types, rows, columns, wording, show-ifs and terminates by meaning, piping,
   ranges, shuffle), and counts the open to-dos.

Results are saved, and each run is compared with the previous one; a survey whose
match falls by more than ``--tolerance`` points is flagged and the exit code is 1.

The survey files are client material, so they are not in the repository. List
them in a JSON file (see ``benchmarks.example.json``)::

    [{"name": "Boursin", "docx": "C:/.../Boursin V8.docx", "reference": "C:/.../P10715.txt"}]

Usage (from ``backend``)::

    uv run python scripts/benchmark.py --config benchmarks.local.json
    uv run python scripts/benchmark.py --only Boursin --reuse-import
"""

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.config import get_settings  # noqa: E402
from app.engines.decipher_similarity import QUESTIONNAIRE_AREAS, compare_questionnaire  # noqa: E402
from app.errors import AppError  # noqa: E402
from app.schemas.questionnaire import Questionnaire  # noqa: E402
from app.services.program_review import build_reviewed_program  # noqa: E402
from app.services.questionnaire_import import StudyFile, import_exact, render_file  # noqa: E402

# To-dos about things the questionnaire leaves to sample setup or media are not scored.
OUT_OF_SCOPE = re.compile(
    r"quota|least.?fill|sample|panel|country|image|video|logo|picture|\[us|\[jp|de/at|ex-us",
    re.I,
)


def main() -> int:
    """Run the benchmark and print the comparison with the last run."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config", default=str(BACKEND / "benchmarks.local.json"))
    parser.add_argument("--results", default=str(BACKEND / "benchmark_results"))
    parser.add_argument("--only", action="append", help="Run only this survey (repeatable).")
    parser.add_argument(
        "--reuse-import",
        action="store_true",
        help="Reuse the last saved import of each survey and benchmark planning only.",
    )
    parser.add_argument("--tolerance", type=float, default=2.0, help="Allowed drop in points.")
    parser.add_argument("--parallel", type=int, default=3, help="Surveys run at once.")
    args = parser.parse_args()

    config = Path(args.config)
    if not config.exists():
        print(f"No benchmark list at {config}. Copy benchmarks.example.json and fill in the paths.")
        return 2
    surveys = json.loads(config.read_text(encoding="utf-8"))
    if args.only:
        wanted = {name.lower() for name in args.only}
        surveys = [item for item in surveys if item["name"].lower() in wanted]
    results_dir = Path(args.results)
    results_dir.mkdir(parents=True, exist_ok=True)
    previous = _previous_run(results_dir)

    outcomes = asyncio.run(_run_all(surveys, results_dir, args.reuse_import, args.parallel))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (results_dir / f"run-{stamp}.json").write_text(json.dumps(outcomes, indent=1), encoding="utf-8")
    return _report(outcomes, previous, args.tolerance)


async def _run_all(
    surveys: list[dict], results_dir: Path, reuse: bool, parallel: int
) -> list[dict]:
    limit = asyncio.Semaphore(max(1, parallel))

    async def one(item: dict) -> dict:
        async with limit:
            return await _run_one(item, results_dir, reuse)

    return list(await asyncio.gather(*(one(item) for item in surveys)))


async def _run_one(item: dict, results_dir: Path, reuse: bool) -> dict:
    """Import, plan, build, review, and score one survey."""
    # Reason: a benchmark measures fresh answers, never ones saved by an earlier run.
    settings = get_settings().model_copy(update={"model_call_cache": False})
    name = item["name"]
    started = time.monotonic()
    cache = results_dir / "imports" / f"{_slug(name)}.json"
    outcome: dict = {"name": name, "import": "not run"}
    try:
        if reuse and cache.exists():
            document = Questionnaire.model_validate_json(cache.read_text(encoding="utf-8"))
            outcome["import"] = "reused"
        else:
            payload = Path(item["docx"]).read_bytes()
            study = StudyFile(Path(item["docx"]).name, render_file(payload, item["docx"]))
            stages: list[str] = []
            document = await import_exact(
                settings, study, session_id=f"benchmark-{_slug(name)}", on_stage=stages.append
            )
            outcome["import"] = "passed"
            outcome["import_retries"] = sum("Re-reading" in stage for stage in stages)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(document.model_dump_json(), encoding="utf-8")
        outcome["questions"] = len(document.questions)
        planned, program, fixed = await build_reviewed_program(
            settings, document, session_id=f"benchmark-{_slug(name)}", on_stage=lambda _m: None
        )
        outcome["review_fixed"] = fixed
        outcome["xml_status"] = program.validation_status
        todos = [
            item
            for question in planned.questions
            if question.programming
            for item in question.programming.unresolved
        ]
        outcome["todos"] = sum(1 for text in todos if not OUT_OF_SCOPE.search(text))
        ids = {q.id for q in document.questions} | {v.id for v in document.derived_variables}
        reference = Path(item["reference"]).read_text(encoding="utf-8")
        similarity = compare_questionnaire(program.xml, reference, ids)
        hit, total = similarity.score()
        outcome["match"] = round(100 * hit / total, 1) if total else None
        outcome["areas"] = {area: list(similarity.score(area)) for area in QUESTIONNAIRE_AREAS}
        # Keep what was built and what it missed, so a low score can be looked into.
        built = results_dir / "xml" / f"{_slug(name)}.xml"
        built.parent.mkdir(parents=True, exist_ok=True)
        built.write_text(program.xml, encoding="utf-8")
        outcome["misses"] = [
            f"{check.area} | {check.item} | {check.check} | {check.detail}"
            for check in similarity.checks
            if not check.passed
        ]
        outcome["open_todos"] = [text for text in todos if not OUT_OF_SCOPE.search(text)]
    except AppError as exc:
        outcome["error"] = exc.message
        if outcome["import"] == "not run":
            outcome["import"] = "failed"
    outcome["seconds"] = round(time.monotonic() - started)
    return outcome


def _report(outcomes: list[dict], previous: dict[str, dict], tolerance: float) -> int:
    """Print the table and return 1 when any survey got worse than the tolerance allows."""
    header = f"{'Survey':16} {'Import':9} {'Match':>7} {'Change':>7} {'To-dos':>7} {'Change':>7} {'Time':>6}"
    print(header)
    print("-" * len(header))
    worse = []
    for outcome in outcomes:
        before = previous.get(outcome["name"], {})
        match, todos = outcome.get("match"), outcome.get("todos")
        match_delta = _delta(match, before.get("match"))
        todo_delta = _delta(todos, before.get("todos"))
        if (
            match is not None
            and before.get("match") is not None
            and match < before["match"] - tolerance
        ):
            worse.append(outcome["name"])
        print(
            f"{outcome['name'][:16]:16} {outcome['import']:9} "
            f"{_show(match, '%'):>7} {match_delta:>7} {_show(todos):>7} {todo_delta:>7} "
            f"{outcome.get('seconds', 0):>5}s"
        )
        if outcome.get("error"):
            print(f"    error: {outcome['error'][:200]}")
    scored = [o["match"] for o in outcomes if o.get("match") is not None]
    if scored:
        print(f"\nAverage match {sum(scored) / len(scored):.1f}%")
    if worse:
        print(f"Worse than the last run by more than {tolerance} points: {', '.join(worse)}")
        return 1
    return 0


def _previous_run(results_dir: Path) -> dict[str, dict]:
    runs = sorted(results_dir.glob("run-*.json"))
    if not runs:
        return {}
    return {item["name"]: item for item in json.loads(runs[-1].read_text(encoding="utf-8"))}


def _delta(now, before) -> str:
    if now is None or before is None:
        return "-"
    change = round(now - before, 1)
    return f"{change:+g}" if change else "0"


def _show(value, suffix: str = "") -> str:
    return "-" if value is None else f"{value}{suffix}"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "survey"


if __name__ == "__main__":
    raise SystemExit(main())
