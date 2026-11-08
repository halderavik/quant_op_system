# Testing, Evaluation and Acceptance Plan

## 1. Test strategy

A working feature requires a schema test, algorithm/tool test, API integration test, UI integration smoke test and a reference golden test where appropriate. LLM plausibility is not a substitute for deterministic statistical correctness. Use synthetic data with fixed seeds; avoid putting real respondent data into public test fixtures or trace exports.

## 2. Golden dataset pack to create

- `survey_small.sav`: 100 synthetic respondents, IDs, weight, gender, age, 5-point trust, NPS, satisfaction, single-select category, multi-response brand flags, purchase intent, 1+ OE fields. Include user-missing codes 98/99, absent data, weight zero, weighted/unweighted differences, nonrespondent skip paths.
- `survey_analysis.sav`: synthetic classification and continuous outcomes with known seeded regression/clustering structure; documented ground-truth calculations and predictable segment membership.
- `oe_truth.csv`: 30+ short synthetic responses with human-reviewed codes, multiple themes and mixed sentiment; exercise net deduplication and blank answers.
- `study_scope.md`: SOW prompting a multi-module survey with eligibility, routing, metrics and quotas.
- `tabspec_canonical.xlsx`: complete canonical workbook.
- `tabspec_external.xlsx`: one importable alternative style and one ambiguity requiring user confirmation.
- `expected_results.json`: reference bases, counts, weighted estimates, standard errors/p-values where valid, net frequencies and output expectations computed independently of implementation.

## 3. Unit test matrix

| Component | Essential assertions |
|---|---|
| Variable metadata | SPSS exact names, value labels, missing, numerical/text type, original immutable |
| Questions | unique IDs, valid routing refs, branch reachability, exclusive option consistency, ordered modules |
| Spec schemas | unique table IDs, valid banner IDs and category code references, no unresolved variables allowed in execution |
| Weights | finite, zero, missing, invalid negative, effective base, weighted denominator |
| Single response | counts sum to eligible bases and percentages per exclusive category sum approximately to 100% when exhaustive |
| Multi-response | respondent counted once per option; distinct eligible base; percentages may exceed 100% |
| Net/subnet | union-of-ID count, no double counting of respondent in parent net |
| Derived variables | correct reverse coding/grouping/filter application, path injection blocked |
| Significance | reference outputs within tolerance; no misleading p-value when assumptions cannot be met |
| Regression | coefficient direction, fit metrics, seed, sample flow, missing handling, convergence warnings |
| Clustering | feature scaling, seed reproducibility, size totals, silhouette or fit criteria |
| OE | code IDs valid, blanks accounted, reviewer override applied, hierarchy and count reconciliation |
| Export | files exist, correct content type, XLSX readable in openpyxl, DOCX readable in python-docx |
| Artifacts | semantic edits create new revision, stale dependencies, compare-and-swap conflicts |
| Sandbox | no key exposure, blocked path traversal, timed-out job termination, no network by default |

## 4. Example deterministic invariants

For each single-response non-overlapping table column, sum of unweighted category counts plus excluded/missing counts equals eligible input base, subject to explicit `show_missing` policy. With valid nonnegative weights, weighted numerator is between 0 and weighted denominator for a proportion. All displayed percentages are within 0..100; allow rounding differences. For each net: weighted/unweighted net reach cannot exceed eligible base and cannot be lower than its largest included child category. For the same filter, a union of C1 and C2 with overlap has count `n(C1) + n(C2) - n(C1 intersection C2)`. OE row-level final assignments must join to a unique response row key. For clustering, segment assignment count equals model-valid N. For regression, all narrative coefficient/metric references resolve to result fields. Reported respondent base must match the analysis sample-flow object.

## 5. Agent evaluations (non-deterministic)

Maintain a gold prompt set with exact expected *structural* requirements and quality rubric, not exact model prose. Evaluate: objective coverage, bias/wording quality, skip logic validity, whole-study coverage, correct dataset mapping, clarification appropriateness, clear noncausal interpretation, OE code consistency, and validator ability to identify injected wrong numbers. Use at least 5 questionnaires across distinct study types and 10 crosstab/analysis prompts with different missing-detail patterns. On model changes rerun the suite. An expert human should review sample questionnaire and codeframe results before acceptance; automated rubric scores alone are insufficient.

## 6. End-to-end test scripts

### E2E-1 Questionnaire and revision
Create project; upload `study_scope.md`; request complete instrument; verify structured artifact + editor; manually change Q5 option; ask chat to change skip; verify both changes remain and version increments; export DOCX; restart app, retrieve latest version.

### E2E-2 Whole-study tab spec
From active questionnaire generate spec; verify every eligible question represented or explicitly excluded; edit a banner; export XLSX; re-import and compare normalized JSON. With dataset attached, map variables and verify mapping report.

### E2E-3 Weighted crosstab
Upload `survey_small.sav`; request trust by gender using weight; compare exact stored weighted percentage, weighted/unweighted bases, net values with `expected_results.json`; open right-panel tab viewer, export table Excel; verify filename and contents.

### E2E-4 External tab spec
Upload supported noncanonical format; preview detected mapping; approve; run tables and validate; then upload ambiguous format, ensure execution is blocked until mapping is resolved. Every skipped table must appear in exception log.

### E2E-5 Advanced analysis
Request logistic regression without dependent variable; system requests missing roles. Supply dependent and predictors, filter/weight; execute and verify numerical output and actual code, report and charts. Request MaxDiff analysis: system states out of scope without silently running alternative.

### E2E-6 Coding
Select OE variable, produce/edit frame; run code batches; correct one row in UI; verify aggregates change and net counts are deduplicated; export workbook, codeframe and report; reload and preserve reviewer correction.

### E2E-7 Validator failure
Manually inject incorrect percentage into a report draft and broken route into questionnaire; validation must reject, show exact discrepancy and repair using actual computation or explicit user edit. It must not claim a successful final report.

### E2E-8 Context and general task
After questionnaire and tabs exist, request “Make a chart from the latest Q5 table and put it in a short report.” Confirm source is the latest project table, report references exact figures, sandbox/log outputs exist and artifact is viewable.

## 7. UI quality criteria

No horizontal overlap at a typical 1440px desktop width; right panel can be resized; keyboard navigation works for chat and grid editing; panel supports visible saved/unsaved/conflict states; a result that cannot be edited does not show a misleading edit button; every action has corresponding effect; numeric cell tooltips indicate weighted/unweighted bases and table notes; long tables virtualized; errors are concise and actionable.

## 8. Sign-off requirements

Pass all essential deterministic tests, backend/API integration, smoke E2Es and a manually reviewed scenario for each agent. Log known missing adapters or limitations explicitly. Never count “LLM produced reasonable sounding table” as a successful crosstab test. `TASK.md` acceptance A01–A10 must be verified with artifacts and test output.
