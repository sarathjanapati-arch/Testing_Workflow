from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .execution import execute_suite
from .master_data import fetch_master_data
from .suite_loader import load_suite
from .validation import GENERATED_CONTEXT_KEYS, validate_run_config, validate_workflows


def load_suite_node(state: dict[str, Any]) -> dict[str, Any]:
    try:
        suite = load_suite(Path(state["tests_file"]))
        run_id = str(int(time.time()))
        return {"suite": suite, "run_id": run_id}
    except Exception as err:
        return {"errors": state.get("errors", []) + [f"Failed to load suite: {err}"]}


def contract_validate_node(state: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = list(state.get("errors", []))
    suite = state.get("suite")
    if not suite:
        return {"errors": errors}
    try:
        validate_run_config(suite, errors)
        checks = validate_workflows(suite, errors, GENERATED_CONTEXT_KEYS)
        return {"contract_checks": checks, "errors": errors}
    except Exception as err:
        return {"errors": errors + [f"Contract validation error: {err}"]}


def execute_sample_workflow_node(state: dict[str, Any]) -> dict[str, Any]:
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


def prefetch_master_data_node(state: dict[str, Any]) -> dict[str, Any]:
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


def build_step_breakdown(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def build_failure_summary(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def build_duplicate_doctor_id_summary(agent_summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def finalize_report_node(state: dict[str, Any]) -> dict[str, Any]:
    results = state.get("results", [])
    agent_summaries = state.get("agent_summaries", [])
    run_cfg = state.get("suite", {}).get("run", {})
    skipped = sum(1 for item in results if item.get("skipped") is True)
    passed = sum(1 for item in results if item.get("passed") is True and item.get("skipped") is not True)
    failed = len(results) - passed - skipped
    step_breakdown = build_step_breakdown(results)
    failure_summary = build_failure_summary(results)
    duplicate_doctor_ids = build_duplicate_doctor_id_summary(agent_summaries)
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
