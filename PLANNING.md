# Implementation Plan — Local Survey Research Agent Studio

## 0. Instructions to AI coding IDE

Read in this order: `README.md` → `PRD.md` → `ARCHITECTURE.md` → `DATA_CONTRACTS.md` → `AGENT_GUIDELINES.md` → `TEST_PLAN.md` → `TASK.md`. Build runnable code, not UI mockups or stubbed analysis. After each phase run the acceptance checks, fix failures, update tasks, and leave a working app. Prioritize an end-to-end, truthful vertical slice over broad but unimplemented features. Do not declare unsupported workflows complete. No need for production infrastructure or verbose project-management boilerplate.

## 1. Development methodology

Use incremental vertical slices, each adding a functional chain from chat request to validated saved artifact to right-panel preview/export. Establish shared contracts and infrastructure first; thereafter each specialist consists of (1) typed input schema, (2) agent instruction, (3) tool interface, (4) deterministic worker where necessary, (5) validators, (6) UI artifact, (7) tests and (8) exemplar workflow.

Keep orchestration centralized. Establish generic `TaskRunner` state machine and an artifact versioning API before adding specialized agents. Limit direct agents' access to database and files; give them typed tools, not arbitrary SQL or unguarded Python. Prefer a single OpenAI Agents SDK manager pattern over a generic multi-agent graph framework unless verified necessary.

## 2. Phase sequence and milestone acceptance

### P0 — Bootstrapping and local runtime
**Deliver:** backend and frontend boot; settings/.env.example; local SQLite; local storage; API health; Vite app; package scripts; basic tests; optional sandbox Dockerfile.

**Acceptance:** single documented command sequence opens app; no key in client bundle; database persists restart; test suite executes. Establish Windows 11/WSL2 and Linux guidance.

### P1 — Persistent project chat and artifact framework
**Deliver:** projects/conversations/messages database, streamed chat events, SDK sessions, TaskContract, context resolver, artifact revision engine, file uploads, artifact panel shell, version history, export/download mechanism, basic general text artifact. Model settings and health check.

**Acceptance:** create project, send two dependent turns, refresh and still retrieve context; create/edit/save an artifact and see exact same revision after restart; stream status and completion; download a real file.

### P2 — SPSS metadata/data foundation and sandbox
**Deliver:** pyreadstat upload service; dataset fingerprints; metadata/labels/missingness; preview; variable selector; worker with cancellation; Docker sandbox or explicitly labeled fallback; resource/run logs; storage path authorization.

**Acceptance:** fixture SAV loaded with correct variable and value labels, missing codes and N; large-file memory limit results in user-readable error; arbitrary out-of-root paths rejected; compute worker cannot read API key.

### P3 — Questionnaire agent + editor
**Deliver:** SOW extraction, questionnaire structured output, modular question editor, flow validation, objective coverage, respondent preview, DOCX/JSON/Markdown export, chat semantic patches.

**Acceptance:** end-to-end SOW to 20+ question instrument (fixture), modify routing and options in chat and UI, persist revisions, broken routing is flagged, DOCX exists and is readable. Distinguish sample instrument length from actually verified estimate.

### P4 — Tab-spec agent + editor
**Deliver:** canonical table schema, objective/question mapping, dataset variable mapping, whole-study generator, banners/nets/significance controls, Excel writer/parser, grid editor, validation, external spec mapping preview.

**Acceptance:** generated whole-study spec covers fixture questionnaire eligible questions; Excel export round-trips without changes; missing variable references fail; external template with unmappable columns shows review state rather than running bogus tables.

### P5 — Crosstab numerical engine and UI
**Deliver:** weight/base computation, single/multi response, nets, means, top/bottom box, filters, banners, significance adapters, base flags, table renderer, Excel table-book exporter. Integrate canonical and external mapped specs.

**Acceptance:** golden datasets produce exact expected weighted percentages/bases/nets; no category duplication of respondent base; result cells reconcile; at least one valid test and one refusal to calculate invalid test; multi-table XLSX outputs valid files. Excel spec batch produces all supported tables and reports exceptions.

### P6 — Advanced analysis agent
**Deliver:** variable-role collection, AnalysisPlan, method registry, scripted execution, diagnostics, charts, research narrative, report editor/export. Implement a **real** initial registry (descriptive, correlation, chi-square, linear/logistic regression, segmentation, PCA/EFA, key driver, ANOVA, correspondence) then add plugins.

**Acceptance:** logistic and clustering fixture tasks run end to end with variable roles and seed; independent statsmodels/sklearn expected values match; report claims link to result data; blocked when DV/predictors unspecified; MaxDiff/conjoint requests rejected; unsupported methods explicitly marked unsupported.

### P7 — Open-ended coding agent
**Deliver:** selected OE variable(s), codeframe author/editor, structured batch coding and checkpoints, sentiment, human override, review queue, code/net frequency calculation, Excel and supported SPSS exports, methodology report.

**Acceptance:** known 30-response labeled fixture yields valid assignments with no invented codes; codeframe edit creates new revision; weighted respondent frequencies and deduplicated nets reconcile; empty responses excluded appropriately; run can resume/retry a failed batch without duplicating rows.

### P8 — General sandbox agent, validation and polish
**Deliver:** contextual safe file/code tasks, robust validator gates, bounded repair, cross-artifact lineage and stale indicators, unified project navigation, comprehensive UI states, tests, error messages and documentation. Final demo workflow across agents.

**Acceptance:** run six user journeys from PRD; validator rejects a deliberately tampered table/report; no task falsely says completed when export missing; keyboard-accessible chat/artifact interactions; all core tests green.

## 3. Engineering workstreams

### A. Backend and storage
Initialize schemas and migration path. Use explicit repositories/service interfaces (`ProjectRepository`, `DatasetRepository`, `ArtifactRepository`, `TaskRepository`) and transactional artifact version updates. Avoid dumping large dataframe objects into SQLite; store Parquet or Arrow snapshots in project directory, with metadata/references in DB. All local paths go through a storage service.

### B. Agents and prompts
Use OpenAI Agents SDK for tool-aware specialists and Responses API where structured-output calls suffice. Maintain model settings in a `ModelRouter`; agent model input is typed and validated. Write a distinct prompt contract for each specialist using `AGENT_GUIDELINES.md`. Use deterministic validation after LLM generation; LLM semantic review is an additional layer, never substitute for numeric validation.

### C. UI and interaction
Build shared panel first with artifact registry mapping type to renderer. Implement typed frontend API types generated from backend OpenAPI or kept in parity by contract tests. Use `Monaco` only where needed for JSON/code view, rich editor for report text, grid for tab specs/codeframe, question builder for questionnaire. Default to readable layouts with generous whitespace, minimal visual noise, light theme.

### D. Data engines
Treat SPSS variable dictionary as authority. Keep base/weight/test computation as separate unit-tested functions. Do not rely on LLM to synthesize values. Make statistic adapters accept validated plans and return deterministic result dictionaries, charts and diagnostics; work with copies of source data.

### E. Quality and demonstration
Create small synthetic fixtures with **known expected values** and optional sample SAV generated for tests. Cover misnamed variables, weight zero, missing categories, empty base, overlapping nets, multi-label coding, negative controls, unsupported templates and invalid routing. CI-like local test script runs lint/type checks/unit/integration/UI smoke.

## 4. Key design decisions to lock early

1. **Pydantic contracts before frontend editor:** Otherwise chat outputs cannot be reliably edited or exported.
2. **Dataset variable dictionary authoritative:** Study questionnaire can propose aliases but never assert dataset mapping until verified.
3. **Exactly one source of truth per artifact:** Right-panel edits and chat patches write same versioned canonical JSON.
4. **Deterministic numerical engine:** LLM controls method plans and language, not arithmetic.
5. **Separation between significance and percentages:** Inferential assumptions explicit, weighted estimates not assumed to confer valid standard errors.
6. **Spec import honesty:** Unknown formatting requires mapping review. “Any tab-spec” means flexible best-effort normalization, not a promise of omniscient parsing.
7. **No hidden missing-variable guesses:** Essential statistical variable roles are user supplied and checked.
8. **No report numerical hallucination:** Structured report binding references computed result paths.
9. **Isolation and auditability:** Avoid running agent-generated arbitrary code in web server context.
10. **Persistence by IDs, not chat text alone:** File and artifact references survive context-window compaction.

## 5. Risk register with mitigations

| Risk | Effect | Mitigation |
|---|---|---|
| Questionnaire type heterogeneity | Invalid routing/omitted topics | Structured types, study templates as guidance not hard limits, flow graph validation and user edit |
| “Any external tab spec” ambiguity | Incorrect tables | Template sniffing, canonical mapping preview, confidence flags, human confirmation |
| SPSS metadata inconsistencies | Wrong labels/missingness | Preserve original, profile, test against pyreadstat fixtures, show assumptions |
| Weighted significance overclaim | Misleading insights | Distinct estimator/test configuration, warning when design missing, refusal if invalid |
| Analysis method breadth | Unimplemented promises | Adapter registry and scoped supported method list; clear unsupported response |
| OE hallucinated categories/inconsistent coding | Untrustworthy frequencies | Approved code IDs, structured output, review queue, versioned codeframe, row-level reconciliation |
| Context drift | Wrong artifact/dataset | ID-based references, explicit active dataset/version, source-priority resolution |
| Agent edits overwrite user edits | Lost research work | Optimistic version control and semantic diffs |
| Large SAV crashes UI | Poor experience | Data worker, previews, limits, off-thread compute, cooperative cancellation |
| API privacy/traces | Survey disclosure | Local-only originals, selected text transmission, tracing redaction/off switch |
| Code execution dangers | Compromise of local machine | Containerized sandbox, file allowlist, no keys/network, limits |
| Expensive model usage | Unbounded retries | Configurable role routing, batching, capped repairs, usage metering (no billing UI) |

## 6. Working cadence for the coding agent

For each phase:
1. Read exact requirements for phase and linked contract.
2. Create a short technical plan in agent chat, then implement files immediately.
3. Execute local tests and a manual workflow.
4. Update `TASK.md` checkbox only after evidence of working code/tests.
5. Summarize changed files, how to run, test output, limitations and next unimplemented phase.
6. Preserve work from prior phases, avoid replacing completed engines with mocks.

Do not defer all integration until the end. Ensure P3 integrates real chat and exports, P5 real SPSS tables, P6 real analyses, P7 real LLM coding. A prototype need not be perfect but must not claim computation it has not performed.

## 7. Final release checklist

- [x] Frontend and backend start on local machine and open in browser.
- [x] All six specialist workflows function in the same persisted project conversation.
- [x] All artifacts open in right panel; designated editable sections are actually editable.
- [x] Excel and document downloads are real and validated.
- [x] Core SPSS metadata, weights, row bases and net computations pass golden tests.
- [x] Model and API key configurable via environment; API key hidden from browser.
- [x] Validator catches intentional numerical and schema inconsistencies.
- [x] Both chat and direct UI edits result in correct artifact version history.
- [x] Unsupported external spec/method produce honest, actionable errors.
- [x] Restart retains project memory, file references and completed outputs.
- [x] `README.md` has exact setup commands for tested platform.
