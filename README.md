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

Open http://127.0.0.1:5173. Copy `.env.example` to `backend/.env` and set `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`. Questionnaire drafting uses OpenAI. Open-end coding and codeframe proposals use Claude. Both keys stay on the server. A named crosstab, a tab spec that is already saved, and registered statistics run without them. Building a tab spec calls the validator, and the spec is saved only after each table has a base in the data.

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

- Unweighted crosstabs use a two-tailed unpooled z-test within each banner group, not against Total and not across groups. Uppercase letters are 95% and lowercase letters are 90%. A column below the table minimum base is marked `.`. Newly generated plans use 20 as that minimum and flag bases of 20–29 as `*low base`. Weighted tables do not receive letters.
- Tab specs export as an analyst plan with Overview, Banner specs, Table plan, Derived variables, and Not tabbed. Chat asks the validator to write that plan from the dataset profile. A column with no data, a text field, and an admin field stay on Not tabbed. A multiple-response table records the punch code that is in the data. A base that matches nobody is saved as All. The spec is not stored when a table would still be empty after two corrections. Download Excel on the tab spec writes that workbook, with the same navy headers, column widths, and orange low-base rows as the example plan. The editor shows those table-plan columns. An older nine-sheet workbook still imports. A base cell that is not `All` or a code comparison blocks that table until it is confirmed. Asking chat to generate cross-tabs from that spec runs the latest saved plan against the active dataset and writes a workbook in the example crosstab layout: a table of contents and one stacked sheet, each question crossed by one banner. The panel lists those tables and loads the one you select. A named `row by banner` request still runs one table. Open ends and unconfirmed bases are recorded as exceptions and the other tables still run.
- Questionnaire DOCX and PDF exports keep programming notes in blue, separate from respondent text. Coding workbooks write numeric punches on `Coded_Data` and formula counts on `Codeframe_{variable}`.
- Decipher programming compiles the saved questionnaire into importable survey XML. Loops have an empty body, ranks do not attach a visual rank-sort style, and dates are `YYYY-MM-DD` text. When `DECIPHER_API_KEY` is set, that XML is uploaded to `https://selfserve.decipherinc.com/api/v1`: the first program creates a survey, and a later program replaces `survey.xml` on the same path. The open link is `https://selfserve.decipherinc.com/survey/{path}`. If Decipher rejects the file, the programmer corrects the structure Decipher named and uploads again: a required survey attribute, a tag that cannot sit inside its parent, or an attribute Decipher names on a tag. Question text, option codes, and routing stay as written. An error that does not name one of those changes is reported, and the XML already corrected is kept. The key is sent as `x-apikey` and stays on the server. A blank key still only saves the XML for download. Live surveys are not overwritten. Preview survey walks that XML one question at a time, including the `cond`, `term`, and `goto` logic in the file. Programmer notes are XML comments, not `note` elements, and the survey sets `delphi="1"`. A condition this preview cannot read stops the walk instead of being guessed, and `<validate>` Python is not executed.
- Unknown Excel tab-spec layouts are previewed and blocked when the mapping is ambiguous.
- MaxDiff and conjoint are refused.
- Questionnaire drafting calls the OpenAI Agents SDK. An uploaded DOCX, PDF, TXT, or Markdown file in the project is included as study material, and Word tables are part of that text. Open-end classification and codeframe proposals call Claude when `MODEL_CODING` starts with `claude`. Numeric results do not.
- While a task is running, the chat keeps the user’s message on screen and lists the real stage messages (for example “Drafting the instrument”), with a clock on the current stage. The open artifact stays in the panel and shows that same stage.
- The questionnaire editor adds, deletes, and reorders questions and options, and autosaves through the revision API. The tab-spec grid sorts, copies, inserts, and deletes rows. A duplicate table id or an unknown banner is blocked.
- Asking for a chart of the latest table runs a generated script in the sandbox and records a job. The chat does not accept arbitrary Python inside the API process.
- An analysis request starts with a plan. The analysis model reads the dataset profile (names, labels, missing counts, and value labels) and writes one step or several, such as imputation, a top-2 box, the segmentation procedure the data needs, a segment profile, and a summary. K-means, PAM with Gower distance, hierarchical clustering, DBSCAN, a Gaussian mixture, and spectral clustering all run. A procedure the registry does not implement is written as a Python script, checked, and run in the sandbox. If a required choice is missing, chat asks before that script runs. A failed script is rewritten once. A `compute` function stored on the plan still runs. MaxDiff and conjoint are refused. That plan runs as `analysis.py` in the sandbox. The results panel downloads the plan, the script, and the workbook. The model does not see respondent rows and does not type the statistics. The default `python:3.12-slim` image has no scientific libraries, so those jobs use the app interpreter with the API key removed.
- A codeframe can be imported from CSV, JSON, or a simple workbook, or proposed from sample responses. Without an API key the proposal uses keyword themes and is stored for review. Coding still accepts only ids on the approved frame.
- Job traces are off unless the project `store_traces` setting is turned on. Prompt text is then kept on the job row.
- Docker Desktop that is installed but not running is treated as unavailable. Those jobs use the labelled subprocess fallback.
- Playwright is `npm run test:e2e`. It starts the Vite app and checks the project shell.
- The validator checks schemas, bases, claim bindings, and export files. It authors the executable tab spec and does not edit computed cells. It does not ask a model to repair numbers. A narrative number that is not one of the computed claims is rejected.

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
