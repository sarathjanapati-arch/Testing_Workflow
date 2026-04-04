from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .nodes import (
    contract_validate_node,
    execute_sample_workflow_node,
    finalize_report_node,
    load_suite_node,
    prefetch_master_data_node,
)
from .state import WorkflowState


def build_graph():
    graph = StateGraph(WorkflowState)
    graph.add_node("load_suite", load_suite_node)
    graph.add_node("contract_validate", contract_validate_node)
    graph.add_node("prefetch_master_data", prefetch_master_data_node)
    graph.add_node("execute_sample_workflow", execute_sample_workflow_node)
    graph.add_node("finalize_report", finalize_report_node)

    graph.add_edge(START, "load_suite")
    graph.add_edge("load_suite", "contract_validate")
    graph.add_edge("contract_validate", "prefetch_master_data")
    graph.add_edge("prefetch_master_data", "execute_sample_workflow")
    graph.add_edge("execute_sample_workflow", "finalize_report")
    graph.add_edge("finalize_report", END)

    return graph.compile()
