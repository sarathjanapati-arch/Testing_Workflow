# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

API-first testing harness for a doctor-focused social platform (DocSynapse). Test journeys (signup → signin → post → feed → referral → credit) are declared as JSON suites and executed by a LangGraph state machine with parallel virtual users. There are three orchestration variants on top of a shared core, plus a Streamlit dashboard.

## Run commands

All entrypoints sit at the repo root and just call `runner.run()` on their package:

```bash
py main.py                      # deterministic suite (testing_workflow)
py main_ollama.py               # same as main.py but sets DOCTOR_IDENTITY_MODE=ollama before running
py main_agentic_ollama.py       # agentic: each doctor agent plans its own action sequence
streamlit run streamlit_agentic_app.py   # dashboard front-end for the agentic runner
```

**Dry-run simulation (no real HTTP calls, no API key needed):**
```bash
python -X utf8 simulate_agents.py                                    # all 3 identity modes, 2 agents
python -X utf8 simulate_agents.py --mode ollama --agents 3           # Ollama identities only
python -X utf8 simulate_agents.py --mode template --no-steps         # context only, skip step rendering
python -X utf8 simulate_agents.py --workflows "Doctor Auth + Profile" --mode template
```
The simulation reads real CSVs from `data_exports/` for company/specialization picks, renders all placeholder-substituted request bodies, and shows the agentic action plan — useful for verifying suite changes before hitting live APIs.

Default suite/report paths come from `testing_workflow_core/settings.py`. Override per run with env vars (Windows PowerShell):
```powershell
$env:API_TESTS_FILE="tests/referral_suite.json"; $env:API_REPORT_FILE="reports/referral_report.json"; py main.py
```

`AGENTIC_API_TESTS_FILE` / `AGENTIC_API_REPORT_FILE` take precedence over `API_TESTS_FILE` / `API_REPORT_FILE` when both are set — all three runners read the same `load_settings()`. The default fallback is `tests/unified_comprehensive_suite.json` → `reports/latest_report_ollama.json`.

There is no test runner, linter, or build step configured. Dependencies: `pip install -r requirements.txt` (add `requirements_ollama.txt` for Ollama/diffusers).

**Required setup:** copy `.env` and set `API_KEY` — it is injected as the `ACIN-API-KEY` header on every request. Without it, all steps will 401.

Core env vars (all optional except `API_KEY`):

| Env var | Default | Purpose |
|---|---|---|
| `API_KEY` | — | **Required.** Sent as `ACIN-API-KEY` on every request |
| `DEFAULT_TIMEOUT_SECONDS` | `15` | Per-request HTTP timeout |
| `DOCTOR_IDENTITY_MODE` | `template` | `template` \| `pool` \| `ollama` |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama endpoint |
| `OLLAMA_MODEL` | `llama3.1` | Model for identity/planning |
| `OLLAMA_TIMEOUT_SECONDS` | `60` | Per-LLM-call timeout — set to `120`+ for large models |
| `GENERATE_IMAGES` | `false` | Enable image generation |
| `DIFFUSERS_MODEL` | `runwayml/stable-diffusion-v1-5` | SD model for post images |

## Architecture

### The three runners are thin wrappers

`testing_workflow/` and `testing_workflow_ollama_agentic/` are each ~3-line modules that wire a LangGraph `StateGraph` and delegate to [testing_workflow_core/](testing_workflow_core/). Don't duplicate logic into them — put it in core.

There is **no separate `testing_workflow_ollama/` package**. `main_ollama.py` just sets `DOCTOR_IDENTITY_MODE=ollama` and calls `testing_workflow.runner.run()`. The Ollama toggle is purely env-var-driven.

- `testing_workflow` uses a 5-node graph: `load_suite → contract_validate → prefetch_master_data → execute_sample_workflow → finalize_report`. Graph construction is in [testing_workflow_core/graph_common.py](testing_workflow_core/graph_common.py); shared node implementations are in [testing_workflow_core/nodes_common.py](testing_workflow_core/nodes_common.py). The orchestrator that wires settings → graph invocation lives in [testing_workflow_core/runner_common.py](testing_workflow_core/runner_common.py).
- `testing_workflow_ollama_agentic` uses a 4-node graph (no contract validation): `load_suite → prefetch_master_data → execute_agentic_sessions → finalize_report`. Has its own `nodes.py`/`session.py` for LLM-driven action planning, and writes partial reports during execution (`AGENTIC_PARTIAL_REPORTING`).

### Suite execution lives in core

All HTTP execution, retries, redaction, peer-doctor coordination, and catalog lookups are in [testing_workflow_core/execution.py](testing_workflow_core/execution.py). The agentic runner re-uses these via the public adapter names exported at the bottom of that file (`execute_step`, `ensure_peer_context`, `register_signed_in_agent`, etc.) — preserve those names when refactoring.

Per virtual user, `_execute_agent` builds a context dict, then for each iteration:
1. Generates persona/identity/profile/behavior/social-content via [doctor_persona.py](testing_workflow_core/doctor_persona.py) and [image_generation.py](testing_workflow_core/image_generation.py).
2. Picks a company + specialization deterministically from `data_exports/companies.csv` + `data_exports/main_specializations.csv` (catalog position seeded by run timestamp + user/iteration index — same agent gets the same picks across reruns within a window).
3. Walks each enabled workflow's steps, rendering `{{placeholders}}` via [template.py](testing_workflow_core/template.py), validating `required_fields`, executing, then `save`-ing fields into the next step's context.

Concurrency is `ThreadPoolExecutor(max_workers)`. A `shared_doctor_registry` (`dict[user_index, {doctor_id, doctor_email, access_token}]`) guarded by `registry_lock` lets agents discover signed-in peers — any step containing `{{peer_doctor_id}}`/`{{peer_access_token}}` triggers `_ensure_peer_context` which polls the registry up to 8s. Suites that use peer placeholders must set `run.virtual_users >= 2`.

### Doctor identity modes

Controlled by `DOCTOR_IDENTITY_MODE` env var. All three modes produce the same context keys:

- **template** (default): Deterministic identities built from fallback name/board/bio lists, seeded by `run_timestamp + user_index + iteration_index` via `agent_seed()` in [seed.py](testing_workflow_core/seed.py).
- **pool**: Pre-computed pool of 1000 unique identities built once at module load; agents index into it deterministically. Faster than template for large runs.
- **ollama**: LLM-generated identities fetched from local Ollama via JSON prompt. Requires Ollama running locally.

Image generation (`generate_images_for_agent()`) produces three images per iteration: profile (512×512 gradient + initials), cover (1200×400 gradient + name), and post (1080×1080 via Stable Diffusion, falling back to gradient + text). Output lands in `output/run_{timestamp}/agent_{user}/iter_{iteration}/`.

Social post generation in [image_generation.py](testing_workflow_core/image_generation.py) uses `langchain-ollama` (`OllamaLLM` + `RunnableSequence`, i.e. `prompt | llm`). The deprecated `LLMChain` + `langchain_community.llms.Ollama` path is kept as a fallback if `langchain-ollama` is not installed. When modifying the post chain, use `.invoke()` not `.run()` — `.run()` is `LLMChain`-era API and will fail on a `RunnableSequence`.

### Agentic runner specifics

`testing_workflow_ollama_agentic/session.py` drives per-doctor agent simulation. Key concepts:

- **Functional groups** (`FUNCTIONAL_GROUPS` dict): Maps logical feature areas (auth_profile, social_network, referral_system, etc.) to their constituent step names. `FUNCTIONAL_DEPENDENCIES` tracks prerequisites between groups. Controlled by `AGENTIC_FUNCTIONAL_GOALS` env var (comma-separated).
- **Action library**: Maps internal action names (`"signup"`) to suite step names (`"Doctor SignUp"`), letting the LLM planner reference actions symbolically.
- **LLM planner**: When `AGENTIC_USE_OLLAMA_PLANNER=true`, Ollama plans the action sequence. Otherwise agents execute deterministically through enabled functional groups.
- **Partial reporting**: When `AGENTIC_PARTIAL_REPORTING=true`, `reports.py` writes incremental updates as agents complete rather than waiting for all to finish.

Agentic-specific env var overrides (set by dashboard sidebar or directly):

| Env var | Purpose |
|---|---|
| `AGENTIC_VIRTUAL_USERS` | Number of concurrent doctor agents |
| `AGENTIC_MAX_WORKERS` | ThreadPoolExecutor size |
| `AGENTIC_ITERATIONS_PER_USER` | Iterations per agent |
| `AGENTIC_MAX_ACTIONS` | Action cap per agent |
| `AGENTIC_SIGNUP_FAILURE_LIMIT` | Abort agent after N signup failures |
| `AGENTIC_AUTH_RESET_LIMIT` | Re-auth threshold |
| `AGENTIC_USE_OLLAMA_PLANNER` | LLM-driven action planning |
| `AGENTIC_PROGRESS_LOGGING` | Log agent progress to stdout |
| `AGENTIC_PARTIAL_REPORTING` | Incremental report writes |
| `AGENTIC_FUNCTIONAL_GOALS` | Comma-separated functional groups to enable |

### Suite file shape

Both flat (`method`/`url`/`expected`/`save`) and nested (`request.*`/`assert.*`/`policy.*`/`extract`) step schemas are accepted — [suite_loader.py](testing_workflow_core/suite_loader.py) normalizes nested → flat at load time. Don't write code that only handles one shape; it'll break on the other suite style.

Steps support `depends_on: <step name>`: dependent steps auto-skip if the named step didn't pass in this iteration.

**Suite authoring rule — no hardcoded per-doctor values in step bodies.** Every field that varies by doctor (job title, education school, field of study, degree, language, skill, consultation modes, start dates) must be a `{{placeholder}}` drawn from `GENERATED_CONTEXT_KEYS`. Hardcoding e.g. `"jobTitle": "Senior Cardiologist"` or `"schoolName": "Andhra Medical College"` sends mismatched data regardless of the doctor's actual specialization. The template fallback in `_fallback_profile_context` produces 15 varied Indian medical colleges, multiple degree types, and per-agent experience dates — all seeded by `rng` so each agent is distinct.

Built-in placeholder context keys (always present, validation won't flag them): see `BUILTIN_CONTEXT_KEYS` in [validation.py](testing_workflow_core/validation.py). Persona-generated keys (same set for all three identity modes) live in `GENERATED_CONTEXT_KEYS` — when adding a new generated field, register it there or contract validation will reject every suite that uses it. Master-data keys (company_id, specialization_id, etc.) live in `MASTER_DATA_CONTEXT_KEYS`.

### Redaction is enforced in execution, not at report-write time

`_redact_value` (in execution.py) walks dicts/lists and masks anything matching `SENSITIVE_KEYS` / `PII_KEYS` (token/password/email/mobile/name family). It runs on `request_snapshot`, `request_headers`, `response_preview`, and `agent_summary` fields *as they are built*. New report fields containing user data must be passed through `sanitize_report_value` / `_sanitize_request_snapshot` — don't bypass these.

### Step-name-driven retry overrides

`_execute_step` upgrades retries for steps whose `name` (case-insensitive) is `"Doctor SignUp"` (≥2 retries, 0.5s delay) or `"Doctor SignIn"` (≥5 retries, 1.0s delay; also retries on 401). This is intentional — the live API is flaky on these. Don't generalize it away unless the user asks.

### Known live-API quirks preserved in suites

The referral service has misspelled URLs and field names (`cancelled-referred`, `refferalId`, `frequenty-referred-doctor`); `send-reminder` takes the *referred* doctor's id under `creatorId`. Suites mirror these on purpose — don't "fix" them.

### Streamlit dashboard

[testing_workflow_dashboard/](testing_workflow_dashboard/) is a self-contained UI over the agentic runner. The sidebar collects ~15 configurable parameters (virtual_users, max_workers, iterations_per_user, identity_mode, use_ollama_planner, generate_posts, generate_images, functional_goals multi-select, etc.), sets them as env vars via [environment.py](testing_workflow_dashboard/environment.py), calls `testing_workflow_ollama_agentic.runner.run()` synchronously, then restores the prior env. New env knobs added to the agentic runner that should be UI-toggleable need wiring in both [config.py](testing_workflow_dashboard/config.py) and [app.py](testing_workflow_dashboard/app.py)'s `_render_sidebar`. Report views (summary, agent gallery, failure analysis, charts, raw JSON explorer) are in [views.py](testing_workflow_dashboard/views.py).

## Things to ignore

- `.github/copilot-instructions.md` is leftover VS Code scaffolding (todo checkboxes, not real instructions). Do not treat it as guidance.
- `testing_workflow/core/` only contains `__pycache__` — it's a stale empty subdir.
- `testing_workflow_ollama_agentic/settings.py` and `state.py` are one-line back-compat re-exports; edit `testing_workflow_core` directly.
