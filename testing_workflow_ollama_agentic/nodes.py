from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from testing_workflow_core.master_data import fetch_master_data
from testing_workflow_core.suite_loader import load_suite

from .reports import build_agentic_report, report_status, write_agentic_report, write_bootstrap_report
from .runtime import apply_run_overrides, log_agentic
from .session import execute_agentic_sessions
from testing_workflow_core.state import AgenticWorkflowState


def load_suite_node(state: AgenticWorkflowState) -> dict[str, Any]:
    try:
        suite = apply_run_overrides(load_suite(Path(state["tests_file"])))
        run_id = str(int(time.time()))
        log_agentic(f"[agentic] loaded suite from {state['tests_file']} with run_id={run_id}")
        write_bootstrap_report(
            report_file=state["report_file"],
            run_id=run_id,
            status="bootstrapping",
            suite=suite,
            errors=list(state.get("errors", [])),
        )
        return {"suite": suite, "run_id": run_id}
    except Exception as err:
        return {"errors": state.get("errors", []) + [f"Failed to load suite: {err}"]}


def prefetch_master_data_node(state: AgenticWorkflowState) -> dict[str, Any]:
    if state.get("errors"):
        return {
            "prefetched_context": {},
            "master_api_checks": [],
        }
    log_agentic("[agentic] starting master-data prefetch")
    try:
        context = dict(state["suite"].get("context", {}))
        prefetched = fetch_master_data(context)
        checks = list(prefetched.get("master_api_checks", []))
        merged_prefetched = dict(prefetched)
        merged_prefetched.pop("master_api_checks", None)

        write_bootstrap_report(
            report_file=state["report_file"],
            run_id=state["run_id"],
            status="prefetch_completed",
            suite=state["suite"],
            errors=list(state.get("errors", [])),
            prefetched_context=merged_prefetched,
            master_api_checks=checks,
        )
        return {
            "prefetched_context": merged_prefetched,
            "master_api_checks": checks,
        }
    except Exception as err:
        error_message = f"Master data prefetch failed: {err}"
        log_agentic(f"[agentic] {error_message}")
        write_bootstrap_report(
            report_file=state["report_file"],
            run_id=state["run_id"],
            status="prefetch_failed",
            suite=state["suite"],
            errors=list(state.get("errors", [])) + [error_message],
        )
        return {
            "prefetched_context": {},
            "master_api_checks": [],
            "errors": list(state.get("errors", [])) + [error_message],
        }


def execute_agentic_sessions_node(state: AgenticWorkflowState) -> dict[str, Any]:
    if state.get("errors"):
        return {
            "results": [],
            "agent_summaries": [],
            "errors": list(state.get("errors", [])),
        }

    log_agentic("[agentic] starting doctor-agent sessions")
    results, agent_summaries, execution_errors = execute_agentic_sessions(
        suite=state["suite"],
        default_timeout_seconds=state["default_timeout_seconds"],
        run_timestamp=int(state["run_id"]),
        prefetched_context=state.get("prefetched_context", {}),
        report_file=state["report_file"],
    )
    log_agentic("[agentic] doctor-agent sessions finished")
    return {
        "results": results,
        "agent_summaries": agent_summaries,
        "errors": list(state.get("errors", [])) + execution_errors,
    }


def finalize_report_node(state: AgenticWorkflowState) -> dict[str, Any]:
    results = state.get("results", [])
    agent_summaries = state.get("agent_summaries", [])
    passed = sum(1 for item in results if item.get("passed") is True and item.get("skipped") is not True)
    skipped = sum(1 for item in results if item.get("skipped") is True)
    failed = len(results) - passed - skipped
    errors = list(state.get("errors", []))
    status = report_status(failed=failed, errors=len(errors))
    report = build_agentic_report(
        run_id=state["run_id"],
        status=status,
        results=results,
        agent_summaries=agent_summaries,
        errors=errors,
        suite=state.get("suite", {}),
        prefetched_context=state.get("prefetched_context", {}),
        master_api_checks=state.get("master_api_checks", []),
    )
    report_path = Path(state["report_file"])
    write_agentic_report(state["report_file"], report)

    print("\n=== Agentic Ollama Doctor Session Run ===")
    print(f"Run ID: {state['run_id']}")
    print(f"Total actions executed: {len(results)}")
    print(f"Passed: {passed} | Failed: {failed}")
    print(f"Agents: {len(agent_summaries)}")
    print(f"Status: {status}")
    print(f"Errors: {len(errors)}")
    print(f"Report: {report_path}")

    return {}
