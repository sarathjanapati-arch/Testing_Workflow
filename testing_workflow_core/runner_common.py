from __future__ import annotations

from .settings import load_settings
from .state import WorkflowState


def run_standard_workflow(build_graph_fn) -> None:
    settings = load_settings()
    app = build_graph_fn()

    initial_state: WorkflowState = {
        "tests_file": str(settings.tests_file),
        "report_file": str(settings.report_file),
        "default_timeout_seconds": settings.default_timeout_seconds,
        "suite": {},
        "run_id": "",
        "contract_checks": [],
        "prefetched_context": {},
        "master_api_checks": [],
        "results": [],
        "agent_summaries": [],
        "errors": [],
    }

    app.invoke(initial_state)
