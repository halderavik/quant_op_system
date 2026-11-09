# Implementation Task Checklist

**Rule:** Check an item only after code is implemented, manually exercised when appropriate, and relevant automated tests pass. Do not mark agent mocks as complete. For each completed phase add links or file paths to tests and working modules in the IDE's final progress summary.

## Phase P0 — Local foundation
- [x] T001 Initialize Python 3.12 FastAPI backend and `pyproject.toml` with version-pinned deps.
- [x] T002 Initialize React/Vite/TypeScript frontend, Tailwind, shadcn/ui and dev scripts.
- [x] T003 Add `.env.example` for `OPENAI_API_KEY`, SQLite/storage paths, model role IDs, CORS, sandbox settings; no real secrets.
- [x] T004 Implement `/api/health`, error conventions and config validation.
- [x] T005 Set up SQLAlchemy models, Alembic migration, local project directories.
- [x] T006 Add pytest, Ruff/type checks, Vitest and Playwright smoke harness.
- [x] T007 Add tested Windows/WSL2 and Linux startup instructions.

## P1 — Chat, orchestration, persistence, artifacts
- [x] T010 Implement project CRUD and project picker/sidebar.
- [x] T011 Implement conversation and messages persistence, SDK session ID reuse, history loading after restart.
- [x] T012 Implement chat streaming SSE and durable sequenced task events, stop/cancel UI.
- [x] T013 Implement `TaskContract` model, requirement extraction, router and status machine.
- [x] T014 Implement source-prioritized context resolver with dataset/artifact IDs.
- [x] T015 Implement orchestrator and specialist registration via Agents SDK.
- [x] T016 Implement ModelRouter with per-agent model settings, fallback and availability/error reporting.
- [x] T017 Implement immutable artifact versions, semantic patch endpoint, optimistic version guard, lineage/stale indicator.
- [x] T018 Implement right-hand artifact panel framework, collapse, resize, selection and common toolbar.
- [x] T019 Implement real file uploads, storage paths, previews, server-side download endpoint.
- [x] T020 Test two-turn memory, restart, simultaneous UI/chat edits and conflict path.

## P2 — SPSS + worker/sandbox
- [x] T030 Implement pyreadstat `.sav` and `.zsav` supported-file ingest and file hashing.
- [x] T031 Extract labels, value labels, user missing codes, types and candidate weights.
- [x] T032 Persist immutable original plus columnar optimized dataset copy and dictionary.
- [x] T033 Implement dataset metadata, limited preview, variable picker/search and dataset switch.
- [x] T034 Implement project-root file ACL and path traversal protection.
- [x] T035 Implement background worker process/job records, cancellation, time/memory caps.
- [x] T036 Implement isolated Docker job runner, no network/secrets, input RO/output RW.
- [x] T037 Implement explicitly downgraded subprocess fallback policy and warnings.
- [x] T038 Test malformed SAV, value labels, missing sentinel behavior, weight metadata and sandbox denial.

## P3 — Questionnaire
- [x] T050 Implement SOW/document text extraction (PDF/DOCX/TXT/MD) and study brief schema.
- [x] T051 Implement questionnaire generation agent and validated structured output.
- [x] T052 Implement questionnaire schema types, study objective coverage and routing expression AST.
- [x] T053 Build interactive modules/questions/options editor with add/edit/delete/reorder and autosave.
- [x] T054 Add flow graph validator: valid references, impossible/unreachable paths, loops, terminations.
- [x] T055 Implement chat-driven semantic questionnaire patch with version diff.
- [x] T056 Implement respondent path preview and instrument export (DOCX, MD, JSON).
- [x] T057 Test NPS, path-to-purchase, tracking, segmentation and custom questionnaire cases.

## P4 — Tab spec
- [x] T070 Implement canonical TabSpec schema and study defaults.
- [x] T071 Implement table coverage planner for single-select, multi-select, grids, numeric, open text exclusions and nets.
- [x] T072 Implement questionnaire-to-variable mapping with unresolved flags and mapping UI.
- [x] T073 Implement banners, categories, bases, weights, filters, derived vars, significance and nets schemas.
- [x] T074 Implement tab-spec agent and study-wide coverage validator.
- [x] T075 Build interactive editable tab-spec grid with sorting, copy, insert, delete, validation.
- [x] T076 Implement canonical XLSX format with required sheets, import and export round-trip.
- [x] T077 Implement external XLSX/CSV template detector and mapping review, mark unsupported entries.
- [x] T078 Test spec generated from questionnaire-only, dataset-only, both, and malformed spec.

## P5 — Table engine
- [x] T090 Implement tested filter/derived variable AST evaluation and survey base selection.
- [x] T091 Implement unweighted/weighted bases and category count/percent algorithms.
- [x] T092 Implement single response, multiple response, net/subnet, means, Top/Bottom Box and batteries.
- [x] T093 Implement multiway banner segments and optional total; preserve denominator semantics.
- [x] T094 Implement p-value/significance adapters with method/assumption checks, optional multiplicity correction.
- [x] T095 Implement table run from plain-language request and from canonical XLSX spec.
- [x] T096 Implement mapped external spec run with status per table and no silent skips.
- [x] T097 Implement right-panel crosstab viewer and multi-table navigation/search.
- [x] T098 Implement high-quality XLSX tab book export, index and footnotes.
- [x] T099 Implement numerical validator for base totals, weighted count, percent bounds, nets and file integrity.
- [x] T100 Golden tests with known results for zero weight, missing, multiple-response overlap and small bases.

## P6 — Analysis agent
- [x] T110 Implement analysis method registry and typed `AnalysisPlan`/role requirement schema.
- [x] T111 Implement conversational/multi-field variable-role capture for required inputs.
- [x] T112 Implement descriptive/correlation/chi-square/t-test/ANOVA plugins.
- [x] T113 Implement linear and binary logistic regression with diagnostics and encoding.
- [x] T114 Implement PCA/EFA plus reliability diagnostics.
- [x] T115 Implement clustering/segmentation with configurable k/features/seed and profile tables.
- [x] T116 Implement key-driver analysis with explicit dependent/predictor setup and normalized importance definition.
- [x] T117 Implement correspondence analysis and at least basic model evaluation.
- [x] T118 Implement generic isolated custom method path with explicit unsupported-method handling.
- [x] T119 Build report composer binding numeric claims to real result keys and include provenance.
- [x] T120 Build report, charts, tables and script viewer/editable narrative sections and exports.
- [x] T121 Implement model validity/warning checks and explicit MaxDiff/conjoint prohibition.
- [x] T122 Test method adapters against reference stats with fixed seeds and tolerance thresholds.

## P7 — OE coding
- [x] T130 Implement OE column/ID/weight selection and substantive-response inventory.
- [x] T131 Implement supplied-codeframe parser and inductive codeframe proposal agent.
- [x] T132 Implement codeframe hierarchy editor, examples/exclusions, revision control and code ID guard.
- [x] T133 Implement LLM structured multi-label batch coding with checkpoint/retry/review flags.
- [x] T134 Implement sentiment with positive/negative/neutral/mixed/unclear definitions.
- [x] T135 Implement row-level human corrections and preserve initial vs final assignments.
- [x] T136 Implement deterministic per-code weighted/unweighted frequency and respondent net/subnet union.
- [x] T137 Build coded data editor/review queue and reporting tables.
- [x] T138 Export codeframe, assignments, frequency tables, and optionally re-readable SPSS output.
- [x] T139 Test invalid code IDs, overlapping nets, missing responses and fixed labeled fixture.

## P8 — General, validator and delivery
- [x] T150 Implement generic contextual task via sandbox with tool policy and real artifacts.
- [x] T151 Implement independent deterministic validation of schema, numeric claims, versions and export file hashes.
- [x] T152 Implement semantic validator for questionnaire method and analysis interpretation.
- [x] T153 Implement max-two repair attempts, transparent failure and partial result publication.
- [x] T154 Implement provenance/diagnostic viewer and storage-safe trace settings.
- [x] T155 Implement report/chart download affordances and all right-panel artifact types.
- [x] T156 Implement cross-artifact stale warnings for upstream revisions.
- [x] T157 Test full multi-agent journey from SOW through questionnaire/spec/SPSS tabs/report and OE.
- [x] T158 Run `TEST_PLAN.md`, fix high-severity bugs, verify restart/cancellation/download.
- [x] T159 Finalize local README and known-limits matrix. Remove placeholder controls and misleading states.

## Explicit final project acceptance
- [x] A01 Six agent capabilities are real, not sample text placeholders.
- [x] A02 Chat remembers project and artifact context after restart.
- [x] A03 Right side panel supports manual editing and preview/export of relevant artifacts.
- [x] A04 User can specify exact SPSS variable names and receive computed crosstab.
- [x] A05 Canonical Excel tabspec can be re-uploaded to regenerate matching tables.
- [x] A06 A supported external tabspec can be mapped, previewed and executed; unsupported fields flagged.
- [x] A07 Analysis asks for missing roles, then runs actual method and returns validated report.
- [x] A08 OE outputs include human-reviewable multi-label coding and respondent-level net frequencies.
- [x] A09 Validator blocks tampered numerical results.
- [x] A10 All delivered downloads exist, are nonempty and can be opened.
## Discovered During Work

- [x] T173 Let the user download the open tab spec as an Excel plan styled like the example workbook. (2026-11-08)
- [x] T172 Export and generate tab specs in the analyst workbook style, and test significance only within a banner group. (2026-11-08)
- [x] T171 Rename the sidebar title to SRAS (Survey Research Agent Studio). (2026-11-08)
- [x] T170 Preview a programmed Decipher survey from its XML, one question at a time, so the respondent path matches the file. (2026-11-08)
- [x] T169 When a questionnaire is drafted or revised, the validator checks every show-if, skip, route, and option code, corrects logic errors, and does not store a draft that still fails. (2026-11-08)
- [x] T168 Reject show-if and skip conditions that name a missing question, a punch label, or a hidden variable, and say which question and comparison failed. (2026-11-08)
- [x] T167 Show each long task’s real stages in the chat, and restyle the artifact panel as a document. (2026-11-08)
- [x] T166 Download a finished questionnaire as DOCX or PDF, and program it as Decipher XML. (2026-11-08)
- [x] T165 Apply chat requests to add, change, or remove questions to the current questionnaire across follow-up turns. (2026-11-08)
- [x] T164 Keep the chat open until a questionnaire draft finishes, show that draft in the side panel, and release the SQLite write lock during the model call. (2026-11-08)
- [x] T163 Route a pasted study brief to questionnaire generation before analysis, coding, or an SPSS upload request. (2026-11-07)
- [x] T162 Type questionnaire routing values for strict structured output, and include uploaded DOCX paragraphs and tables when drafting. (2026-11-07)
- [x] T161 Align questionnaire, crosstab, and coding exports with the example deliverables. (2026-11-07)

- [x] T160 Route coding jobs to Claude Sonnet and pin fast flagship model ids in `backend/.env`. OpenAI roles use GPT-6.1 Sol. Keys stay server-side. (2026-11-07)

- 2026-11-07: Banner value labels from SPSS are dictionaries. Building a one-table spec must call `.items()` on that dictionary. A bare `or {}.items()` iterated the keys and crashed chat crosstabs.
- 2026-11-07: Parquet snapshots need their parent directory created before `DataFrame.to_parquet`.
- 2026-11-07: Brand X live check on `example/one_project` (965 rows). Questionnaire structured output is rejected because `Expr.value` has no JSON schema type. Follow-up answers do not resume a prior analysis. Rim weights and PowerPoint are stored as notes. An empty chi-square leaves the task queued. The chat transcript can cover the Send button after a long conversation.
- 2026-11-07: T035, T053, T075, T097, T120, T131, T132, T137, T150, T154, and T158 are implemented. Job rows are written by the sandbox runner. Questionnaire and tab-spec edits change structure. The crosstab panel searches a book. Report prose is editable and unclaimed numbers are rejected. Codeframes can be imported or proposed, then reviewed. Chart requests record a sandbox job. Provenance is on the artifact panel and traces default off. Verification: `uv run pytest` 49 passed, `uv run ruff check app tests` clean, `npm test` 14 passed, `npm run test:e2e` 1 passed. Restart, cancel, and download are covered by the API tests. The Playwright run checks the project shell.
