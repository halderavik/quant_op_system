# Developer Mode Plan — External Integrations for SRAS

Status: **deferred — future implementation.** Not scheduled. Planned and discussed 2026-11-12; do not start until the owner reopens it.

## 1. Goal

Add a **Developer section** where a developer can:

1. Connect an external tool: an MCP server (Google Drive, Slack, …) or a REST API (follow-up question generator, a cross-tab engine, an open-end sentiment service).
2. Describe the tool's **role**: what it does, what it needs, what it returns, and **when the routing agent should call it**.
3. Change routing **in their own routing profile**, never in the core router.
4. Test the tool and their routing in a sandbox, with a trace of every decision and call.
5. Submit the tested integration to an **admin**, who re-tests it and is the only person who can approve it and turn it on for the platform.

## 2. Non-negotiable rule: the core platform does not change behaviour

Everything built so far (router, `build_contract`, specialists, analysis guardrails, crosstab engine, Decipher, Prolific, synthetic data) keeps working exactly as it does today, whether Developer Mode is on, off, broken, or deleted.

How that is guaranteed:

| Guarantee | Mechanism |
|---|---|
| Core never depends on dev code | New package `backend/app/devmode/`. Core modules never import it. An import-boundary test (`tests/test_devmode_isolation.py`) fails the build if any `app/agents`, `app/engines`, `app/services` module imports `app.devmode`. |
| One seam, default no-op | The orchestrator gains a single optional hook interface, `ExtensionHooks` (in core, ~40 lines), with a no-op default. Devmode registers an implementation only when `DEVMODE_ENABLED=true`. If the hook raises or times out, the orchestrator logs it and continues on the core path. |
| Separate data | Devmode uses its own database file `data/devmode.db` and storage folder `data/devmode/`. No migrations touch `studio.db`. |
| Separate projects | Developers test in **sandbox projects** (copies of fixtures or of a chosen project's metadata/datasets). Dev runs never write artifacts into real projects. |
| Core router untouched | A routing profile can only *add* routes or *claim* turns through declared rules evaluated after the core decision (§5). It cannot edit core prompts, intents, product locks (Decipher, study brief, synthetic, MaxDiff/conjoint blocker), or analysis guardrails. |
| Kill switch | `DEVMODE_ENABLED=false` removes the Developer UI, the `/api/dev/*` routes, and the hook. An admin can also disable any single live integration instantly. |
| Regression gate | The existing test suite (228 backend + 51 frontend) plus a routing golden set must pass with every live integration loaded before anything is approved. |

## 3. Roles and access (new — the app is single-user today)

`ARCHITECTURE.md` says SRAS is a local single-user app with no login. Admin approval needs identities, so Developer Mode introduces roles:

| Role | Can |
|---|---|
| Researcher (default) | Use the studio. Sees only core routes plus integrations an admin has made live. |
| Developer | Everything a researcher can, plus the Developer section: create integrations, routing profiles, sandbox projects, tests; submit for review. |
| Admin | Everything, plus the review queue, approval, staged rollout, disable/rollback, secrets for live integrations, audit log. |

Implementation: a `users` table in `devmode.db` (name, role, password hash), local login with a session cookie, and a first-run admin bootstrap from an env var. The core studio keeps working without login for the researcher role so nothing existing breaks. **Decision needed** (§12): local accounts now vs. SSO (Google/Microsoft) later.

## 4. Core concepts and contracts

### 4.1 Integration

One external system plus its connection details.

```json
{
  "integration_id": "int_followup_ai",
  "name": "Follow-up question generator",
  "kind": "rest",                    // "rest" | "mcp_http" | "mcp_stdio"
  "base_url": "https://followup-ai-questions-…herokuapp.com",
  "auth": {"type": "none"},          // none | api_key_header | bearer | oauth2 (MCP)
  "secret_refs": [],                 // names only; values live in the secret store
  "egress_allow": ["followup-ai-questions-…herokuapp.com"],
  "timeout_seconds": 20,
  "max_response_kb": 512,
  "version": 3,
  "status": "draft"
}
```

- **REST**: tools come from an imported OpenAPI file, a Postman collection, or endpoints entered by hand (method, path, request JSON schema, response JSON schema).
- **MCP**: tools come from the server's `tools/list`. Remote servers use streamable HTTP (with OAuth where the server needs it). Local `stdio` servers run as a subprocess in a container with only their declared env vars and no access to `data/`.

### 4.2 Tool card: role, triggers, data, output

The developer writes one card per tool they want the router to use. This is the "what it does and when to call it" definition.

```json
{
  "tool_id": "followup.generate",
  "integration_id": "int_followup_ai",
  "operation": "POST /generate-followup",
  "role": "Writes probing follow-up questions for a respondent's open-ended answer.",
  "use_when": [
    "The user asks for follow-up, probe, or probing questions for an open-ended question.",
    "A questionnaire question is open-ended and the user wants AI probes added."
  ],
  "do_not_use_when": ["The user wants open ends coded or a codeframe."],
  "example_requests": [
    "Suggest follow-up probes for Q12",
    "Add AI probing to the open ends in the questionnaire"
  ],
  "counter_examples": ["Code the open ends in Q12"],
  "preconditions": ["questionnaire_exists"],          // dataset_active, questionnaire_exists, oe_variable, tabspec_exists …
  "inputs": {                                          // where each request field comes from
    "question": {"from": "questionnaire.question_text", "pick": "named_in_request"},
    "response": {"from": "dataset.text_variable", "limit_rows": 50},
    "allowed_types": {"from": "constant", "value": ["reason", "elaboration"]}
  },
  "data_scope": "open_end_text",       // metadata_only | artifact_text | open_end_text | respondent_rows
  "outward_action": false,             // true for Slack post, Drive write: needs user confirmation in chat
  "output": {"artifact_type": "integration_result", "render": "table",
             "map": {"rows": "$.followups[*]", "columns": ["type", "text"]}},
  "attach_to": "route"                 // route | after:<core_intent> | provider:<core_intent>
}
```

`attach_to` controls how the tool joins the flow:

| Mode | Meaning | Example |
|---|---|---|
| `route` | A new destination the router can choose. | "Suggest probes for Q12" goes to the follow-up API. |
| `after:<intent>` | Runs after a core specialist finishes, adding to its result. It cannot change the core artifact. | After `code_open_ends`, run the sentiment API and attach sentiment as a separate artifact. |
| `provider:<intent>` | An alternative engine for a core intent. Allowed only in a dev profile; in production it needs explicit admin approval and the output must pass the core validator for that artifact type. | An external cross-tab API answering `run_crosstab`, whose tables must pass the tab-book validator. |

### 4.3 Routing profile: the developer's own router version

```json
{
  "profile_id": "prof_avik_dev_1",
  "owner": "developer user id",
  "base": "core@<git sha>",           // core router it layers on; read-only
  "enabled_tools": ["followup.generate", "slack.post_summary"],
  "rules": [
    {"match": {"keywords_any": ["probe", "follow-up question"]}, "route_to": "followup.generate", "priority": "before_core"},
    {"match": {"core_intent": "general_task"}, "consider": ["slack.post_summary"], "priority": "fallback"}
  ],
  "router_addendum": "Prefer the follow-up generator for probing questions on open ends.",
  "version": 4
}
```

- A profile is **versioned** and **owned**. It applies only in that developer's sandbox projects, or to projects an admin assigns during staged rollout.
- `router_addendum` is extra guidance for the *extension* router (§5). It is never appended to the core `_INSTRUCTIONS`.
- Rules use a small declarative language, not code: keywords, regex, core intent, preconditions, project tags. That keeps profiles reviewable and safe.

## 5. Routing design: layered, core first

Today: `choose_route` (LLM) → `build_contract` (keyword + roles) → `_dispatch` (`if intent == …`).

With Developer Mode, three layers, all inside the `ExtensionHooks` seam:

```
user turn
  │
  ├─ L0  Product locks (core, unchanged): Decipher, pasted brief, synthetic, MaxDiff/conjoint
  │        → if locked: core path, extensions never see the turn
  │
  ├─ L1  Core router (unchanged) → core intent + reason
  │
  ├─ L2  Extension router (devmode, only if a profile is active for this project)
  │        a. "before_core" rules that match strongly can claim the turn
  │        b. else, if core intent is general_task or a rule names this core intent,
  │           a separate LLM call chooses among enabled tool cards, or "keep core"
  │        c. preconditions are checked; data scope is checked against project policy
  │
  ├─ Dispatch: core specialist, or extension tool runner
  │
  └─ L3  "after:<intent>" tools run on the finished core result (non-blocking for the core reply)
```

- The extension router is its own prompt with its own model setting (`model_extension_router`). Its output schema is `{"decision": "keep_core" | "tool", "tool_id", "reason", "confidence"}`. Below a confidence threshold, the core decision stands.
- Both decisions are written to the task trace (`core_intent`, `extension_decision`, rule that fired), so the test console and admin can see exactly why a turn went where it did.
- If L2 fails (timeout, bad output, tool down), the turn runs on the core path and the trace records the failure.

## 6. Execution and safety

| Concern | Control |
|---|---|
| Secrets | Server-side secret store in `devmode.db`, encrypted with a key from the OS keyring or an env var. Never returned to the browser after entry; never written to logs, traces, or the sandbox. Dev and live secrets are separate. |
| Network | All calls go through one **integration gateway** (`httpx`) that enforces the egress allow-list, timeouts, response size caps, retries with backoff, and per-integration rate limits. The existing analysis sandbox keeps `--network none`; integrations never run inside it. |
| Respondent data | `data_scope` on each tool card is enforced by the input mapper. `metadata_only` sends no rows. `open_end_text` sends only the named text column, capped by `limit_rows`, with respondent IDs replaced by call-local tokens. Project-level policy can forbid scopes, e.g. no row data off-machine. |
| Outward actions | Tools with `outward_action: true` (Slack post, Drive write, email) draft first and require an explicit "Send" confirmation in chat before the call. |
| Untrusted output | External responses are data. They are validated against the declared response schema, shown as integration artifacts, and never fed into a core prompt as instructions. A `provider:` tool's output must pass the core validator for that artifact type before it is saved. |
| MCP stdio servers | Run in Docker with no host mounts, only declared env vars, and egress limited to the allow-list. On machines without Docker, stdio servers are disabled for live use; dev testing shows a warning. |
| Audit | Every call is logged: who, project, tool, version, request hash, response status, latency, bytes, data scope used. Payload bodies are stored only in dev sandbox runs and only when the developer opts in. |

## 7. Developer section (UI)

A new top-level **Developer** area, visible only to developer and admin roles. It is a separate React route tree (`frontend/src/devmode/`), loaded lazily, so the studio bundle is unchanged when Developer Mode is off.

1. **Catalog**: preinstalled connectors (Google Drive MCP, Slack MCP) and the developer's custom integrations, with status chips (Draft, Testing, Submitted, Live, Disabled).
2. **Add integration wizard**
   1. Type: REST or MCP.
   2. Connect: URL, auth, secret entry, or OAuth sign-in for MCP.
   3. Discover: list MCP tools, import OpenAPI/Postman, or define endpoints by hand.
   4. Health check: call the health endpoint or an MCP ping, then show latency and the result.
3. **Tool card editor**: role, use-when, do-not-use-when, examples, counter-examples, preconditions, input mapping with a live preview of what would be sent, data scope, output mapping with a preview from a sample response, and attach mode.
4. **Routing profile editor**: rules table, extension-router addendum, enabled tools, and a side-by-side view of the core router (read-only) against "your additions".
5. **Test console**
   - **Route simulator**: type a message and see the L0 lock, the L1 core intent, and the L2 extension decision with reasons. Nothing executes.
   - **Run in sandbox**: execute against a sandbox project and get the full trace: route → input mapping → request (redacted) → response → output artifact.
   - **Test suites**: saved cases of the form "message plus project state → expected route and assertions". Assertions cover status, response schema, latency, and output fields.
   - **Core regression check**: one click runs the routing golden set with the profile on and shows any turn whose core route changed.
6. **Submissions**: a submit button, enabled only when the gate passes (§8). Shows review status and admin comments.

Admin-only area:

- **Review queue**: the submitted package (manifest, tool cards, profile diff, test evidence, security checklist).
- **Admin test run**: rerun all suites in a clean admin sandbox with admin-held secrets.
- **Decision**: Approve, Request changes, or Reject, with comments.
- **Rollout**: approved, then staged to selected projects, then live for all, with one-click disable and rollback to the previous version.
- **Audit log**: every call and every state change.

## 8. Lifecycle, testing and admin approval

```
draft → testing → submitted → in_review → approved → staged → live
                     ↑            │            │          │
                     └─ changes_requested ←────┘          ├→ disabled → (rollback | retired)
                                  └→ rejected             └→ superseded by a new version
```

- A submission is an **immutable, hashed bundle**: integration manifest + tool cards + routing profile + test suite + test results + developer notes. Later edits create a new version and a new submission.
- **Submit gate** (automatic, all must pass):
  1. Every tool has at least 3 positive and 2 negative routing cases. All pass in the simulator.
  2. Contract tests pass: responses match the declared schema, including error paths (timeout, 4xx, 5xx).
  3. The core routing golden set is unchanged, except turns the profile explicitly claims and lists.
  4. Data-scope check: the redacted request preview matches the declared scope.
  5. No secret appears in traces or test outputs.
- **Admin review** (manual plus automated):
  - Rerun everything in a clean environment with the admin's secrets.
  - Add admin-written adversarial cases: prompt injection in API responses, oversized payloads, slow responses, misrouting bait.
  - Check the full backend and frontend suites with the bundle loaded.
  - Review the security checklist: egress hosts, data scope, outward actions, vendor terms and data processing.
  - Approve with a rollout plan.
- **Live**: approved tools appear in the production extension profile. Researchers see them routed automatically, and each result is labeled "via <integration name>". Error-rate and latency alerts auto-disable a live tool after a threshold, and the core path takes over.

## 9. How the examples fit

| Example | Kind | Attach | Data scope | Notes |
|---|---|---|---|---|
| Google Drive MCP (preinstalled) | MCP HTTP + OAuth | `route` (import a SOW/brief), `after:*` (save the deliverable to Drive) | artifact_text / files | Writes are outward actions and need confirmation. A brief imported from Drive feeds the existing questionnaire route as an uploaded file. |
| Slack MCP (preinstalled) | MCP HTTP + OAuth | `route` ("post the summary to #research") | artifact_text | The message is always drafted and shown before sending. Channel allow-list per project. |
| followup_ques_AI | REST, no auth (Heroku) | `route` (probes for an OE question); later `after:create_questionnaire` (offer probes for OE questions) | open_end_text (question + response) | Endpoints: `/generate-followup`, `/generate-enhanced-multilingual`, `/generate-theme-enhanced`. No OpenAPI exists, so the developer imports the Postman collection or defines endpoints by hand. It sends text to a third party that calls OpenAI, so the admin must sign off the data scope. The service has no auth or rate limits, so the gateway enforces our own limits. |
| External cross-tab API | REST | `provider:run_crosstab` (dev only until approved) | respondent_rows or aggregated | The highest-risk example. Its tables must pass the core tab-book validator (bases, nets, weights) before display. In production it should start as a second opinion shown beside core tables, not a replacement. |
| Open-end sentiment API | REST | `after:code_open_ends` or `route` ("score sentiment on Q12") | open_end_text | Output is a separate sentiment artifact and an optional derived variable, never a change to the core codeframe. |

## 10. Build phases and acceptance

| Phase | Deliver | Acceptance |
|---|---|---|
| **D0 Foundations** | `DEVMODE_ENABLED` flag, `app/devmode/` package, `devmode.db`, `ExtensionHooks` seam (no-op), import-boundary test, users/roles/login, routing golden set (~150 labeled turns from today's router). | Flag off: zero diff in behaviour, and all existing tests pass. Flag on with no integrations: same. Golden set recorded. |
| **D1 Integration registry + REST** | Integration CRUD, secret store, gateway (allow-list, timeouts, size caps, audit), OpenAPI/Postman import, manual endpoints, health check. | followup_ques_AI added from the Postman collection and `/health` succeeds. A disallowed host is blocked. Secrets never reach the API response or logs. |
| **D2 MCP client + catalog** | MCP client (streamable HTTP + OAuth, stdio in Docker), tool discovery, preinstalled Drive and Slack connectors. | Drive lists files in a test folder. A Slack post goes to a test channel only after confirmation. stdio stays blocked without Docker. |
| **D3 Tool cards + extension router** | Tool card editor, input/output mapping with previews, data-scope enforcement, routing profiles, L2 extension router, traces. | "Suggest probes for Q12" routes to followup in the dev profile and stays core without the profile. The core golden set is unchanged. |
| **D4 Test console** | Sandbox projects, route simulator, run-in-sandbox with traces, test suites, core regression check. | A developer builds a suite of at least 5 cases and runs it green. A deliberately misrouting rule is caught by the regression check. |
| **D5 Submission + admin review** | Immutable bundles, submit gate, review queue, admin rerun, adversarial pack, decisions with comments. | A failing gate blocks submit. The admin can reject, request changes, or approve, and every action is audited. |
| **D6 Live runtime** | Production extension profile, staged rollout by project, kill switch, rollback, auto-disable on errors, "via integration" labels. | An approved tool works for researchers in staged projects only. Disabling it falls back to core within one turn. |
| **D7 Reference integrations** | followup_ques_AI, sentiment API, and cross-tab API (second-opinion mode), each with full suites. | Each passes the admin gate end to end. |

Rough size: D0–D1 about 1.5 weeks, D2–D4 about 3 weeks, D5–D7 about 2.5 weeks, for one engineer with AI assistance.

## 11. Files and modules (planned)

```
backend/app/devmode/
  __init__.py          register_hooks(app) when enabled
  models.py            users, integrations, tool_cards, profiles, test_cases, runs, submissions, audit
  auth.py              roles, login, session cookie
  secrets.py           encrypted secret store
  gateway.py           HTTP client with allow-list, limits, audit
  mcp_client.py        MCP sessions (HTTP/OAuth, stdio in Docker)
  importers.py         OpenAPI + Postman → operations
  mapping.py           tool-card input mapping + data-scope enforcement; output mapping
  ext_router.py        L2 extension router (rules + LLM)
  hooks.py             ExtensionHooks implementation
  testing.py           simulator, suites, golden-set regression
  review.py            submission bundles, gate, admin decisions, rollout
  api.py               /api/dev/* and /api/admin/* routes
backend/app/agents/extension_hooks.py   the only core addition: interface + no-op
frontend/src/devmode/                    lazily loaded Developer and Admin areas
tests/devmode/                           unit, contract, isolation, golden-set tests
```

## 12. Decisions needed before D0

1. **Accounts**: local username and password for developer and admin now, with SSO later? Or SSO from the start?
2. **Where this runs**: SRAS is local and single-user today. Will developers and admins share one hosted instance? Admin review on another person's machine needs a shared server. That changes how secrets, the database, and OAuth callbacks work.
3. **Data leaving the machine**: should the default project policy allow `open_end_text` to go to approved third parties, or start at `metadata_only` and require per-project opt-in?
4. **Provider mode for core intents** (for example, an external cross-tab replacing core): allow it at all in production, or keep external engines as a second opinion beside core output?
5. **Preinstalled MCPs**: Google Drive and Slack only for v1, or also Microsoft 365 (SharePoint/Teams)?

## 13. Recommended answers (discussed 2026-11-12, not yet confirmed)

These are the recommendations from the planning discussion. The owner parked the work as future implementation before confirming them, so treat them as the starting position, not as decisions.

1. **Accounts**: local accounts first (users table, hashed passwords, session cookie, first admin from an env var), with permissions tied to roles rather than to the login method so SSO can be added later. Researchers keep using the studio without login while it is local.
2. **Where this runs**: developer submit → admin approve needs a shared instance. Build D0–D4 so they run locally, and add a hosting phase before D5: Postgres instead of SQLite, HTTPS, backups, and a sandbox on the server. **Open question:** where would it be hosted (Azure, AWS, internal server)?
3. **Data leaving the machine**: default `metadata_only`. An admin can allow `open_end_text` per project for named approved integrations, and the user sees a notice before each send. `respondent_rows` also needs a recorded vendor agreement. The follow-up question API needs this opt-in, because it sends answers to Heroku and on to OpenAI.
4. **Replacement engines**: in production, external engines are shown beside core results with an automatic comparison and difference flags, never instead of them. Full replacement is allowed only in dev test projects, and later only by a separate admin decision for that engine. **Open question:** confirm this.
5. **Built-in connectors**: Google Drive and Slack for v1, with Microsoft 365 as the first connector after v1. Slack posts only to channels an admin approves for each project.
