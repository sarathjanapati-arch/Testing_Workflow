from __future__ import annotations

from .graph import build_graph
from testing_workflow_core.settings import load_settings
from testing_workflow_core.state import AgenticWorkflowState


def run() -> None:
    settings = load_settings()
    app = build_graph()

    initial_state: AgenticWorkflowState = {
        "tests_file": str(settings.tests_file),
        "report_file": str(settings.report_file),
        "default_timeout_seconds": settings.default_timeout_seconds,
        "suite": {},
        "run_id": "",
        "prefetched_context": {},
        "master_api_checks": [],
        "results": [],
        "agent_summaries": [],
        "errors": [],
    }

    app.invoke(initial_state)
