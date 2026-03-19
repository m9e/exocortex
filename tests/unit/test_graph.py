"""Tests for graph definition and validation."""

import pytest

from exocortex.core.graph import (
    ConditionOp,
    ConditionSpec,
    EdgeType,
    Graph,
    GraphDefinitionError,
    RunBudget,
)
from exocortex.core.state import FieldSpec, ReducerType, StateSchema


def _simple_graph() -> Graph:
    """Create a minimal valid graph for testing."""
    g = Graph(name="test")
    g.add_node("a", handler="test.a")
    g.add_node("b", handler="test.b")
    g.add_edge("a", "b")
    g.set_entry("a")
    g.set_terminal("b")
    return g


class TestGraphBuilder:
    def test_add_node(self):
        g = Graph(name="test")
        g.add_node("x", handler="test.x", name="My Node")
        assert "x" in g.nodes
        assert g.nodes["x"].name == "My Node"

    def test_duplicate_node_raises(self):
        g = Graph(name="test")
        g.add_node("x", handler="test.x")
        with pytest.raises(GraphDefinitionError, match="Duplicate"):
            g.add_node("x", handler="test.x2")

    def test_add_edge(self):
        g = _simple_graph()
        assert len(g.edges) == 1
        assert g.edges[0].source == "a"
        assert g.edges[0].target == "b"

    def test_entry_and_terminal(self):
        g = _simple_graph()
        assert g.entry == "a"
        assert g.terminals == {"b"}

    def test_outgoing_edges(self):
        g = _simple_graph()
        out = g.outgoing_edges("a")
        assert len(out) == 1
        assert out[0].target == "b"

    def test_incoming_edges(self):
        g = _simple_graph()
        inc = g.incoming_edges("b")
        assert len(inc) == 1
        assert inc[0].source == "a"


class TestGraphValidation:
    def test_valid_graph(self):
        g = _simple_graph()
        errors = g.validate()
        assert errors == []

    def test_no_entry(self):
        g = Graph(name="test")
        g.add_node("a", handler="test.a")
        g.set_terminal("a")
        errors = g.validate()
        assert any("No entry node" in e for e in errors)

    def test_no_terminal(self):
        g = Graph(name="test")
        g.add_node("a", handler="test.a")
        g.set_entry("a")
        errors = g.validate()
        assert any("No terminal" in e for e in errors)

    def test_entry_not_found(self):
        g = Graph(name="test")
        g.add_node("a", handler="test.a")
        g.set_entry("missing")
        g.set_terminal("a")
        errors = g.validate()
        assert any("not found" in e for e in errors)

    def test_edge_source_not_found(self):
        g = Graph(name="test")
        g.add_node("b", handler="test.b")
        g.add_edge("missing", "b")
        g.set_entry("b")
        g.set_terminal("b")
        errors = g.validate()
        assert any("missing" in e for e in errors)

    def test_conditional_edge_without_condition(self):
        g = Graph(name="test")
        g.add_node("a", handler="test.a")
        g.add_node("b", handler="test.b")
        g.add_edge("a", "b", EdgeType.CONDITIONAL)  # No condition!
        g.set_entry("a")
        g.set_terminal("b")
        errors = g.validate()
        assert any("no condition" in e for e in errors)

    def test_conditional_edge_with_condition_valid(self):
        g = Graph(name="test")
        g.add_node("a", handler="test.a")
        g.add_node("b", handler="test.b")
        g.add_edge("a", "b", EdgeType.CONDITIONAL,
                   condition=ConditionSpec(field="done", operator=ConditionOp.IS_TRUE))
        g.set_entry("a")
        g.set_terminal("b")
        errors = g.validate()
        assert errors == []

    def test_unreachable_node(self):
        g = Graph(name="test")
        g.add_node("a", handler="test.a")
        g.add_node("b", handler="test.b")
        g.add_node("orphan", handler="test.orphan")
        g.add_edge("a", "b")
        g.set_entry("a")
        g.set_terminal("b")
        errors = g.validate()
        assert any("unreachable" in e for e in errors)


class TestCycleDetection:
    def test_cycle_without_max_traversals_errors(self):
        g = Graph(name="test")
        g.add_node("a", handler="test.a")
        g.add_node("b", handler="test.b")
        g.add_edge("a", "b")
        g.add_edge("b", "a")  # Back-edge, no max_traversals
        g.set_entry("a")
        g.set_terminal("b")
        errors = g.validate()
        assert any("max_traversals" in e for e in errors)

    def test_cycle_with_max_traversals_valid(self):
        g = Graph(name="test")
        g.add_node("a", handler="test.a")
        g.add_node("b", handler="test.b")
        g.add_edge("a", "b")
        g.add_edge("b", "a", max_traversals=5)  # Properly bounded
        g.set_entry("a")
        g.set_terminal("b")
        errors = g.validate()
        assert errors == []

    def test_self_loop_without_limit_errors(self):
        g = Graph(name="test")
        g.add_node("a", handler="test.a")
        g.add_edge("a", "a")  # Self-loop
        g.set_entry("a")
        g.set_terminal("a")
        errors = g.validate()
        assert any("max_traversals" in e for e in errors)


class TestGraphWithSchema:
    def test_graph_with_state_schema(self):
        schema = StateSchema(fields={
            "query": FieldSpec(field_type="str", default=""),
            "results": FieldSpec(field_type="list", default=[], reducer=ReducerType.APPEND),
        })
        g = Graph(name="test", state_schema=schema)
        assert g.state_schema.fields["query"].field_type == "str"

    def test_graph_with_budget(self):
        budget = RunBudget(max_nodes=10, max_total_tokens=50_000)
        g = Graph(name="test", run_budget=budget)
        assert g.run_budget.max_nodes == 10
