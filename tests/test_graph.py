"""Tests for the Graph class and the Cycle 1 topology."""
import pytest
from src.doco_agent_core.graph import END, HITL_PAUSE, Graph


def test_graph_single_node_runs_and_ends():
    g = Graph()
    g.add_node("greet", lambda state: {**state, "greeted": True})
    g.set_entry_point("greet")
    g.add_edge("greet", END)
    result = g.invoke({"greeted": False})
    assert result["greeted"] is True


def test_graph_multi_node_chain():
    g = Graph()
    g.add_node("a", lambda s: {**s, "a": True})
    g.add_node("b", lambda s: {**s, "b": True})
    g.set_entry_point("a")
    g.add_edge("a", "b")
    g.add_edge("b", END)
    result = g.invoke({})
    assert result["a"] is True
    assert result["b"] is True


def test_graph_conditional_edge_routes_correctly():
    g = Graph()
    g.add_node("decide", lambda s: s)
    g.add_node("left", lambda s: {**s, "path": "left"})
    g.add_node("right", lambda s: {**s, "path": "right"})
    g.set_entry_point("decide")
    g.add_conditional_edge(
        "decide",
        lambda s: "go_left" if s.get("choice") == "left" else "go_right",
        {"go_left": "left", "go_right": "right"},
    )
    g.add_edge("left", END)
    g.add_edge("right", END)

    assert g.invoke({"choice": "left"})["path"] == "left"
    assert g.invoke({"choice": "right"})["path"] == "right"


def test_graph_hitl_pause_stops_execution():
    g = Graph()
    g.add_node("match", lambda s: s)
    g.add_node("confirm_hitl", lambda s: {**s, "hitl_registered": True})
    g.add_node("create", lambda s: {**s, "created": True})
    g.set_entry_point("match")
    g.add_edge("match", "confirm_hitl")
    g.add_edge("confirm_hitl", HITL_PAUSE)
    g.add_edge(HITL_PAUSE, "create")

    result = g.invoke({})
    assert result["hitl_registered"] is True
    assert result.get("created") is None  # execution stopped at HITL_PAUSE
    assert result["__current_node__"] == HITL_PAUSE


def test_graph_resume_continues_from_node():
    g = Graph()
    g.add_node("create", lambda s: {**s, "created": True})
    g.add_node("log", lambda s: {**s, "logged": True})
    g.set_entry_point("create")
    g.add_edge("create", "log")
    g.add_edge("log", END)

    result = g.invoke({}, start_at="create")
    assert result["created"] is True
    assert result["logged"] is True


def test_cycle1_graph_topology_is_correct():
    from src.doco_agent_core.graph import build_cycle1_graph
    g = build_cycle1_graph()
    # Verify the graph can be described (nodes exist)
    assert "match" in g.node_names()
    assert "confirm_hitl" in g.node_names()
    assert "create" in g.node_names()
    assert "update" in g.node_names()
    assert "cancel" in g.node_names()


def test_cycle1_graph_routes_create_when_no_candidates():
    from src.doco_agent_core.graph import build_cycle1_graph
    g = build_cycle1_graph()
    state = {"has_candidates": False, "action": None}
    result = g.invoke(state, start_at="confirm_hitl")
    assert result["action"] == "create"


def test_cycle1_graph_pauses_at_hitl_when_candidates_found():
    from src.doco_agent_core.graph import build_cycle1_graph
    g = build_cycle1_graph()
    state = {"has_candidates": True}
    result = g.invoke(state, start_at="confirm_hitl")
    assert result["__current_node__"] == HITL_PAUSE
