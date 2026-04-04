# Bug Report: Doctor Signup Fails Under Parallel Requests

## Summary
During parallel signup testing, one request succeeds while another fails with `500 RUNTIME_ERROR` for the same endpoint, indicating a likely backend concurrency/race issue.

## Environment
- Date observed: **April 4, 2026**
- Endpoint: `POST https://dsapi.thelocal.co.in/dc/api-auth/v1/auth/doctor/signUp`
- API key header used: `ACIN-API-KEY`
- Test mode: parallel virtual users modeled as AI agents

## Evidence
From run report: [latest_report.json](c:/Users/pc/Desktop/Testing-Workflow/reports/latest_report.json)

### Run ID `1775287770`
- `agent_1`: `201` success
- `agent_2`: `500` failure
- Failure payload:
```json
{
  "success": false,
  "error": {
    "code": "RUNTIME_ERROR",
    "message": "Unexpected runtime error",
    "details": {
      "exception": "RuntimeException"
    }
  }
}
```

### Run ID `1775287584`
- Same pattern reproduced:
  - one success (`201`)
  - one failure (`500 RUNTIME_ERROR`)

## Why this looks like a bug
- Payload contract is valid (single-user signup passes with `201`).
- Request data is unique per agent (email/mobile are different).
- Failure appears only under concurrent signup execution.

## Expected behavior
Both concurrent valid signup requests should return success (`201`) or a deterministic business error, not an internal runtime exception (`500`).

## Impact
- Parallel onboarding tests are unstable.
- Real users signing up concurrently may intermittently fail.

## Suggested backend investigation
1. Check transactional boundaries and race conditions in signup flow.
2. Verify unique-index handling + exception mapping.
3. Inspect shared state/resource access under concurrent signup.
4. Add server-side correlation IDs and structured error traces for this path.
