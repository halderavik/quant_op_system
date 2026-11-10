# Architecture — Survey Research Agent Studio

This file records the decisions the other specifications assumed. It is a local single-user app, not a deployed service.

## Processes

- FastAPI (`backend/app/main.py`) serves `/api` and owns SQLite plus the project file tree.
- Vite (`frontend`) is the browser UI. It proxies `/api` to port 8000 so the OpenAI key never reaches the client.
- SPSS, tabulation, and models run in the API process only as deterministic Python. Generated scripts run in Docker (`--network none`, no API key) or in a labelled subprocess fallback. That fallback is not a secure sandbox.

## Layout

- `backend/app/schemas` — Pydantic contracts from `DATA_CONTRACTS.md`
- `backend/app/engines` — numbers, flow graphs, Excel, SPSS. No LLM calls
- `backend/app/agents` — intent contracts, Agents SDK calls, the task state machine
- `backend/app/repositories` — projects, artifacts, datasets, tasks
- `backend/app/sandbox` — job runner
- `frontend/src` — three-region workspace

## State

SQLite (WAL) stores projects, messages, tasks, artifact revisions, and file pointers. Parquet snapshots hold respondent data. Artifact edits from chat and from the right panel both call the revision API with `expected_version`. A mismatch returns HTTP 409.

Task statuses: `queued`, `clarification_needed`, `running`, `validating`, `completed`, `completed_with_warnings`, `failed`, `cancelled`.

## Models

`ModelRouter` reads role ids from the environment. `GET /api/health` reports whether a key is set and does not call the network. `POST /api/models/probe` lists OpenAI account models and does not expect Claude ids in that list. Questionnaire drafting uses the OpenAI Agents SDK with structured output. Open-end coding and codeframe proposals use Claude when the coding model id starts with `claude`. Crosstabs, weights, tests, regression, clustering, and code frequencies do not.

MaxDiff and conjoint raise `unsupported_method` and are not sent to the general sandbox. An analysis the registry does not implement is written as a Python script, checked, and run in the same analysis sandbox. Chat asks when a required choice is missing. A failed script is rewritten once from its stderr.

## Known limits

- Tab-spec grid editing covers table titles. Full insert, reorder, and delete are available through the revision API.
- External workbook detection maps a small header set and blocks ambiguous significance columns. It does not claim to parse every vendor layout.
- The validator is deterministic. It checks bases, claim bindings, and export files. It does not use a second model to rewrite numbers.
- Complex survey-design standard errors are out of scope. Weighted tables do not receive invented p-values.
- An analysis outside the registry runs as a checked script in the sandbox. The script may use the installed scientific libraries. It cannot import other modules, call `open`, or use the network. A missing choice is asked in chat before a job starts. The script is rewritten once if it fails. MaxDiff and conjoint are still refused.
