# Testing_Workflow

API-first testing app powered by **LangGraph** for multi-step journeys (signup -> signin -> post -> feed).

## What it does
- Runs API tests as a LangGraph workflow
- Supports journey-style test suites with sequential steps
- Shares data across steps using context variables (token, user ID, post ID, etc.)
- Supports `GET`, `POST`, `PUT`, `PATCH`, `DELETE`
- Validates status code, response time, text contains, and JSON-path equality
- Supports retry + retry delay per step
- Generates a JSON report after each run

## Setup
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Update `.env` if needed:
   - `API_TESTS_FILE` (default: `tests/overall_suite.json`)
   - `API_REPORT_FILE` (default: `reports/latest_report.json`)
   - `DEFAULT_TIMEOUT_SECONDS` (default: `15`)
3. Edit `tests/overall_suite.json` and replace endpoints/expectations with your API contract.

## Run

**Doctor Auth + Post Service suite (default):**
```bash
py main.py
```

**Referral Service suite:**
```bash
API_TESTS_FILE=tests/referral_suite.json API_REPORT_FILE=reports/referral_report.json py main.py
```
On Windows (PowerShell):
```powershell
$env:API_TESTS_FILE="tests/referral_suite.json"; $env:API_REPORT_FILE="reports/referral_report.json"; py main.py
```

Ollama-backed duplicate workflow:
```bash
py main_ollama.py
```

**Referral Service suite (Ollama-backed):**
```bash
API_TESTS_FILE=tests/referral_suite.json API_REPORT_FILE=reports/referral_ollama_report.json py main_ollama.py
```
On Windows (PowerShell):
```powershell
$env:API_TESTS_FILE="tests/referral_suite.json"; $env:API_REPORT_FILE="reports/referral_ollama_report.json"; py main_ollama.py
```
Agentic Ollama doctor-simulation layer:
```bash
py main_agentic_ollama.py
```
Streamlit UI for the agentic API simulation:
```bash
streamlit run streamlit_agentic_app.py
```
Environment knobs:
- `OLLAMA_BASE_URL` (default: `http://127.0.0.1:11434`)
- `OLLAMA_MODEL` (default: `llama3.1`)
- `OLLAMA_TEXT_MODEL` (default fallback: `OLLAMA_MODEL`, example: `gemma:7b`)
- `DOCTOR_IDENTITY_MODE=ollama` for the duplicated workflow, or `pool` / `template` if you want to override it
- `AGENTIC_USE_OLLAMA_PLANNER=true` to let the new layer choose doctor actions dynamically
- `API_KEY` (required) — sent as the `ACIN-API-KEY` header on every request; `load_suite()` injects it into the suite context. Set in `.env` (see `.env.example`).
- `AGENTIC_API_TESTS_FILE` / `API_TESTS_FILE` (default: `tests/unified_comprehensive_suite.json`)
- `AGENTIC_API_REPORT_FILE` / `API_REPORT_FILE` (default: `reports/latest_report_ollama.json`)
- Optional extra dependencies for Ollama post/image generation are listed in `requirements_ollama.txt`
- Diffusers image generation uses `DIFFUSERS_MODEL` (default: `runwayml/stable-diffusion-v1-5`) and can be disabled with `OLLAMA_USE_DIFFUSERS_IMAGES=false`

## Agentic Layer
`main_agentic_ollama.py` runs a higher-level doctor simulation layer on top of the Ollama workflow. Instead of executing the full test suite in a fixed order, each doctor agent:
- generates its own identity, profile, and behavior context
- plans a realistic action sequence such as signup, profile completion, search, posting, and engagement
- adapts lightly to system state, for example creating a post after an empty feed or following post creation with profile-post/detail checks

This mode is meant for “doctor-like usage simulation” rather than only deterministic API coverage.

## Streamlit UI
`streamlit_agentic_app.py` provides a small dashboard for the agentic API simulation. It lets you:
- launch the agentic Ollama run from the browser
- change key run settings such as tests file, report file, total agents, parallel agents, max actions, and identity mode
- inspect run summary, failed actions, and per-agent action history
- review the raw JSON report without opening files manually

## Test Suites

| File | Service | Workflows | Steps | Notes |
|---|---|---|---|---|
| `tests/unified_comprehensive_suite.json` | Auth + Profile + Post + Discovery + Referral + Credit + Cancel | 7 | 49 | Default for all runners (see `testing_workflow_core/settings.py`) |
| `tests/overall_suite.json` | Auth + Post + Network | 2 | 21 | Smaller subset suite |
| `tests/overall_suite_ollama.json` | Auth + Post + Network + Referral + Credit + Cancel | 6 | 44 | Wider non-discovery superset |
| `tests/referral_suite.json` | Referral Service | 5 | 29 | Referral-only; requires `virtual_users >= 2` |
| `tests/comprehensive_suite.json` | Auth + Profile + Post + Referral Auth + Referral + Credit + Cancel | 7 | 50 | Variant that includes the Referral Auth workflow instead of Doctor Discovery |

### Referral Suite — `tests/referral_suite.json`

Covers all endpoints from the DocSynapse Referral Service:

| Workflow | Steps | Description |
|---|---|---|
| Referral Auth + Master Data | 6 | SignUp, SignIn, get specializations, get doctors |
| Referral CRUD | 9 | Create, read, update, count, remind referral |
| Referred Doctor Accept Flow | 4 | Peer accepts referral, updates patient status |
| Credit Point Tracking | 5 | View and update credit point status |
| Cancel & Delete | 4 | Cancel a PENDING referral, then delete it |

**Requirements:**
- `virtual_users: 2` (set in the suite's `run` config) so each agent has a real peer to refer to and accept on behalf of.
- The `Referred Doctor Accept Flow` and `Get Credit Points By Receiver` steps use `{{peer_access_token}}` — they are automatically skipped if only one virtual user runs.
- The `Get All Referred for Cancel` step uses `size=1` and assumes the API returns the most-recently-created referral as `content[0]`. If the API sorts oldest-first, the cancel step will attempt to cancel the wrong referral and will receive an appropriate error from the server.

**Known API quirks (preserved as-is):**
- `POST /cancelled-referred` field name has a typo in the URL ("cancelled" vs "canceled") — matches the live API.
- `POST /update-referral` body field is `refferalId` (double-f) — matches the live API.
- `POST /send-reminder` body uses `creatorId` but expects the **referred doctor's** ID, not the creator's.
- `POST /frequenty-referred-doctor` URL typo ("frequenty") — matches the live API.

## Workflow file format
Top-level supports:
- `run`: runtime settings such as `virtual_users`, `iterations_per_user`, `default_timeout_seconds`, `default_retries`, `think_time_ms`
- `context`: shared variables available to all steps
- `workflows`: list of workflow journeys, each with `steps`

Each workflow supports:
- `name`
- `enabled`
- `steps`

Each step supports:
- `name`, `method`, `url` (required)
- `headers`, `params`, `json`, `data`, `files`
- `required_fields`: list of dot-paths such as `json.email` or `json.experience.0.companyId` that must be present and non-empty before the request is sent
- `retries`, `retry_delay_seconds`, `timeout_seconds`
- `expected.status_code`
- `expected.max_response_time_ms`
- `expected.body_contains`
- `expected.json_path_equals`
- `save`: extract response JSON fields into context for next steps

The engine also accepts the design-style nested schema and normalizes it automatically:
- `request.method`, `request.url`, `request.headers`, `request.params`, `request.json`, `request.data`, `request.files`
- `policy.timeout`, `policy.retries`, `policy.retry_delay`, `policy.retry_on_status_codes`
- `assert.status_code`, `assert.max_response_time_ms`, `assert.body_contains`, `assert.json_path_equals`
- `extract`

### Placeholder variables
Use `{{variable_name}}` anywhere in `url`, `headers`, `params`, `json`, `data`, `files`, and `expected`.

Built-in:
- `{{run_timestamp}}` (auto-generated per run)

## Output
- Console summary with pass/fail per workflow step
- Detailed report JSON at `reports/latest_report.json`
