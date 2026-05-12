from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .state import WorkflowState


def build_standard_graph(nodes_module) -> object:
    graph = StateGraph(WorkflowState)
    graph.add_node("load_suite", nodes_module.load_suite_node)
    graph.add_node("contract_validate", nodes_module.contract_validate_node)
    graph.add_node("prefetch_master_data", nodes_module.prefetch_master_data_node)
    graph.add_node("execute_sample_workflow", nodes_module.execute_sample_workflow_node)
    graph.add_node("finalize_report", nodes_module.finalize_report_node)

    graph.add_edge(START, "load_suite")
    graph.add_edge("load_suite", "contract_validate")
    graph.add_edge("contract_validate", "prefetch_master_data")
    graph.add_edge("prefetch_master_data", "execute_sample_workflow")
    graph.add_edge("execute_sample_workflow", "finalize_report")
    graph.add_edge("finalize_report", END)

    return graph.compile()
