from __future__ import annotations

from typing import Any, TypedDict


class WorkflowState(TypedDict):
    tests_file: str
    report_file: str
    default_timeout_seconds: float
    suite: dict[str, Any]
    run_id: str
    contract_checks: list[str]
    prefetched_context: dict[str, Any]
    master_api_checks: list[dict[str, Any]]
    results: list[dict[str, Any]]
    agent_summaries: list[dict[str, Any]]
    errors: list[str]
