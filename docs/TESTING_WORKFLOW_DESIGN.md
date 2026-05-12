# LangGraph Testing Workflow Design (API-First)

## 1) Purpose
Design a clean, understandable, and scalable testing workflow for a doctor-focused social app (LinkedIn-style), using API-based testing with LangGraph orchestration.

This document is design-only. No implementation changes are included.

Also keep the system integration-friendly so MCP servers and multiple testing frameworks can be plugged in without redesigning the core flow.

## 2) Product Testing Goals
- Test realistic user journeys (as humans use the app), not only isolated endpoints.
- Support parallel execution with multiple virtual users.
- Use random doctor data for registration to avoid collisions.
- Keep architecture modular: agent responsibilities are clear and easy to maintain.
- Keep test definitions declarative in JSON/YAML so non-core-devs can update test cases.

## 3) Phase 0: API Contract Discovery (Must Complete First)
Before implementation, we must define what each API requires, what it returns, and how test workflow should handle it.

### 3.1 Endpoint contract template (fill for each endpoint)
- Endpoint name
- Method + path
- Auth requirement (none, bearer token, refresh token, role)
- Required headers
- Required params/path/query keys
- Required body fields
- Optional body fields
- Validation constraints (length, format, enum, regex)
- Success status codes
- Error status codes and error payload shape
- Response payload schema (key fields)
- Extractable values for next steps (token, user_id, post_id, etc.)
- Idempotency/duplicate behavior (for retries)
- Rate-limit behavior

### 3.2 Minimum endpoint set for first implementation
1. Registration API
2. Login API
3. Create post API
4. Feed/listing API
5. Post details API

### 3.3 Handling policy per endpoint
- Retryable failures: timeout, 5xx, explicit transient codes only.
- Non-retryable failures: validation 4xx, auth mismatch.
- Extraction rules: only from successful response schema.
- Redaction rules: token/password/PII masked in logs and reports.
- Detailed contract table moved to `docs/DOCTOR_SIGNUP_CONTRACT_TABLE.csv` (Excel-friendly).

## 4) Scope
### In Scope
- API workflow testing
- Multi-step journeys (register -> login -> post -> view feed -> view post, etc.)
- Parallel user simulation
- Per-step assertions and extracted variables
- Reporting (summary + per-step details)

### Out of Scope (for initial version)
- Browser/UI automation (Playwright/Selenium)
- Advanced load-testing features (ramp profiles, p95 graphs, distributed runners)
- Direct database mutation during test runs

Note: DB checks can be included as optional read-only verification phase if needed later.

## 5) Core Architecture
The workflow uses specialized agents (or nodes) with single responsibilities:

1. Suite Planner Agent
- Validates test suite file.
- Expands workflows into executable step plans.
- Builds run metadata.

2. User Context Agent
- Creates per-user context.
- Generates random doctor profile data.
- Resolves placeholders and derived variables.

3. Request Executor Agent
- Sends HTTP requests.
- Applies retry and timeout policies.
- Captures request/response telemetry.

4. Assertion Agent
- Runs validations for status, latency, body contains, JSON path equals, schema (optional).
- Produces actionable failures.

5. State Extractor Agent
- Extracts values (token, user_id, post_id, etc.) from responses.
- Stores them in that user’s isolated runtime context.

6. Orchestrator Agent
- Controls journey step transitions.
- Handles retry routing and stop/continue decisions.

7. Reporter Agent
- Produces consolidated results across all virtual users.
- Outputs machine-readable and human-readable reports.

## 6) Agent Count and Specification (Initial)
Start with a minimal, clean set of agents. Add more only if complexity demands it.

### 6.1 Recommended initial agents (5)
1. Contract Agent
- Validates API contract completeness before test run.
- Fails fast for missing required contract pieces.

2. Data Agent
- Generates random doctor data per virtual user.
- Maintains reproducible randomness with optional seed.

3. Execution Agent
- Sends API requests with timeout/retry policy.
- Captures telemetry (latency, status, sanitized response preview).

4. Validation Agent
- Evaluates assertions against API contract + test step rules.
- Produces clear failure reasons.

5. Reporting Agent
- Aggregates per-user and global results.
- Writes console + JSON/optional markdown report.

### 6.2 Agent IO contract
- Input: `run config`, `api contract`, `user context`, `step definition`
- Output: `step result`, `updated context`, `assertion outcomes`, `trace logs`

## 7) Tools Needed (Initial)
Keep toolset small and explicit:

1. `http_request_tool`
- Executes request with timeout/retry hints.

2. `template_render_tool`
- Resolves placeholders from context.

3. `json_path_tool`
- Reads fields from JSON response for assertions/extraction.

4. `assertion_tool`
- Status, latency, contains, json-path equals, optional schema checks.

5. `data_factory_tool`
- Creates random doctor profile payloads.

6. `redaction_tool`
- Masks secrets and PII in logs/reports.

7. `report_writer_tool`
- Emits run summary and detail reports.

8. `mcp_resource_tool` (optional but recommended)
- Reads external test resources through MCP (contracts, datasets, environment metadata, optional verification data).
- Keeps external dependencies decoupled from core runner logic.

9. `framework_adapter_tool`
- Provides a common interface for multiple execution/assertion backends (internal engine, pytest/newman/k6 adapters, etc.).
- Allows incremental adoption of additional frameworks.

## 8) Parallel Execution Model (Human-like Access)
### Concept
- A virtual user represents one human session.
- Each virtual user runs full journey flows sequentially.
- Multiple virtual users run in parallel.

### Proposed behavior
- `virtual_users`: number of concurrent user sessions.
- `iterations_per_user`: number of journey loops per user.
- Optional `think_time_ms` between steps to mimic human pauses.
- Isolated context per user to avoid token/data leakage.

### Why this model
- Preserves realistic dependency chain within each user (register -> login -> post).
- Adds concurrency across users to expose race and contention issues.

## 9) Data Strategy: Random Doctor Registration
Each virtual user should generate unique values:
- email: `doctor.{run_id}.{user_id}.{rand}@domain.com`
- phone/license IDs (if required): randomized suffix patterns
- name/specialization can be sampled from test dictionaries

Best practices:
- Keep deterministic option with seeded RNG for reproducibility.
- Save generated values in user context for subsequent steps.

## 10) Test Suite Definition (Design Schema)
Top-level:
- `run`: runtime settings
- `context`: shared defaults
- `workflows`: list of journey definitions

`run` example fields:
- `virtual_users`
- `iterations_per_user`
- `max_parallel_workflows` (optional)
- `default_timeout_seconds`
- `default_retries`
- `think_time_ms`

Each workflow:
- `name`
- `enabled`
- `steps`

Each step:
- `name`
- `request`: method, url, headers, params, json/data
- `policy`: timeout, retries, retry_delay
- `assert`: status_code, max_response_time_ms, body_contains, json_path_equals
- `extract`: map of `context_key -> json_path`
- `depends_on` (optional future extension)

## 11) Placeholders and Context Resolution
Use placeholders like `{{access_token}}`, `{{post_id}}`, `{{doctor_email}}`.

Resolution order:
1. Per-step locals
2. Per-user context
3. Shared context
4. Built-ins (`run_id`, `timestamp`, `user_index`)

If unresolved:
- Step fails with explicit missing-variable error.

## 12) API vs SQL Role Clarification
Primary mechanism: API tests.

SQL in this system should be optional and used only for verification when needed, for example:
- Confirm user record exists after registration.
- Confirm post persistence fields.

Recommended policy:
- Keep SQL checks read-only.
- Run SQL checks as separate verification steps, not mixed inside API execution.
- Require explicit environment opt-in for DB credentials.
- Prefer MCP-based DB/resource connectors where possible, to avoid hard-coding direct DB client logic in the runner.

## 13) Failure Handling and Retries
- Retry only request execution failures/eligible status conditions.
- Assertion failures are reported clearly and may be configured as non-retriable by default.
- Continue-on-failure policy configurable at workflow level.

## 14) Reporting Design
### Required outputs
1. Console summary
- total steps, pass/fail counts, duration
- pass rate by workflow

2. JSON report
- run metadata
- per-user timelines
- per-step request/response stats
- assertion error details

3. Optional markdown report
- quick view for team sharing

## 15) Observability and Debuggability
Capture for each step:
- request method/url
- sanitized headers
- status code
- response time
- short response preview
- exact assertion failure reasons

Optional extensions:
- correlation IDs
- structured logs

## 16) Security and Compliance
- Never log secrets/tokens in plaintext report.
- Redact sensitive headers and PII fields.
- Keep generated test user data clearly tagged as synthetic.

## 17) Minimal Milestone Plan
Phase 1: Contract-first single-user journey framework
- API contract validation + clean agent boundaries

Phase 2: Parallel virtual users
- Concurrency + isolated contexts + aggregated report

Phase 3: Robustness
- Better retries, redaction, optional SQL verification hooks

Phase 4: MCP + framework interoperability
- MCP connectors for contract/data/verification sources
- Adapter layer to support multiple frameworks under one declarative suite model

## 18) Open Decisions (Review Needed)
1. Concurrency defaults
- Suggested start: `virtual_users=5`, `iterations_per_user=1`

2. Retry policy
- Suggested start: `retries=1`, `retry_delay=0.5s`

3. Continue-on-failure behavior
- Suggested: continue within user flow but mark failure

4. SQL verification
- Enable now or keep for Phase 3?

5. MCP adoption scope
- Start with contract + test data sources only, or include DB verification MCP in first pass?

6. Framework mix
- Keep only internal LangGraph runner initially, or enable adapters for pytest/newman/k6 in Phase 1/2?

## 20) MCP Integration Concept
### Why MCP here
- Centralizes external resources (contracts, datasets, env metadata, optional verification sources).
- Reduces tight coupling between test workflow engine and infrastructure-specific clients.
- Improves portability across projects/environments.

### MCP usage model
1. Pre-run:
- Fetch API contract and optional shared test datasets from MCP.
- Validate resource availability before run starts.

2. In-run:
- Resolve optional dynamic data via MCP lookups (read-only by default).
- Keep runtime fallback behavior explicit if MCP source is unavailable.

3. Post-run:
- Optionally publish reports/artifacts to MCP-backed storage.

### Guardrails
- Default to read-only MCP operations.
- Explicit opt-in for sensitive sources.
- Apply redaction before writing logs/reports externally.

## 21) Multi-Framework Integration Concept
### Goal
Keep one declarative suite format while allowing multiple execution frameworks behind a stable adapter interface.

### Adapter contract (design-level)
- `prepare(run_config, suite, contract)`
- `execute_step(step, context, policy)`
- `validate(result, assertions, contract)`
- `extract(result, extract_rules)`
- `teardown()`

### Suggested adapter types
- `langgraph_native_adapter` (primary default)
- `pytest_adapter` (for ecosystem/plugin leverage)
- `postman_newman_adapter` (collection-based teams)
- `k6_adapter` (performance-oriented extensions later)

### Selection policy
- Per-run adapter selection via config, e.g. `run.framework: "langgraph_native"`.
- Keep assertion/extraction semantics consistent across adapters.
- If an adapter lacks a feature, fail with a clear capability error.

## 19) Example design-level config (illustrative)
```json
{
  "run": {
    "virtual_users": 5,
    "iterations_per_user": 1,
    "default_timeout_seconds": 15,
    "default_retries": 1,
    "think_time_ms": [200, 1200]
  },
  "context": {
    "base_url": "https://api.your-doctor-app.com"
  },
  "workflows": [
    {
      "name": "Doctor Journey",
      "enabled": true,
      "steps": [
        {
          "name": "Register",
          "request": {
            "method": "POST",
            "url": "{{base_url}}/auth/register",
            "json": {
              "name": "{{doctor_name}}",
              "email": "{{doctor_email}}",
              "password": "{{doctor_password}}",
              "specialization": "{{specialization}}"
            }
          },
          "assert": {
            "status_code": 201
          },
          "extract": {
            "doctor_id": "data.user.id"
          }
        },
        {
          "name": "Login",
          "request": {
            "method": "POST",
            "url": "{{base_url}}/auth/login",
            "json": {
              "email": "{{doctor_email}}",
              "password": "{{doctor_password}}"
            }
          },
          "assert": {
            "status_code": 200
          },
          "extract": {
            "access_token": "data.token"
          }
        },
        {
          "name": "Create Post",
          "request": {
            "method": "POST",
            "url": "{{base_url}}/posts",
            "headers": {
              "Authorization": "Bearer {{access_token}}"
            },
            "json": {
              "content": "Clinical insight {{timestamp}}",
              "visibility": "public"
            }
          },
          "assert": {
            "status_code": 201
          },
          "extract": {
            "post_id": "data.post.id"
          }
        },
        {
          "name": "View Feed",
          "request": {
            "method": "GET",
            "url": "{{base_url}}/feed",
            "headers": {
              "Authorization": "Bearer {{access_token}}"
            }
          },
          "assert": {
            "status_code": 200
          }
        }
      ]
    }
  ]
}
```

---
If this design is approved, implementation will follow this structure exactly and in phases.
