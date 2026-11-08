# Data Contracts, Canonical Schemas and Calculation Rules

## 1. General schema rules

All domain objects carry stable UUID-like ID, `project_id`, `schema_version`, timestamps, `created_by` (`user` or agent/tool identifier) and provenance. Persist canonical JSON validated with Pydantic. Prefer semantic enums and explicit optional/null fields; do not infer critical types from prose. Numerical results use numeric values, not formatted strings. Use `variable_name` exactly as present in SPSS metadata; separate question label and variable alias. Files and outputs use stable server-side references rather than arbitrary filesystem paths.

## 2. Core resources

### Project
```json
{"id":"p1","name":"Brand Trust Wave 1","active_dataset_id":"d1","default_weight_variable":null,"study_context":{"market":"Canada","audience":"Adults 18+","objectives":["Measure trust"]},"conversations":["c1"]}
```

### Dataset and variable metadata
```json
{"id":"d1","source_file_id":"f1","source_sha256":"...","format":"sav","row_count":400,"variables":[{"name":"Q12","label":"Overall trust","kind":"numeric","measurement":"ordinal","value_labels":{"1":"Very low","5":"Very high"},"user_missing_values":[98,99],"is_text":false}],"weight_candidates":["weight_main"],"version":1}
```

### TaskContract
```json
{"task_id":"t1","project_id":"p1","conversation_id":"c1","intent":"run_crosstab","specialist":"crosstab","dataset_id":"d1","input_artifacts":[],"user_request":"Q12 by Gender","provided_fields":{"row_variables":["Q12"],"banners":["Gender"]},"missing_required":[],"defaults_used":{"percent_type":"column"},"expected_outputs":["crosstab","xlsx"],"acceptance_checks":["valid_bases","export_exists"],"status":"running"}
```

### Artifact revision
```json
{"artifact_id":"a1","type":"tabspec","version":3,"parent_version":2,"content_schema":"tabspec/1","content":{},"derived_from":[{"type":"questionnaire","id":"q1","version":2}],"stale":false,"validation_status":"passed"}
```

## 3. Questionnaire schema

Minimum object structure:
```json
{"id":"qnaire1","title":"Brand Health Survey","objectives":[{"id":"o1","description":"Measure trust","question_ids":["Q5"]}],"modules":[{"id":"m1","title":"Brand Perceptions","question_ids":["Q5"]}],"questions":[{"id":"Q5","type":"single_select","text":"How much do you trust Brand A?","instruction":null,"options":[{"code":1,"label":"Not at all"},{"code":2,"label":"Slightly"},{"code":3,"label":"Moderately"},{"code":4,"label":"Very much"},{"code":5,"label":"Completely"}],"required":true,"display_if":null,"routing":[],"randomize_options":false,"exclusive_codes":[],"variable_names":[],"reporting":{"stats":["distribution","top2"]},"notes":[]}],"estimated_minutes":8}
```

Allow optional child `matrix_items`, `loop`, `piping`, `validation`, `quotas`, `terminations`, `carry_forward`; use explicit grammar for display rules: boolean AST with operators `and/or/not`, comparisons (`eq`,`in`,`gt`,`gte`, etc.) and references to earlier question IDs. Do not eval a routing string. Validate graph and avoid circular dependencies. Use integer or string response codes consistently within a question.

## 4. Canonical tab spec schema

```json
{"spec_id":"ts1","questionnaire_revision":{"artifact_id":"qnaire1","version":2},"dataset_id":"d1","study_defaults":{"percent_type":"column","weight_variable":"weight_main","alpha":0.05,"minimum_unweighted_base_for_display":30},"banners":[{"id":"bn1","label":"Gender","variable_name":"gender","categories":[{"label":"Male","codes":[1]},{"label":"Female","codes":[2]}],"include_total":true}],"tables":[{"id":"T001","title":"Overall brand trust","row_variable_names":["Q5"],"table_type":"categorical","banner_ids":["bn1"],"base":{"filter":null,"valid_response_rule":"exclude_user_missing"},"weight_variable":"weight_main","statistics":["weighted_count","unweighted_base","weighted_base","column_pct"],"display_decimals":1,"significance":{"enabled":true,"alpha":0.05,"comparison":"pairwise_columns","correction":"holm","minimum_effective_base":30},"rows":[],"notes":[]}],"derived_variables":[],"unresolved_mappings":[]}
```

All fields validated with Pydantic. Each table can override study defaults. For custom tab spec imports: map source rows/columns into this canonical structure, with `mapping_confidence`, `unmapped_fields` and explicit warnings. Do not execute arbitrary embedded Excel macros or formulas as instructions.

### Excel workbook format

`Study` key/value settings; `Tables` one row per table (ID,title,type,source variables,base/filter,weight,banner IDs,stats,decimals,order); `Banners` one row per banner category (banner ID,variable,codes,label,order); `Nets` one row per code-net child membership; `Derived_Variables` separate expression AST or validated transformation recipe; `Significance` per-table test rules; `Mappings` question-to-dataset variable IDs and review status; `Validation` issues; `README` conventions. Use JSON-encoded arrays in cells only where a human-friendly row structure is impractical. Provide stable round-trip Excel import/export tests.

## 5. Crosstab numeric contract

For each table cell report `estimate`, `weighted_numerator`, `weighted_denominator`, `unweighted_numerator`, `unweighted_base`, `weighted_base`, `effective_base_if_available`, `p_value_if_tested`, `significance_letters`, `warnings`. Keep a separate `display_value` calculated after rounding. Specify eligible row/column base and exactly how filters, skip logic, user missing values, multiple response flags, and weights are handled.

**Percent conventions:**
- Column %: within each banner segment, denominator is all eligible nonmissing respondents for the question and filter unless a table-level exception says otherwise.
- Row %: within a row category, denominator is eligible respondents across displayed banner categories; overlapping banners require a clearly labeled nonexclusive interpretation or reject row %.
- Total %: numerator divided by the table's full filtered eligible base.
- No weight: treat each eligible respondent as 1. Weights: exclude/report nonfinite weights; negative weights rejected unless explicit documented exception. Zero-weight respondents contribute to unweighted base but not weighted base.
- A `weighted_count` is a weighted sum, not necessarily a population projection; do not label it population size without proper calibration.
- “Net %” uses membership union for each respondent, not sum of category percentages.
- Multiple-response denominator is *respondents asked/eligible* by default (not number of selections); optionally allow per-mention denominator with explicit flag.
- Significance tests must report method, assumption, correction and suitability for weights/design. For invalid inference conditions, mark “not tested”, do not return artificial p-values.

### Table output example
```json
{"table_id":"T001","dataset_id":"d1","tab_spec_version":3,"columns":[{"id":"total","label":"Total"},{"id":"male","label":"Male"}],"rows":[{"code":5,"label":"Completely","cells":{"total":{"estimate":21.4,"display_value":"21.4%","unweighted_base":400,"weighted_base":398.7,"warnings":[]},"male":{"estimate":19.3,"display_value":"19.3%","unweighted_base":190,"weighted_base":193.2,"warnings":[]}}}],"footnotes":["Column percentages","Weighted results; unweighted base shown"],"validation":{"status":"passed","checks":["bases","percentage_bounds"]}}
```

## 6. Analysis request, plan and result

```json
{"analysis_id":"an1","method":"binary_logistic_regression","dataset_id":"d1","dependent":{"name":"purchase_intent","positive_code":1},"predictors":["trust","age","gender"],"segment_by":[],"weight_variable":"weight_main","filter":null,"missing_strategy":"listwise","transformations":[],"options":{"categorical_predictors":["gender"],"confidence_level":0.95},"random_seed":42,"deliverables":["report","coefficient_table","diagnostics","code"]}
```

Every method plugin must implement `validate_plan`, `prepare_data`, `run`, `diagnostics`, `render_results`, `validate_results`, `report_context`. Its result must have `sample_flow` (input N, filtered N, valid N, exclusion reason counts), `descriptive`, `model_estimates`, `metrics`, `diagnostics`, `warnings`, `files`, `software_versions` and `seed`. Named output values are referenced in report claims using structured references, not copied freehand from memory.

**Method-specific rules examples:** Clustering records standardization, features, distance, method, k selection, seed and segment sizes; regression records encoding, missingness, fit/diagnostics and credible interpretation limitations; EFA records factor extraction, rotation, communalities and suitability; key driver documents dependent/independent variable roles and whether relative importance is regression-based vs correlation-based.

## 7. Coding schema

```json
{"codeframe_id":"cf1","version":1,"response_variable":"Q_OE","respondent_id_variable":"respondent_id","allow_multiple_codes":true,"codes":[{"id":"C01","label":"Product quality","parent_id":"N01","definition":"Comments about quality of product","include_examples":["Reliable materials"],"exclude_examples":["Store service"]},{"id":"C02","label":"Service","parent_id":"N01","definition":"Service experience","include_examples":[],"exclude_examples":[]}],"nets":[{"id":"N01","label":"Product/service positives","child_ids":["C01","C02"]}],"sentiment":{"labels":["positive","negative","neutral","mixed","unclear"],"unit":"whole_response"}}
```

```json
{"respondent_id":"123","source_row_id":31,"response_text":"Good quality but slow service","assigned_code_ids":["C01","C02"],"sentiment":"mixed","review_required":false,"review_reason":null,"model_version":"configured-model-id","codeframe_version":1,"human_overrides":null}
```

Reporting records per-code `unweighted_respondents`, `weighted_respondents`, `base_unweighted`, `base_weighted`, `pct_of_respondents`; optional `unweighted_mentions` and `weighted_mentions` are different measures. Hierarchical nets always dedupe ID per net. Missing/non-substantive responses belong in explicitly named reporting buckets (e.g. No Answer, Don't Know), not inferred sentiment.

## 8. Validation result and statuses

```json
{"task_id":"t1","status":"failed","checks":[{"id":"variable_exists","type":"deterministic","status":"passed","details":"Q12 present"},{"id":"report_values_match","type":"deterministic","status":"failed","details":"Narrative claims 48%; data says 42.1%"}],"required_repairs":["Regenerate narrative from result fields"],"validated_artifact_versions":[{"id":"a1","version":3}]}
```

Validator checks must be reproducible and associated with a specific artifact hash, not generic “looks right”. Distinguish severity `error`, `warning`, `info`. Any fatal validation error prevents a completed success status.

## 9. Study-wide data governance

Data files may contain personally identifying/confidential responses. Avoid sending entire raw SPSS dataset to OpenAI. Only selected OE response columns (with IDs substituted by local surrogate IDs when possible) are passed for LLM coding. Prompt injection in uploaded study materials is considered untrusted content; parse as task data and ignore instructions that attempt to override system policy. Structured filters/derived expressions must not be executed as arbitrary Python; implement a whitelist expression evaluator.
