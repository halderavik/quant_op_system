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

Open http://localhost:5173 (the dev server listens on `localhost`, so `127.0.0.1` may refuse the connection). Copy `.env.example` to `backend/.env` and set `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`. Questionnaire drafting uses OpenAI. Open-end coding and codeframe proposals use Claude. Both keys stay on the server. A named crosstab, a tab spec that is already saved, and registered statistics run without them. Building a tab spec calls the validator, and the spec is saved only after each table has a base in the data.

### Optional: Ad Hoc AutoCoder for open-end coding

Fully automatic open-end coding uses the Ad Hoc AutoCoder from the private repository `Dhyey-b3/adhoc_autocoder_project`. You need read access to that repository. It is not in `pyproject.toml`, because it pins `openai<3` and this backend runs openai 3.x. Install it into the backend environment without its pinned dependencies, plus its embedding library:

```powershell
cd backend
uv pip install --no-deps "adhoc-autocoder @ git+https://github.com/Dhyey-b3/adhoc_autocoder_project@32484bb2740e6488fd9dd6f14a429dbb16ed70f9"
uv pip install "sentence-transformers>=3.0,<6"
```

`uv sync` removes packages that are not in the lock file, so run these two commands again after any `uv sync`. Without the AutoCoder, a coding request with no codeframe says so. You can still propose a codeframe for review, or import one. It uses `OPENAI_API_KEY` with `MODEL_AUTOCODER` (default `gpt-5-mini`). `AUTOCODER_EMBEDDINGS=tfidf` avoids downloading the BGE embedding model, but candidate codes are matched less accurately. Only the question wording and the selected answers are sent to OpenAI. The AutoCoder sees row numbers, not respondent ids.

### Optional: connectors (Google Drive, Slack, Microsoft 365, custom MCP servers)

Open **Connectors** at the bottom left. The agents can then import a brief or data file from Drive, OneDrive, or SharePoint, and save decks and tab books there or post updates to Slack. Ask in chat, for example "Save the report deck to Google Drive" or "Post the key takeaways to #research". Read-only tool calls run at once. Anything that uploads, posts, or changes something outside Quant OS appears as an approval card in the chat, and runs only when you click Approve.

The ready-made connectors use each provider's hosted MCP server and sign in with OAuth. An admin registers an OAuth client once and puts its id and secret in `backend/.env`: `GOOGLE_MCP_CLIENT_ID`/`GOOGLE_MCP_CLIENT_SECRET`, `SLACK_MCP_CLIENT_ID`/`SLACK_MCP_CLIENT_SECRET`, or `MICROSOFT_TENANT_ID` with `MICROSOFT_MCP_CLIENT_ID`/`MICROSOFT_MCP_CLIENT_SECRET`. Each card lists the provider's setup steps and the redirect URI to register (`PUBLIC_BASE_URL` + `/api/connectors/oauth/callback`). Slack only accepts HTTPS redirect URIs, so set `PUBLIC_BASE_URL` to an HTTPS address that reaches the backend. Google's Drive server is in Developer Preview. Microsoft's hosted OneDrive and SharePoint server is in preview and needs a Copilot licence, and its card can point at another Microsoft 365 MCP server instead. A custom MCP server needs only its streamable HTTP URL and an optional token. Tokens are encrypted at rest with `CONNECTOR_SECRET_KEY`, or with a key generated in `data/connectors.key` when that is unset.

To rehearse without real accounts, run the stand-in server, which offers Drive- and Slack-like tools, and add `http://127.0.0.1:8765/mcp` with token `demo-token` as a custom server:

```powershell
cd backend
.venv\Scripts\python.exe -m tests.mock_mcp_server --port 8765 --token demo-token
```

### Live quality: bot and fraud detection in a live Decipher survey

Open the **Live quality** tab in a project and tick **Add tracking when this survey is programmed in Decipher** (or ask in chat, for example "program this survey in Decipher with bot and fraud detection"). Programming then embeds a tracker script and a hidden results page in the survey XML. While people take the survey, the tracker sends behaviour (keystrokes, mouse, scrolling, focus), open-end text, page timing, and grid answers to the bot-detection API from the `bot_detection_live` project (`BOT_DETECTION_API_BASE`, default the deployed Cloud Run service). On the final page it runs the composite check and writes the respondent id, session id, verdict, score, and risk into hidden `QOS_*` questions, so they are in the Decipher data file too. The tab refreshes every 8 seconds with totals and one row per respondent: behaviour verdict, open-end quality and reasons, fraud signals, straight-lining, and speeding. Straight-lining and speeding are computed in Quant OS from the page and grid data the tracker records. The survey id in the detection service is the project name; once a survey is live in Decipher that id is kept, so renaming the project does not split its responses. **Quality dashboard** (bottom left) shows every tracked survey with live tiles, starts over time, open-end quality, reasons for flags, a filterable respondent table, and a CSV export. Switch to **All surveys** to see surveys from other tools that use the same detection service.

**Quality rules.** Each project starts on default rules. Change them under **Quality rules** in the Live quality tab before the survey goes live:
- **Flagging rules** apply on the dashboard as soon as you save: the bot score threshold, the decisive bot signals (automated browser, scripted clicks, no mouse or keyboard, honeypot, open ends that appeared without typing), the speeder and straight-lining limits, which open-end reasons count as low quality, pasted answers, the fraud threshold, duplicates, and connections from cloud data centres.
- **In-survey rules** are written into the survey the next time you program it in Decipher:
  - By default a hidden check runs when page 2 is submitted. Respondents with an enabled decisive signal go to a Decipher termination (`QOS_EARLY`, `QOS_bot_term`). A score on its own never ends a survey.
  - A short privacy notice opens the first page.

To sign trackers so nobody can add fake sessions under a survey's name, set `BOT_DETECTION_TOKEN_SECRET` to the same value as the service's `TRACKING_TOKEN_SECRET`. Without it, surveys are not signed.

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
- A Prolific sample price uses `PROLIFIC_API_KEY` from the server. The panel shows the audience, planned quota cells, eligibility, reward, total, and balance. The model does not type the price. Publishing locks that total only after the user confirms it, and only when the Decipher survey URL exists, the balance covers the new total, and screen-out pay is accepted. Pause, resume, and stop stay on that panel. Other panel vendors are not connected.
- Unknown Excel tab-spec layouts are previewed and blocked when the mapping is ambiguous.
- MaxDiff and conjoint are refused.
- Questionnaire drafting calls the OpenAI Agents SDK. An uploaded DOCX, PDF, TXT, or Markdown file in the project is included as study material, and Word tables are part of that text. Open-end classification and codeframe proposals call Claude when `MODEL_CODING` starts with `claude`. Numeric results do not.
- While a task is running, the chat keeps the user’s message on screen and lists the real stage messages (for example “Drafting the instrument”), with a clock on the current stage. The open artifact stays in the panel and shows that same stage.
- The questionnaire editor adds, deletes, and reorders questions and options, and autosaves through the revision API. The tab-spec grid sorts, copies, inserts, and deletes rows. A duplicate table id or an unknown banner is blocked.
- Asking for a chart of the latest table runs a generated script in the sandbox and records a job. The chat does not accept arbitrary Python inside the API process.
- Chat routing reads the saved artifacts, the active dataset's variable names, and the previous turn, then asks the orchestrator model which specialist should run. A Decipher request, a pasted study brief, and MaxDiff or conjoint do not use that call. Pricing or buying a panel sample, including a later “launch it” on that quote, is the sample specialist. A pasted brief that also mentions sample stays a questionnaire. When the route call cannot run, keyword rules choose the specialist.
- An analysis request starts with a plan. The analysis model reads the dataset profile (names, labels, missing counts, and value labels) and writes one step or several, such as imputation, a top-2 box, the segmentation procedure the data needs, a segment profile, and a summary. K-means, PAM with Gower distance, hierarchical clustering, DBSCAN, a Gaussian mixture, and spectral clustering all run. A procedure the registry does not implement is written as a Python script, checked, and run in the sandbox. If a required choice is missing, chat asks before that script runs. A failed script is rewritten once. A `compute` function stored on the plan still runs. MaxDiff and conjoint are refused. That plan runs as `analysis.py` in the sandbox. The results panel downloads the plan, the script, and the workbook. The model does not see respondent rows and does not type the statistics. The default `python:3.12-slim` image has no scientific libraries, so those jobs use the app interpreter with the API key removed.
- A codeframe can be imported from CSV, JSON, or a simple workbook, or proposed from sample responses. Without an API key the proposal uses keyword themes and is stored for review. Coding still accepts only ids on the approved frame.
- Asking which respondents look like fraud runs the data-cleaning specialist. It checks speeding when a duration field exists, straight-lining and patterned grids, checkbox flatlines, exact and near-duplicate interviews, duplicate ids, attention checks, item nonresponse, age outside 0–120, and open-end gibberish, duplicates, and very short explanations. Counts are computed in Python. The model sees only open ends those rules left undecided, and only when a coding-model key is set. Without that key the recommendation still finishes and those rows stay in review. The original SPSS file is not changed. The panel shows the counts and the workbook. A later request to apply the removals writes a new dataset copy, drops only the remove rows, and leaves review rows and the uploaded file in place.
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
