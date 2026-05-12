from __future__ import annotations

from .graph import build_graph
from testing_workflow_core.runner_common import run_standard_workflow


def run() -> None:
    run_standard_workflow(build_graph)
