from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .nodes import (
    execute_agentic_sessions_node,
    finalize_report_node,
    load_suite_node,
    prefetch_master_data_node,
)
from testing_workflow_core.state import AgenticWorkflowState


def build_graph():
    graph = StateGraph(AgenticWorkflowState)
    graph.add_node("load_suite", load_suite_node)
    graph.add_node("prefetch_master_data", prefetch_master_data_node)
    graph.add_node("execute_agentic_sessions", execute_agentic_sessions_node)
    graph.add_node("finalize_report", finalize_report_node)

    graph.add_edge(START, "load_suite")
    graph.add_edge("load_suite", "prefetch_master_data")
    graph.add_edge("prefetch_master_data", "execute_agentic_sessions")
    graph.add_edge("execute_agentic_sessions", "finalize_report")
    graph.add_edge("finalize_report", END)

    return graph.compile()
