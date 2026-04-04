from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .execution import execute_suite
from .master_data import fetch_master_data
from .state import WorkflowState
from .suite_loader import load_suite
from .template import PLACEHOLDER_PATTERN

VALID_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
BUILTIN_CONTEXT_KEYS = {
    "run_timestamp",
    "user_index",
    "agent_id",
    "iteration_index",
    "run_email_suffix",
    "run_mobile",
    "peer_doctor_id",
    "peer_doctor_email",
    "peer_access_token",
}
GENERATED_CONTEXT_KEYS = {
    "doctor_first_name",
    "doctor_last_name",
    "doctor_fullname",
    "doctor_email_local",
    "registration_number",
    "years_of_experience",
    "date_of_birth",
    "gender",
    "medical_council_board",
    "short_bio",
    "identity_source",
    "identity_pool_index",
    "identity_error",
}
MASTER_DATA_CONTEXT_KEYS = {
    "company_id",
    "company_name",
    "specialization_id",
    "sub_specialization_id",
    "additional_specialization_id",
    "specialization_name",
    "specialization_source",
    "company_source",
}


def _find_placeholders(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, str):
        found.update(match.group(1) for match in PLACEHOLDER_PATTERN.finditer(value))
    elif isinstance(value, dict):
        for item in value.values():
            found.update(_find_placeholders(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_find_placeholders(item))
    return found


def _validate_run_config(suite: dict[str, Any], errors: list[str]) -> None:
    run_cfg = suite.get("run", {})
    if not isinstance(run_cfg, dict):
        errors.append("Top-level 'run' must be an object when present.")
        return

    for field in ("virtual_users", "iterations_per_user", "max_workers"):
        if field not in run_cfg:
            continue
        value = run_cfg[field]
        if not isinstance(value, int):
            errors.append(f"run.{field} must be an integer.")
        elif value < 1:
            errors.append(f"run.{field} must be >= 1.")

    virtual_users = run_cfg.get("virtual_users")
    max_workers = run_cfg.get("max_workers")
    if isinstance(virtual_users, int) and isinstance(max_workers, int) and max_workers > virtual_users:
        errors.append("run.max_workers cannot exceed run.virtual_users.")

    if "ramp_up_seconds" in run_cfg:
        ramp_up_seconds = run_cfg["ramp_up_seconds"]
        if not isinstance(ramp_up_seconds, (int, float)):
            errors.append("run.ramp_up_seconds must be numeric.")
        elif float(ramp_up_seconds) < 0:
            errors.append("run.ramp_up_seconds must be >= 0.")

    if "think_time_ms" in run_cfg:
        think_time_ms = run_cfg["think_time_ms"]
        if isinstance(think_time_ms, (int, float)):
            if float(think_time_ms) < 0:
                errors.append("run.think_time_ms must be >= 0.")
        elif isinstance(think_time_ms, list):
            if len(think_time_ms) != 2 or not all(isinstance(item, (int, float)) for item in think_time_ms):
                errors.append("run.think_time_ms list form must be [min_ms, max_ms] numeric values.")
            elif any(float(item) < 0 for item in think_time_ms):
                errors.append("run.think_time_ms list values must be >= 0.")
        else:
            errors.append("run.think_time_ms must be numeric or [min_ms, max_ms].")


def _validate_step_shape(
    wf_name: str,
    step: dict[str, Any],
    available_context: set[str],
    known_step_names: set[str],
    errors: list[str],
) -> None:
    step_name = step.get("name", "unnamed_step")

    if "name" not in step or not isinstance(step_name, str) or not step_name.strip():
        errors.append(f"Workflow '{wf_name}' has a step with a missing or empty 'name'.")

    method = step.get("method")
    if method is None:
        errors.append(f"Workflow '{wf_name}' step '{step_name}' missing 'method'.")
    elif not isinstance(method, str) or method.upper() not in VALID_METHODS:
        errors.append(f"Workflow '{wf_name}' step '{step_name}' has invalid method '{method}'.")

    url = step.get("url")
    if url is None:
        errors.append(f"Workflow '{wf_name}' step '{step_name}' missing 'url'.")
    elif not isinstance(url, str) or not url.strip():
        errors.append(f"Workflow '{wf_name}' step '{step_name}' has an invalid 'url'.")

    enabled = step.get("enabled", True)
    if not isinstance(enabled, bool):
        errors.append(f"Workflow '{wf_name}' step '{step_name}' has non-boolean 'enabled'.")

    dependency_name = step.get("depends_on")
    if dependency_name is not None:
        if not isinstance(dependency_name, str) or not dependency_name.strip():
            errors.append(f"Workflow '{wf_name}' step '{step_name}' has invalid 'depends_on'.")
        elif dependency_name == step_name:
            errors.append(f"Workflow '{wf_name}' step '{step_name}' cannot depend on itself.")
        elif dependency_name not in known_step_names:
            errors.append(
                f"Workflow '{wf_name}' step '{step_name}' depends on unknown step '{dependency_name}'."
            )

    if "json" in step and "data" in step:
        errors.append(f"Workflow '{wf_name}' step '{step_name}' cannot define both 'json' and 'data'.")
    if "json" in step and "files" in step:
        errors.append(f"Workflow '{wf_name}' step '{step_name}' cannot define both 'json' and 'files'. Use 'data' for multipart form fields.")

    files = step.get("files")
    if files is not None:
        if not isinstance(files, dict) or not files:
            errors.append(f"Workflow '{wf_name}' step '{step_name}' files must be a non-empty object.")
        elif "data" in step and not isinstance(step.get("data"), dict):
            errors.append(f"Workflow '{wf_name}' step '{step_name}' data must be an object when used with files.")
        else:
            for field_name, field_value in files.items():
                if not isinstance(field_name, str) or not field_name.strip():
                    errors.append(f"Workflow '{wf_name}' step '{step_name}' has an invalid files field name.")
                    continue
                valid_value = False
                if isinstance(field_value, str) and field_value.strip():
                    valid_value = True
                elif isinstance(field_value, dict):
                    path_value = field_value.get("path")
                    valid_value = isinstance(path_value, str) and bool(path_value.strip())
                elif isinstance(field_value, list) and field_value:
                    valid_value = all(
                        (isinstance(item, str) and item.strip())
                        or (
                            isinstance(item, dict)
                            and isinstance(item.get("path"), str)
                            and bool(str(item.get("path")).strip())
                        )
                        for item in field_value
                    )
                if not valid_value:
                    errors.append(
                        f"Workflow '{wf_name}' step '{step_name}' files.{field_name} must be a file path string, a path object, or a non-empty list of them."
                    )

    expected = step.get("expected")
    if expected is not None and not isinstance(expected, dict):
        errors.append(f"Workflow '{wf_name}' step '{step_name}' expected must be an object.")
    elif isinstance(expected, dict):
        if "status_code" in expected and not isinstance(expected["status_code"], int):
            errors.append(f"Workflow '{wf_name}' step '{step_name}' expected.status_code must be an integer.")
        if "max_response_time_ms" in expected and not isinstance(expected["max_response_time_ms"], (int, float)):
            errors.append(
                f"Workflow '{wf_name}' step '{step_name}' expected.max_response_time_ms must be numeric."
            )
        if "json_path_equals" in expected and not isinstance(expected["json_path_equals"], dict):
            errors.append(
                f"Workflow '{wf_name}' step '{step_name}' expected.json_path_equals must be an object."
            )

    save_fields = step.get("save")
    if save_fields is not None and not isinstance(save_fields, dict):
        errors.append(f"Workflow '{wf_name}' step '{step_name}' save must be an object.")
    elif isinstance(save_fields, dict):
        for var_name, path_spec in save_fields.items():
            if not isinstance(var_name, str) or not var_name.strip():
                errors.append(f"Workflow '{wf_name}' step '{step_name}' has invalid save key '{var_name}'.")
            if isinstance(path_spec, list):
                if not path_spec or not all(isinstance(item, str) and item.strip() for item in path_spec):
                    errors.append(
                        f"Workflow '{wf_name}' step '{step_name}' save path list for '{var_name}' must contain non-empty strings."
                    )
            elif not isinstance(path_spec, str) or not path_spec.strip():
                errors.append(
                    f"Workflow '{wf_name}' step '{step_name}' save path for '{var_name}' must be a non-empty string or string list."
                )

    for placeholder in sorted(_find_placeholders(step)):
        if placeholder not in available_context:
            errors.append(
                f"Workflow '{wf_name}' step '{step_name}' references unknown placeholder '{placeholder}'."
            )


def _validate_workflows(suite: dict[str, Any], errors: list[str]) -> list[str]:
    checks: list[str] = []
    context = suite.get("context", {})
    if context is not None and not isinstance(context, dict):
        errors.append("Top-level 'context' must be an object when present.")
        context = {}

    workflows = suite.get("workflows", [])
    if not isinstance(workflows, list) or not workflows:
        errors.append("Top-level 'workflows' must be a non-empty list.")
        return checks

    base_context = set(context.keys()) | BUILTIN_CONTEXT_KEYS | GENERATED_CONTEXT_KEYS | MASTER_DATA_CONTEXT_KEYS
    all_step_names: list[str] = []
    for wf in workflows:
        steps = wf.get("steps", [])
        if isinstance(steps, list):
            for step in steps:
                raw_name = step.get("name")
                if isinstance(raw_name, str):
                    all_step_names.append(raw_name)

    available_context = set(base_context)
    known_step_names = set(all_step_names)
    for wf in workflows:
        wf_name = wf.get("name", "unnamed_workflow")
        if "name" not in wf or not isinstance(wf_name, str) or not wf_name.strip():
            errors.append("Each workflow must have a non-empty 'name'.")

        steps = wf.get("steps", [])
        if not isinstance(steps, list) or not steps:
            errors.append(f"Workflow '{wf_name}' has no steps.")
            continue

        step_names: list[str] = []
        for step in steps:
            raw_name = step.get("name")
            if isinstance(raw_name, str):
                step_names.append(raw_name)

        duplicate_names: set[str] = set()
        seen_names: set[str] = set()
        for name in step_names:
            if name in seen_names:
                duplicate_names.add(name)
            seen_names.add(name)
        for duplicate_name in sorted(duplicate_names):
            errors.append(f"Workflow '{wf_name}' has duplicate step name '{duplicate_name}'.")

        for step in steps:
            step_name = step.get("name", "unnamed_step")
            _validate_step_shape(wf_name, step, available_context, known_step_names, errors)
            checks.append(f"{wf_name}::{step_name}")

            save_fields = step.get("save", {})
            if isinstance(save_fields, dict):
                available_context.update(str(var_name) for var_name in save_fields.keys())

    return checks


def load_suite_node(state: WorkflowState) -> dict[str, Any]:
    suite = load_suite(Path(state["tests_file"]))
    run_id = str(int(time.time()))
    return {"suite": suite, "run_id": run_id}


def contract_validate_node(state: WorkflowState) -> dict[str, Any]:
    errors: list[str] = list(state.get("errors", []))
    suite = state["suite"]
    _validate_run_config(suite, errors)
    checks = _validate_workflows(suite, errors)
    return {"contract_checks": checks, "errors": errors}


def execute_sample_workflow_node(state: WorkflowState) -> dict[str, Any]:
    if state.get("errors"):
        return {
            "results": [],
            "agent_summaries": [],
            "errors": list(state.get("errors", [])),
        }
    results, agent_summaries, execution_errors = execute_suite(
        suite=state["suite"],
        default_timeout_seconds=state["default_timeout_seconds"],
        run_timestamp=int(state["run_id"]),
        prefetched_context=state.get("prefetched_context", {}),
    )
    return {
        "results": results,
        "agent_summaries": agent_summaries,
        "errors": list(state.get("errors", [])) + execution_errors,
    }


def prefetch_master_data_node(state: WorkflowState) -> dict[str, Any]:
    if state.get("errors"):
        return {
            "prefetched_context": {},
            "master_api_checks": [],
        }
    context = dict(state["suite"].get("context", {}))
    prefetched = fetch_master_data(context)
    checks = list(prefetched.get("master_api_checks", []))
    merged_prefetched = dict(prefetched)
    merged_prefetched.pop("master_api_checks", None)
    return {
        "prefetched_context": merged_prefetched,
        "master_api_checks": checks,
    }


def _build_step_breakdown(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_step: dict[str, dict[str, Any]] = {}
    for item in results:
        step_name = str(item.get("step", "unnamed_step"))
        bucket = by_step.setdefault(
            step_name,
            {"step": step_name, "passed": 0, "failed": 0, "skipped": 0},
        )
        if item.get("skipped") is True:
            bucket["skipped"] += 1
        elif item.get("passed") is True:
            bucket["passed"] += 1
        else:
            bucket["failed"] += 1
    return [by_step[name] for name in sorted(by_step)]


def _build_failure_summary(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for item in results:
        if item.get("passed") is True and item.get("skipped") is not True:
            continue

        step_name = str(item.get("step", "unnamed_step"))
        if item.get("skipped") is True:
            reason = str(item.get("skip_reason") or "Skipped")
            category = "skipped"
        else:
            errors = item.get("errors", [])
            reason = str(errors[0]) if errors else "Unknown failure"
            category = "failed"

        key = (step_name, reason)
        bucket = grouped.setdefault(
            key,
            {
                "step": step_name,
                "category": category,
                "reason": reason,
                "count": 0,
                "user_indexes": [],
            },
        )
        bucket["count"] += 1
        user_index = item.get("user_index")
        if isinstance(user_index, int) and user_index not in bucket["user_indexes"]:
            bucket["user_indexes"].append(user_index)

    summary = list(grouped.values())
    summary.sort(key=lambda item: (-int(item["count"]), item["category"], item["step"], item["reason"]))
    return summary


def _build_duplicate_doctor_id_summary(agent_summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_doctor_id: dict[str, list[dict[str, Any]]] = {}
    for agent in agent_summaries:
        doctor_id = agent.get("doctor_id")
        if not isinstance(doctor_id, str) or not doctor_id.strip():
            continue
        by_doctor_id.setdefault(doctor_id, []).append(agent)

    duplicates: list[dict[str, Any]] = []
    for doctor_id, agents in sorted(by_doctor_id.items()):
        if len(agents) < 2:
            continue
        duplicates.append(
            {
                "doctor_id": doctor_id,
                "count": len(agents),
                "user_indexes": sorted(int(agent.get("user_index", 0)) for agent in agents),
                "agent_ids": [str(agent.get("agent_id")) for agent in agents],
                "doctor_emails": [str(agent.get("doctor_email")) for agent in agents],
            }
        )
    return duplicates


def finalize_report_node(state: WorkflowState) -> dict[str, Any]:
    results = state.get("results", [])
    agent_summaries = state.get("agent_summaries", [])
    run_cfg = state.get("suite", {}).get("run", {})
    skipped = sum(1 for item in results if item.get("skipped") is True)
    passed = sum(1 for item in results if item.get("passed") is True and item.get("skipped") is not True)
    failed = len(results) - passed - skipped
    step_breakdown = _build_step_breakdown(results)
    failure_summary = _build_failure_summary(results)
    duplicate_doctor_ids = _build_duplicate_doctor_id_summary(agent_summaries)
    report = {
        "run_id": state["run_id"],
        "summary": {
            "total_steps": len(results),
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "virtual_users": int(run_cfg.get("virtual_users", 1)),
            "iterations_per_user": int(run_cfg.get("iterations_per_user", 1)),
            "max_workers": int(run_cfg.get("max_workers", min(int(run_cfg.get("virtual_users", 1)), 100))),
            "contract_checks": len(state.get("contract_checks", [])),
            "errors": len(state.get("errors", [])),
            "unique_agents": len(agent_summaries),
            "step_breakdown": step_breakdown,
            "failure_summary": failure_summary,
            "duplicate_doctor_ids": duplicate_doctor_ids,
        },
        "agents": agent_summaries,
        "prefetched_context": state.get("prefetched_context", {}),
        "master_api_checks": state.get("master_api_checks", []),
        "errors": state.get("errors", []),
        "results": results,
    }

    report_path = Path(state["report_file"])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n=== LangGraph Testing Workflow Run ===")
    print(f"Run ID: {state['run_id']}")
    print(f"Total steps: {len(results)}")
    print(f"Passed: {passed} | Failed: {failed} | Skipped: {skipped}")
    print(
        "Agents: "
        f"{report['summary']['virtual_users']} | "
        f"Iterations/User: {report['summary']['iterations_per_user']} | "
        f"Workers: {report['summary']['max_workers']}"
    )
    print(f"Contract checks: {len(state.get('contract_checks', []))}")
    print(f"Errors: {len(state.get('errors', []))}")
    print(f"Report: {report_path}")

    return {}
