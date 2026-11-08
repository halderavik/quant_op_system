# Product Requirements Document — Survey Research Agent Studio

**Status:** Implementation specification for local prototype  
**Revision:** 1.0 — 2026-11-07  
**Audience:** AI coding IDE, engineering, research/statistical methodologists  
**Priority:** Accuracy, flexibility, transparent execution, coherent UX; cost optimization is secondary.

## 1. Vision

Build a locally running, integrated agentic quantitative survey research environment. A researcher talks to one professional assistant in a persistent project chat. Behind the scenes, a coordinator routes each task to a questionnaire-design specialist, tab specification specialist, crosstab engine, statistical analysis specialist, open-end coding specialist, or general-purpose sandbox specialist. The researcher may also edit structured deliverables directly in a right-side artifact workspace. Every numerical result is computed from data, every artifact is editable where practical, and a separate validator checks the result before it is delivered.

This is a functional local prototype, **not** a production multi-tenant platform. Do not introduce cloud deployment, billing, authentication providers, enterprise infrastructure, or elaborate microservice architecture unless strictly necessary. Nonetheless, handle uploaded data and local code execution conservatively.

## 2. Product principles

1. **Execute the request:** Prefer completing a well-specified task over narrating plans. Ask only for missing *blocking* information; use visible, documented defaults for nonblocking choices.
2. **One continuous research context:** Uploaded datasets, questionnaires, codeframes, artifacts, variable aliases, weights, and prior decisions remain accessible within a project and conversation.
3. **Statistically grounded:** An LLM never invents a crosstab, p-value, coefficient, sample count, theme frequency, or model fit statistic. Use tested computation tools.
4. **Researchers retain control:** Structured artifact editors and chat commands can both modify work. Save a new version after each accepted edit.
5. **Professional interaction:** Directly report what was done, what was assumed, warnings, results, and downloadable files. Avoid unsupported conclusions and unrequested long deliberations.
6. **Source of truth:** Original uploaded files are immutable. Dataset schema and project artifacts are stored as addressable resources, not merely pasted into a prompt.
7. **No misleading promises:** Fully arbitrary Excel/tab-spec layouts cannot be parsed reliably. Support canonical format and a documented set of templates; attempt detection of unknown formats and provide a reviewable mapping when necessary. Never silently misinterpret a spec.
8. **Traceable quality:** Input versions, transformation parameters, code, execution logs, validator findings, and outputs form a run record.
9. **Model-flexible:** Centralized configuration chooses a capable OpenAI model per agent and fallback. Verify model availability from the account rather than assuming an alias exists.

## 3. Target user and key journeys

Primary: survey methodologists, quantitative research analysts, statisticians, and research managers. The prototype is single-user on a local workstation.

### Journey A — Create and revise questionnaire
1. User creates a project and pastes SOW/research scope or uploads DOCX/PDF/text materials.
2. System extracts objectives, audiences, methodology, eligibility, required metrics, brand/category lists, and deliverable constraints.
3. Questionnaire agent drafts a complete instrument with modules, question IDs, respondent wording, response options, instructions, bases, routing, piping, randomization, quota/screener/termination logic, and research notes.
4. System opens a live questionnaire editor in the right panel; chat remains on the left.
5. User edits a question manually or asks: “Change Q12 to a seven-point scale; update the related routing.”
6. System validates numbering, references, flow, scale consistency, estimated length, and objective coverage; previews respondent path.
7. User exports DOCX/Markdown/JSON and optionally derives tab specs from the current saved questionnaire version.

### Journey B — Generate and customize whole-study tab specifications
1. User supplies a questionnaire, SPSS file, or chooses the active questionnaire.
2. Agent produces tables covering all eligible questions, with banners, stub rows, bases, weighted/unweighted counts, percentages, nets, mean/Top Box/Top 2 Box when applicable, significance rules, exclusions, display order and labels.
3. Variables in a dataset are linked to question IDs; uncertain links are clearly marked for review.
4. User edits the spec in a grid or chat, validates it, and exports an XLSX workbook.
5. The resulting canonical spec can run directly in the crosstab engine.

### Journey C — Generate one table or an entire tab book
1. User uploads an SPSS `.sav`/`.zsav` file, system profiles variables, types, labels, values, missing codes, multiple-response sets if available, and weights.
2. User requests “Q12 by gender and age; weighted column %, unweighted base, significance at 95%,” using known variable names; or uploads a tab-spec workbook.
3. Orchestrator resolves actual variable names, asks a concise clarification if a required banner/weight mapping cannot be determined, and passes a typed spec to computation.
4. Crosstab engine computes verified tables. Results appear as searchable, interactive tab grid with table notes and Excel export.
5. Uploading a whole-study spec yields a table workbook with a table index and a validation report for skipped/unsupported tables.

### Journey D — Advanced analysis and report
1. A dataset must exist. User asks for regression, segmentation, key-driver analysis, factor analysis, correspondence analysis, time-series, etc., excluding MaxDiff and conjoint.
2. User specifies variables and their roles; if not, a targeted structured form or conversational question collects dependent, predictors, weights, filtering, variable transformations, and key method options.
3. Analysis agent drafts a machine-readable AnalysisPlan and shows the intended analysis and assumptions; clear requests can execute immediately.
4. Deterministic Python tools process data in an isolated job directory, save scripts, tables, charts, diagnostics, and intermediate results.
5. Agent writes a research-ready narrative and caveats; validator checks report claims against computed outputs.
6. User explores the report/chart panel and downloads report (DOCX/HTML/optional PDF), Excel results, and script/notebook as available.

### Journey E — Open-ended coding and sentiment
1. User uploads SPSS data and selects text responses (and optional ID, weights, preexisting coding frame, coding examples).
2. Coding agent proposes codeframe with category IDs, descriptions, include/exclude rules, net/subnet hierarchies, explicit multi-code treatment and sentiment definition.
3. User approves/edits the codeframe or requests direct application of a supplied codeframe.
4. Batch LLM coding produces row-level multi-label assignments, flags ambiguous/novel responses and supports review/corrections.
5. A deterministic aggregator calculates weighted/unweighted frequency, % of respondents, net/subnet frequencies (deduplicated respondent-level), code co-occurrence, and sentiment distribution. Counts reconcile to coded records.
6. User downloads coded dataset as Excel and, when supported, SPSS-compatible export; codebook, frequencies, and methodology report accompany it.

### Journey F — General-purpose contextual task
User requests an ad hoc file transformation, chart, descriptive summary, code-based calculation, or research document. General agent uses approved file/sandbox tools and the current project context, with the same validation and artifact conventions. It should not make unsupported statistical claims or bypass explicit exclusions for MaxDiff/conjoint advanced analysis.

## 4. Functional requirements

IDs are stable for implementation, test cases, and issue tracking.

### 4.1 Workspace and chat
- **FR-001** Local app loads without login, supports multiple named projects and conversations.
- **FR-002** Three-region layout: slim project/navigation sidebar, central chat, expandable resizable **right artifact panel**. Minimal typography and restrained neutral colors; light mode default.
- **FR-003** Chat streams status/events and final response; stops/cancels a run; shows steps completed and validation status without exposing chain-of-thought.
- **FR-004** All conversations and artifact links persist after restart; past chat is retrievable.
- **FR-005** Context resolver prioritizes explicit current request > saved project defaults > inferred study metadata; conflicting context is surfaced.
- **FR-006** Users can mention artifacts by name/version or click “Use in chat.”
- **FR-007** File uploads: `.sav`, `.zsav` (where supported), `.xlsx`, `.csv`, `.docx`, `.pdf`, `.txt`, `.md`, `.json`. Unsupported/corrupt formats receive intelligible errors.
- **FR-008** Show project files, active dataset version, questionnaire, tab spec, outputs and run history.
- **FR-009** Artifact edits update durable structured storage; autosave with debounce, explicit save indicator, undo/version history, conflict detection.
- **FR-010** Downloads are served from actual generated files, never placeholder links.

### 4.2 Questionnaire designer
- **FR-020** Parse SOW into study objectives, design metadata, target audiences and research constraints.
- **FR-021** Generate varied survey types: brand health/trust/equity, awareness, NPS/CSAT/CES, path-to-purchase, usage & attitudes, concept/product/advertising tests, pricing (non-conjoint), customer experience, tracking, segmentation, market sizing, employee, HCP/B2B, and custom mixed designs; not limited to templates.
- **FR-022** Every question includes stable ID, module, stem, response type, scale/answers, selectable exclusive options, optional open text, display rules, routing, required/optional, validation, reporting hints and notes.
- **FR-023** Handle single-select, multi-select, rating, numeric, text, matrix, rank, allocation, date, grid, loop, masked list, quota, screener, terminate, skip, carry-forward, and piping; explicitly flag unsupported interaction types.
- **FR-024** Recommend sensible order, fatigue reduction, bias minimization, mutually exclusive/exhaustive answer sets, “none/don't know” handling, and balanced response scales.
- **FR-025** Maintain measurable mapping of objectives to question IDs.
- **FR-026** Resolve and revalidate routing dependencies on edits; provide flow-preview and warnings for unreachable questions, broken references, conflicting conditions and loops.
- **FR-027** Export readably to DOCX; optionally export machine-readable JSON and Markdown.
- **FR-028** Questionnaire generation is not claimed to be programming-platform-specific; export generic specification unless platform is selected.

### 4.3 Tab specification agent
- **FR-030** Create whole-study tab plan from active questionnaire or SPSS metadata; cover eligible variables/questions and identify exclusions with reasons.
- **FR-031** Canonical table definition supports table ID/title, source question(s)/variable(s), table type, row categories, banner segments, bases/universes, weight, filter, missingness, aggregation, tests, statistics, decimals, notes, order.
- **FR-032** Support numeric summaries, single response, multiple response, matrix batteries, net/subnet, grouped categories, mean, Top/Bottom Box, distribution and multiway banner columns.
- **FR-033** Show unresolved/questionnaire-to-variable mappings; no guessing exact field names.
- **FR-034** Excel spec download has `README`, `Study`, `Tables`, `Banners`, `Nets`, `Derived_Variables`, `Significance`, `Mappings`, `Validation` sheets; use stable machine-readable columns and examples.
- **FR-035** Grid editor supports insert/reorder/duplicate/delete/edit and validation; chat modifications operate on same source-of-truth artifact.
- **FR-036** Include standard whole-study conventions: table numbering, base footnotes, weighted/unweighted denominators, skip/NA handling, significance and small-base caveats, banner definitions, output order.

### 4.4 Crosstabulation engine
- **FR-040** SPSS ingestion preserves variable names, variable labels, value labels, user-defined missingness if available, data types, and original records; decode failures are reported.
- **FR-041** Profile data and propose candidate weights, respondent IDs, multi-response questions and missing-value encoding; suggestions must be confirmed when consequential.
- **FR-042** Run a single requested table and batches of tables using identical canonical specification schema.
- **FR-043** Parse own XLSX spec reliably. For external XLSX/CSV formats, identify structure, attempt schema mapping, render mapping preview and require confirmation if ambiguities exist. Unsupported constructs are marked, not silently ignored.
- **FR-044** Handle row %, column %, total %, weighted count, unweighted base, weighted base, mean, SD, net percentages and multiple-response mentions with explicit denominator semantics.
- **FR-045** Configurable significance (default 95%, two-sided), pairwise tests for relevant proportions/means with documented assumptions, multiple-testing option, design-effect handling where available, display significance letters and small-base flags.
- **FR-046** Handle weight missing/invalid/zero/negative policy explicitly; no quiet use of invalid weights; tables reconcile against effective base.
- **FR-047** Outputs are viewable and sortable in the right panel and export to Excel with title, source, bases, notes, cell formatting and run metadata.
- **FR-048** Support reusable derived variables: age bands, category merges, reversed scales, nets, top-box flags, mean score; include provenance and validate instructions.
- **FR-049** Multi-response options stored as a *set* of boolean indicators or long-form source; respondent-level bases must not be inflated by responses.
- **FR-050** Weighted percentages and tests must not be treated as a fully survey-design-aware inferential analysis when complex design data are absent.

### 4.5 Statistical analysis agent
- **FR-060** Analysis requires a loaded SPSS dataset; otherwise ask for upload.
- **FR-061** Block execution until required variable roles and options are supplied; display candidate valid variables without deciding causal/dependent roles for the user.
- **FR-062** Provide analysis registry and validated typed plans. Initial methods: descriptive, correlations, t-test/ANOVA, chi-square, linear/logistic/ordinal regression, key-driver analysis, PCA/EFA, clustering/segmentation, discriminant/classification, correspondence analysis, reliability (alpha), and weighting/profile summaries.
- **FR-063** Extensible plugin interface for new R/Python statistics, including structural equation modeling, latent class, multilevel/longitudinal models, survival analysis, etc.; each plugin needs declared inputs/outputs and validators. Not every possible method is available at launch.
- **FR-064** **Exclude MaxDiff and conjoint** workflows; explain exclusion and do not dispatch them to generic agent as a workaround.
- **FR-065** Each run yields machine-readable results, executable script, logs, graphics, diagnostics, research report and caveats; errors show actionable next steps.
- **FR-066** Filter, weights, missing-value rules, imputation, transformations, random seeds, model configuration and software versions are recorded.
- **FR-067** No silent statistical defaults for critical inputs; allow documented method defaults once roles and intended sample are known.
- **FR-068** Narrative distinguishes association from causation, sample estimates from population, fit vs validation, and predictive vs explanatory objectives.
- **FR-069** Provide statistical warnings for small samples, sparse cells, high missingness, convergence, separation, collinearity, low cluster size, unstable loadings, and outlier influence as appropriate.
- **FR-070** All numerical statements in a generated report must be traceable to named result fields.

### 4.6 Open-ended coding and sentiment
- **FR-080** Select one or more text columns and respondent ID; treat blank/placeholder responses separately.
- **FR-081** Support supplied codeframe or emergent inductive codeframe, with iterative review, examples, inclusion/exclusion, stable code IDs, parent nets/subnets, and multi-label coding.
- **FR-082** LLM codes in batches to a strict schema with evidence spans (or short rationale), confidence or review reason, applied code IDs and sentiment labels, without fabricating responses.
- **FR-083** Novel or ambiguous answers are flagged; human corrections override automated assignments and are retained.
- **FR-084** Build non-overlapping respondent-level net counts for distinct respondent reach and separate mention-count reports. Subcodes may overlap; percentages need not add to 100% in multi-label coding.
- **FR-085** Allow sentiment polarity plus optional intensity/aspect; document handling of negation, mixed sentiment, sarcasm and neutral/unclear.
- **FR-086** Export codeframe, row-level coded data, per-code weighted/unweighted frequencies, percentages, nets/subnets, sentiment and review log.
- **FR-087** Optional SPSS export must maintain original variables and append coding variables with meaningful labels; validate round-trip read when feasible.
- **FR-088** Quality checks: valid code IDs, no duplicate row IDs, missing response coverage, consistency of hierarchy, coded-record reconciliation and reviewer disagreement sample.

### 4.7 Orchestration and validation
- **FR-090** Orchestrator parses intent and creates typed TaskContract: action, inputs, variable roles, desired artifacts, dependencies, constraints, user-confirmation requirements, success checks.
- **FR-091** Route to specialists based on intent; sequential and multi-step tasks permitted (questionnaire → specs → tabs → report).
- **FR-092** Agents receive only necessary context, artifact references, and tools; one component owns communication to user to avoid duplicate/conflicting replies.
- **FR-093** Validator is mandatory prior to success status. It checks input requirements, schema, computations, coverage, research methodology, export existence and request-level match; independent deterministic tests are primary.
- **FR-094** Validation failures lead to bounded repair/recompute (max two automated retries per stage), otherwise present partial output with explicit failure status.
- **FR-095** Show clear task status (`queued`, `clarification_needed`, `running`, `validating`, `completed`, `completed_with_warnings`, `failed`, `cancelled`) and artifact statuses.
- **FR-096** Each run logs agent, model ID, tools, data fingerprints, input artifact versions, elapsed time, error class, and validation results; avoid logging raw respondent text by default.
- **FR-097** Global agent instructions prohibit fabricated results, misleading status, destructive edits, and unauthorized external transfer.

### 4.8 General sandbox
- **FR-100** General agent may perform contextual transformations, code generation/execution and creation of files/charts/documents through an approved tool catalog.
- **FR-101** Sandbox is a *local, isolated subprocess/container* with restricted directories, resource limits, timeout, no ambient secrets, and network disabled by default; local prototype must not execute arbitrary LLM-generated code directly in the API server process.
- **FR-102** If local Docker unavailable, use a limited subprocess fallback only with explicit warning of reduced isolation; never label it secure sandboxing.
- **FR-103** Every execution saves source script, manifest, stdout/stderr, outputs, and exit status.
- **FR-104** File read/write tools enforce project paths and reject path traversal.

## 5. UX requirements

Desktop-first at 1280px+, responsive layout below that width. Suggested default sizing: navigation 220px; chat flexible ~46%; right panel flexible ~44%. Right panel collapses when no artifact is open; chat can remain wide. Use shadcn/ui + Tailwind; icons sparingly. No clutter, overlapping dialogs, fake charts or skeleton controls that do nothing.

Right panel artifact types: `QuestionnaireEditor`, `TabSpecGrid`, `CrosstabViewer`, `AnalysisReport`, `ChartViewer`, `CodeframeEditor`, `CodedDataGrid`, `FilePreview`, `RunDiagnostics`. Common toolbar: title, type, source version, status, save/undo, version history, download, expand/close. Changes from chat cause obvious diff/confirmation of affected artifact version. Spreadsheet-like panes support sticky headings, search and row focus. Reports support inline editable narrative sections while computed numbers remain generated/read-only unless rerunning analysis.

Chat assistant response pattern: one short opening statement of what completed; compact assumptions/quality notes; links to produced artifacts; one targeted question only if blocked. Show “working / reading file / calculating / validating / exporting” as succinct events. Do not stream private reasoning.

## 6. Nonfunctional requirements and constraints

- **NFR-001:** Local start via `docker compose up` or `uv run uvicorn ...` plus `npm run dev`; documented quick-start with Windows 11 and Linux notes.
- **NFR-002:** Persistent SQLite + local artifact filesystem; no Redis/Celery/Kubernetes/cloud infra for v1.
- **NFR-003:** Browser refresh/restart does not lose conversations, uploads or accepted artifact edits.
- **NFR-004:** OpenAI API key stored **server-side** in `.env`, never sent to the browser or exposed in logs; detect missing key with actionable startup error.
- **NFR-005:** Compute must remain responsive for moderately large SPSS files; use streaming/chunk strategies where feasible, job execution off the HTTP event loop; provide progress/cancel and memory failure notices.
- **NFR-006:** Accuracy verified against a reference library using fixture data and known expected tables/tests; statistical numerical tolerances documented.
- **NFR-007:** Validation must reject invalid/fabricated values even if LLM narrative sounds plausible.
- **NFR-008:** Avoid sending full respondent-level files to LLM for deterministic tabs/analysis. OE coding sends selected response text to OpenAI, with clear user disclosure and file-size/batch limits.
- **NFR-009:** Basic provenance and local-only data retention; delete project removes associated local files with explicit confirmation.
- **NFR-010:** Unit tests, API tests, browser workflow tests and golden-data tests included.

## 7. Scope and intentional limitations

**Included:** End-to-end local prototype of all six capabilities, persistent project chat, configurable OpenAI models, validation, interactive artifact editors, authentic calculations and downloads.

**Not included initially:** auth, collaboration, billing, cloud deployment, complex survey sampling variance methods without design variables, native integration with all scripting platforms, automated fieldwork deployment, an unrestricted arbitrary file-type parser, MaxDiff/conjoint, full BI report builder, distributed workloads. Extensions should fit clean interfaces.

**Important capability boundary:** The app should *attempt* broad study/method/spec coverage, but capability cannot be assumed. A method or imported format is operationally supported only after an adapter and validation test exist. When unsupported, provide explicit gap, preview and/or extension path; do not manufacture a successful output.

## 8. Definition of done

A full demonstration can perform the following without manual code edits: (1) generate/edit/export questionnaire from SOW; (2) generate/edit/export full tab specs from questionnaire and from SPSS data; (3) run requested weighted tabs plus imported canonical tab book and display/export numbers; (4) execute regression and clustering from a specified SPSS dataset and deliver diagnostics/report; (5) code open-ended responses into a modifiable hierarchy and produce standard frequencies/nets; (6) execute contextual general sandbox task; (7) reload the app and continue a project conversation without losing file/artifact context; (8) exhibit validator catching a deliberately incorrect figure; (9) show actionable failure on unsupported external spec and ambiguous variables; (10) operate using actual OpenAI API calls with model configuration and observable run logs.

See `ARCHITECTURE.md`, `DATA_CONTRACTS.md`, `PLANNING.md`, `TASK.md`, `AGENT_GUIDELINES.md`, `TEST_PLAN.md` and `README.md` for implementation requirements.
