# Survey Research Agent Studio

Local quantitative survey workspace: a persistent project chat, a right-hand artifact panel, and deterministic SPSS calculations. The original build specification follows the quick start.

## Quick start (tested on Windows 11, Python 3.12.10, Node 22)

From PowerShell, in two terminals. Do not chain commands with `&&`.

```powershell
cd backend
uv sync --all-groups
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

```powershell
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173. Copy `.env.example` to `backend/.env` and set `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`. Questionnaire drafting uses OpenAI. Open-end coding and codeframe proposals use Claude. Both keys stay on the server. Crosstabs, tab specs, and registered statistics run without them.

Linux uses the same commands in a shell that allows `&&` if you prefer one line, but each command above also works alone.

Tests:

```powershell
cd backend
uv run pytest
uv run ruff check app tests
```

```powershell
cd frontend
npm test
```

`docker compose --profile sandbox run --rm sandbox` only checks that the sandbox image can start. The API uses Docker for generated scripts when the `docker` CLI is on PATH, and otherwise a labelled subprocess fallback.

## Known limits

- Unweighted crosstabs use a two-tailed unpooled z-test. Uppercase letters are 95% and lowercase letters are 90%. A column with base 30 or below is marked `.`. Weighted tables do not receive letters.
- Questionnaire DOCX and PDF exports keep programming notes in blue, separate from respondent text. Coding workbooks write numeric punches on `Coded_Data` and formula counts on `Codeframe_{variable}`.
- Decipher programming compiles the saved questionnaire into importable survey XML. Loops have an empty body, ranks do not attach a visual rank-sort style, and dates are `YYYY-MM-DD` text. Direct launch into Decipher is not connected. Preview survey walks that XML one question at a time, including the `cond`, `term`, and `goto` logic in the file. Programmer notes stay hidden. A condition this preview cannot read stops the walk instead of being guessed, and `<validate>` Python is not executed.
- Unknown Excel tab-spec layouts are previewed and blocked when the mapping is ambiguous.
- MaxDiff and conjoint are refused.
- Questionnaire drafting calls the OpenAI Agents SDK. An uploaded DOCX, PDF, TXT, or Markdown file in the project is included as study material, and Word tables are part of that text. Open-end classification and codeframe proposals call Claude when `MODEL_CODING` starts with `claude`. Numeric results do not.
- While a task is running, the chat keeps the user’s message on screen and lists the real stage messages (for example “Drafting the instrument”), with a clock on the current stage. The open artifact stays in the panel and shows that same stage.
- The questionnaire editor adds, deletes, and reorders questions and options, and autosaves through the revision API. The tab-spec grid sorts, copies, inserts, and deletes rows. A duplicate table id or an unknown banner is blocked.
- Asking for a chart of the latest table runs a generated script in the sandbox and records a job. The chat does not accept arbitrary Python inside the API process.
- A codeframe can be imported from CSV, JSON, or a simple workbook, or proposed from sample responses. Without an API key the proposal uses keyword themes and is stored for review. Coding still accepts only ids on the approved frame.
- Job traces are off unless the project `store_traces` setting is turned on. Prompt text is then kept on the job row.
- Docker Desktop that is installed but not running is treated as unavailable. Those jobs use the labelled subprocess fallback.
- Playwright is `npm run test:e2e`. It starts the Vite app and checks the project shell.
- The validator checks schemas, bases, claim bindings, and export files. It does not ask a model to repair numbers. A narrative number that is not one of the computed claims is rejected.

## Build specification

# Survey Research Agent Studio — AI-IDE Build Specification

The markdown files below are the product specification. The runnable app is `backend/` and `frontend/`.

## Files and reading order

1. **PRD.md** — Product behavior, user journeys, functional/nonfunctional requirements, boundaries and done criteria.
2. **ARCHITECTURE.md** — Technology stack, agents, state machine, persistent chat memory, storage, sandbox, APIs, model routing.
3. **DATA_CONTRACTS.md** — Canonical data schemas and statistical semantics for questionnaire, table specification, tables, analysis and OE coding.
4. **AGENT_GUIDELINES.md** — Specialized agent contracts, tool boundaries, conversation/validation rules.
5. **PLANNING.md** — Implementation phases, dependency order, risks and evidence of completion.
6. **TASK.md** — Granular build checklist and final acceptance criteria.
7. **TEST_PLAN.md** — Golden datasets, correctness checks, agent evaluations and full workflows.

## Suggested instruction to paste into AI coding IDE

> Build the complete local Survey Research Agent Studio according to the seven Markdown specifications in this folder. Read README.md, PRD.md, ARCHITECTURE.md, DATA_CONTRACTS.md, AGENT_GUIDELINES.md, TEST_PLAN.md, and TASK.md before implementation. Work phase-by-phase (P0–P8), prioritizing runnable end-to-end flows over placeholder UIs. Use Python FastAPI, React/Vite/TypeScript, SQLite, OpenAI Agents SDK and OpenAI Responses API. Implement actual SPSS-based calculations in deterministic Python rather than asking an LLM for numbers. Use a clean minimal UI with a central persistent chat and right-hand editable artifact panel. Implement each phase, test it, fix defects, and only then check TASK.md items. Do not claim unsupported survey methodologies, arbitrary tab-spec imports, statistical methods, or sandbox execution work when they do not. Use my local OPENAI_API_KEY in backend .env; never expose it to the browser. Avoid production/cloud infrastructure. Start coding P0 and P1 immediately and continue through the phases.

## Core design decisions

- **Single local integrated application**, not microservices.
- **One persistent project chat** in which questionnaire, tab spec, computed tabs, model results and coding are linked by versioned references.
- **LLMs specialize in planning, wording, interpreting and classifying; numerical statistics are calculated by Python.**
- **Questionnaires, tab specs, codeframes and report narrative are editable** through both chat and the right-side workspace.
- **Validator must pass** before the system announces a task successfully completed.
- **MaxDiff and conjoint excluded** from the advanced analysis system.
- **Unknown external Excel tab specs:** try to normalize and ask the user to confirm ambiguous mappings; do not invent behavior.
- **Model routing configurable**, with capable flagship reasoning model for difficult methods and a capable bulk model for OE classification. Actual model access is probed at startup.

## Scope notes

This is not a deployed app, nor does it include a supplied OpenAI key. The coding IDE will create the project source, install dependencies, generate local test data, implement APIs and UI, and produce runnable exports. SPSS support and some complex inferential methods may require method-specific assumptions; validation and explicit warnings are mandatory.

## Documentation references

Official docs used for technology choices (verify versions during build):
- https://developers.openai.com/api/docs/models
- https://openai.github.io/openai-agents-python/
- https://openai.github.io/openai-agents-python/sessions/
- https://developers.openai.com/api/docs/guides/structured-outputs
