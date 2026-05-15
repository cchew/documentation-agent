"""Framework-neutral graph abstraction for the Doco Agent pipeline.

Defines a lightweight Graph class with nodes, directed edges, and conditional
edges. The HITL_PAUSE sentinel signals that execution should suspend pending
an async human interaction (e.g. a Slack button click). The graph can resume
from any named node via invoke(state, start_at=node_name).

The Cycle 1 graph topology (match → confirm_hitl → create|update|cancel) is
built by build_cycle1_graph() using no-op stub nodes so the topology is testable
without live Confluence/Slack dependencies.

Cycle 2 work: wire the actual execute_* and match() functions as node callables,
replacing the stubs, and run the pipeline through graph.invoke() instead of
calling functions directly.
"""
from __future__ import annotations

from typing import Any, Callable

END = "__end__"
HITL_PAUSE = "__hitl_pause__"


class Graph:
    def __init__(self) -> None:
        self._nodes: dict[str, Callable[[dict], dict | None]] = {}
        self._edges: dict[str, str] = {}
        self._conditional_edges: dict[str, tuple[Callable[[dict], str], dict[str, str]]] = {}
        self._entry: str | None = None

    def add_node(self, name: str, fn: Callable[[dict], dict | None]) -> None:
        self._nodes[name] = fn

    def set_entry_point(self, name: str) -> None:
        self._entry = name

    def add_edge(self, from_node: str, to_node: str) -> None:
        if from_node in self._edges or from_node in self._conditional_edges:
            raise ValueError(f"Edge already defined from '{from_node}'")
        self._edges[from_node] = to_node

    def add_conditional_edge(
        self,
        from_node: str,
        router: Callable[[dict], str],
        mapping: dict[str, str],
    ) -> None:
        if from_node in self._edges or from_node in self._conditional_edges:
            raise ValueError(f"Edge already defined from '{from_node}'")
        self._conditional_edges[from_node] = (router, mapping)

    def node_names(self) -> list[str]:
        return list(self._nodes.keys())

    def invoke(
        self,
        state: dict[str, Any],
        start_at: str | None = None,
    ) -> dict[str, Any]:
        """Run the graph from start_at (or entry point) until END or HITL_PAUSE.

        Returns the final state with '__current_node__' set to the terminal node.
        """
        current = start_at or self._entry
        if current is None:
            raise ValueError("No entry point set and no start_at provided")

        while current not in (END, HITL_PAUSE):
            fn = self._nodes.get(current)
            if fn is None:
                raise ValueError(f"No node registered for '{current}'")
            result = fn(state)
            if result is not None:
                state = result

            if current in self._conditional_edges:
                router, mapping = self._conditional_edges[current]
                route_key = router(state)
                current = mapping.get(route_key, END)
            elif current in self._edges:
                current = self._edges[current]
            else:
                current = END

        state["__current_node__"] = current
        return state


# ---------------------------------------------------------------------------
# Cycle 1 topology
# ---------------------------------------------------------------------------

def _noop(state: dict) -> dict:
    return state


def _confirm_hitl_router(state: dict) -> str:
    """Route past confirm_hitl: pause if candidates exist, else create immediately."""
    if state.get("has_candidates", False):
        return "pause"
    return "create"


def _action_router(state: dict) -> str:
    """Route after HITL resume: direction is set by the interaction handler.

    Cycle 2: wire as the router for a confirm_resume conditional edge.
    """
    return state.get("action", "cancel")


def build_cycle1_graph() -> Graph:
    """Build the Cycle 1 update-not-duplicate graph with stub node callables.

    Topology: match → confirm_hitl → HITL_PAUSE (if candidates)
                                   → create (if no candidates)

    On HITL resume (via /slack/interactions):
              confirm_resume → create | update | cancel → END
    """
    g = Graph()

    g.add_node("match", _noop)
    g.add_node("confirm_hitl", _noop)
    g.add_node("create", lambda s: {**s, "action": "create"})
    g.add_node("update", lambda s: {**s, "action": "update"})
    g.add_node("cancel", lambda s: {**s, "action": "cancel"})

    g.set_entry_point("match")
    g.add_edge("match", "confirm_hitl")

    g.add_conditional_edge(
        "confirm_hitl",
        _confirm_hitl_router,
        {"pause": HITL_PAUSE, "create": "create"},
    )

    g.add_edge("create", END)
    g.add_edge("update", END)
    g.add_edge("cancel", END)

    return g
