from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def report_status(*, failed: int, errors: int, in_progress: bool = False) -> str:
    if in_progress:
        return "running"
    if errors > 0:
        return "completed_with_errors"
    if failed > 0:
        return "completed_with_failures"
    return "completed"


def build_agentic_report(
    *,
    run_id: str,
    status: str,
    results: list[dict[str, Any]] | None = None,
    agent_summaries: list[dict[str, Any]] | None = None,
    errors: list[str] | None = None,
    suite: dict[str, Any] | None = None,
    prefetched_context: dict[str, Any] | None = None,
    master_api_checks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    report_results = results or []
    report_agents = agent_summaries or []
    report_errors = errors or []
    run_config = (suite or {}).get("run", {}) if isinstance(suite, dict) else {}
    passed = sum(1 for item in report_results if item.get("passed") is True and item.get("skipped") is not True)
    skipped = sum(1 for item in report_results if item.get("skipped") is True)
    failed = len(report_results) - passed - skipped
    virtual_users = int(run_config.get("virtual_users", len(report_agents) or 0) or 0)
    iterations_per_user = int(run_config.get("iterations_per_user", 1) or 1)
    max_workers = int(run_config.get("max_workers", virtual_users or len(report_agents) or 0) or 0)

    return {
        "run_id": run_id,
        "mode": "agentic_ollama",
        "status": status,
        "summary": {
            "total_steps": len(report_results),
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "virtual_users": virtual_users,
            "iterations_per_user": iterations_per_user,
            "max_workers": max_workers,
            "unique_agents": len(report_agents),
            "errors": len(report_errors),
        },
        "agents": report_agents,
        "prefetched_context": prefetched_context or {},
        "master_api_checks": master_api_checks or [],
        "errors": report_errors,
        "results": report_results,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def write_agentic_report(report_file: str | None, payload: dict[str, Any]) -> None:
    if not report_file:
        return
    report_path = Path(report_file)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_bootstrap_report(
    *,
    report_file: str,
    run_id: str,
    status: str,
    suite: dict[str, Any] | None = None,
    errors: list[str] | None = None,
    prefetched_context: dict[str, Any] | None = None,
    master_api_checks: list[dict[str, Any]] | None = None,
) -> None:
    payload = build_agentic_report(
        run_id=run_id,
        status=status,
        suite=suite,
        errors=errors,
        prefetched_context=prefetched_context,
        master_api_checks=master_api_checks,
    )
    write_agentic_report(report_file, payload)
