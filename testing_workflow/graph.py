from __future__ import annotations

from . import nodes
from testing_workflow_core.graph_common import build_standard_graph


def build_graph():
    return build_standard_graph(nodes)
