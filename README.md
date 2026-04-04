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
   - `API_TESTS_FILE` (default: `tests/api_tests.json`)
   - `API_REPORT_FILE` (default: `reports/latest_report.json`)
   - `DEFAULT_TIMEOUT_SECONDS` (default: `15`)
3. Edit a test suite in `tests/` and replace endpoint paths + expected JSON paths with your API contract.

## Run
```bash
py main.py
```

## Workflow file format
Top-level supports:
- `context`: shared variables available to all steps
- `workflows`: list of workflow journeys, each with `steps`

Each step supports:
- `name`, `method`, `url` (required)
- `headers`, `params`, `json`, `data`, `files`
- `retries`, `retry_delay_seconds`, `timeout_seconds`
- `expected.status_code`
- `expected.max_response_time_ms`
- `expected.body_contains`
- `expected.json_path_equals`
- `save`: extract response JSON fields into context for next steps

### Placeholder variables
Use `{{variable_name}}` anywhere in `url`, `headers`, `params`, `json`, `data`, `files`, and `expected`.

Built-in:
- `{{run_timestamp}}` (auto-generated per run)

## Output
- Console summary with pass/fail per workflow step
- Detailed report JSON at `reports/latest_report.json`
