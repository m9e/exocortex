"""Tests for the graph execution engine."""

from typing import Any

from exocortex.core.engine import GraphEngine, ResultStatus, RunStatus
from exocortex.core.graph import (
    ConditionOp,
    ConditionSpec,
    EdgeType,
    Graph,
    NodeType,
    RunBudget,
)
from exocortex.core.state import FieldSpec, StateSchema


def _make_handler(output: dict[str, Any]):
    """Create a simple handler that returns fixed output."""
    def handler(state: dict[str, Any]) -> dict[str, Any]:
        return output
    return handler


def _make_transform_handler(transform):
    """Create a handler that transforms state."""
    def handler(state: dict[str, Any]) -> dict[str, Any]:
        return transform(state)
    return handler


class TestLinearExecution:
    def test_single_node(self):
        g = Graph(
            name="test",
            state_schema=StateSchema(fields={
                "result": FieldSpec(field_type="str", default=""),
            }),
        )
        g.add_node("a", handler="h.a")
        g.set_entry("a")
        g.set_terminal("a")

        engine = GraphEngine(g)
        engine.register_handler("h.a", _make_handler({"result": "done"}))

        run = engine.run()
        assert run.status == RunStatus.COMPLETED
        assert run.state["result"] == "done"
        assert len(run.history) == 1

    def test_two_nodes_linear(self):
        g = Graph(
            name="test",
            state_schema=StateSchema(fields={
                "step": FieldSpec(field_type="int", default=0),
            }),
        )
        g.add_node("a", handler="h.a")
        g.add_node("b", handler="h.b")
        g.add_edge("a", "b")
        g.set_entry("a")
        g.set_terminal("b")

        engine = GraphEngine(g)
        engine.register_handler("h.a", _make_handler({"step": 1}))
        engine.register_handler("h.b", _make_handler({"step": 2}))

        run = engine.run()
        assert run.status == RunStatus.COMPLETED
        assert run.state["step"] == 2
        assert len(run.history) == 2

    def test_three_node_pipeline(self):
        g = Graph(
            name="test",
            state_schema=StateSchema(fields={
                "value": FieldSpec(field_type="int", default=0),
            }),
        )
        g.add_node("a", handler="h.inc")
        g.add_node("b", handler="h.inc")
        g.add_node("c", handler="h.inc")
        g.add_edge("a", "b")
        g.add_edge("b", "c")
        g.set_entry("a")
        g.set_terminal("c")

        engine = GraphEngine(g)
        engine.register_handler(
            "h.inc",
            _make_transform_handler(lambda s: {"value": s.get("value", 0) + 1}),
        )

        run = engine.run()
        assert run.status == RunStatus.COMPLETED
        assert run.state["value"] == 3


class TestConditionalEdges:
    def test_condition_true_follows_edge(self):
        g = Graph(
            name="test",
            state_schema=StateSchema(fields={
                "score": FieldSpec(field_type="float", default=0.0),
                "result": FieldSpec(field_type="str", default=""),
            }),
        )
        g.add_node("check", handler="h.check")
        g.add_node("good", handler="h.good")
        g.add_edge("check", "good", EdgeType.CONDITIONAL,
                   condition=ConditionSpec(field="score", operator=ConditionOp.GTE, value=0.7))
        g.set_entry("check")
        g.set_terminal("good")

        engine = GraphEngine(g)
        engine.register_handler("h.check", _make_handler({"score": 0.9}))
        engine.register_handler("h.good", _make_handler({"result": "passed"}))

        run = engine.run()
        assert run.status == RunStatus.COMPLETED
        assert run.state["result"] == "passed"

    def test_condition_false_skips_edge(self):
        g = Graph(
            name="test",
            state_schema=StateSchema(fields={
                "score": FieldSpec(field_type="float", default=0.0),
                "result": FieldSpec(field_type="str", default="pending"),
            }),
        )
        g.add_node("check", handler="h.check")
        g.add_node("good", handler="h.good")
        g.add_edge("check", "good", EdgeType.CONDITIONAL,
                   condition=ConditionSpec(field="score", operator=ConditionOp.GTE, value=0.7))
        g.set_entry("check")
        g.set_terminal("check")  # check is also terminal (no path taken)
        g.set_terminal("good")

        engine = GraphEngine(g)
        engine.register_handler("h.check", _make_handler({"score": 0.3}))
        engine.register_handler("h.good", _make_handler({"result": "passed"}))

        run = engine.run()
        assert run.status == RunStatus.COMPLETED
        assert run.state["result"] == "pending"  # good was never reached
        assert len(run.history) == 1  # Only check ran


class TestCycleExecution:
    def test_cycle_with_limit(self):
        g = Graph(
            name="test",
            state_schema=StateSchema(fields={
                "count": FieldSpec(field_type="int", default=0),
            }),
        )
        g.add_node("inc", handler="h.inc")
        g.add_edge("inc", "inc", max_traversals=3)  # Self-loop, max 3
        g.set_entry("inc")
        g.set_terminal("inc")

        engine = GraphEngine(g)
        engine.register_handler(
            "h.inc",
            _make_transform_handler(lambda s: {"count": s.get("count", 0) + 1}),
        )

        run = engine.run()
        assert run.status == RunStatus.COMPLETED
        # Entry executes once, then 3 more traversals of the self-loop
        assert run.state["count"] == 4
        assert len(run.history) == 4

    def test_cycle_between_two_nodes(self):
        g = Graph(
            name="test",
            state_schema=StateSchema(fields={
                "count": FieldSpec(field_type="int", default=0),
                "done": FieldSpec(field_type="bool", default=False),
            }),
        )
        g.add_node("work", handler="h.work")
        g.add_node("check", handler="h.check")
        g.add_edge("work", "check")
        g.add_edge("check", "work", EdgeType.CONDITIONAL,
                   condition=ConditionSpec(field="done", operator=ConditionOp.IS_FALSE),
                   max_traversals=5)
        g.set_entry("work")
        g.set_terminal("check")

        call_count = 0

        def work_handler(state):
            nonlocal call_count
            call_count += 1
            return {"count": call_count}

        def check_handler(state):
            return {"done": state.get("count", 0) >= 3}

        engine = GraphEngine(g)
        engine.register_handler("h.work", work_handler)
        engine.register_handler("h.check", check_handler)

        run = engine.run()
        assert run.status == RunStatus.COMPLETED
        assert run.state["done"] is True
        assert run.state["count"] == 3


class TestBudgetEnforcement:
    def test_node_budget_exceeded(self):
        g = Graph(
            name="test",
            state_schema=StateSchema(fields={
                "count": FieldSpec(field_type="int", default=0),
            }),
            run_budget=RunBudget(max_nodes=2),
        )
        g.add_node("inc", handler="h.inc")
        g.add_edge("inc", "inc", max_traversals=100)
        g.set_entry("inc")
        g.set_terminal("inc")

        engine = GraphEngine(g)
        engine.register_handler(
            "h.inc",
            _make_transform_handler(lambda s: {"count": s.get("count", 0) + 1}),
        )

        run = engine.run()
        assert run.status == RunStatus.BUDGET_EXCEEDED
        assert "Node budget" in (run.error or "")


class TestHooks:
    def test_pre_hook_runs_before_node(self):
        g = Graph(name="test")
        g.add_node("a", handler="h.a")
        g.set_entry("a")
        g.set_terminal("a")

        hook_calls: list[str] = []

        def pre_hook(state, node):
            hook_calls.append(f"pre:{node.id}")
            return state

        engine = GraphEngine(g)
        engine.register_handler("h.a", _make_handler({}))
        engine.add_pre_hook(pre_hook)

        run = engine.run()
        assert run.status == RunStatus.COMPLETED
        assert hook_calls == ["pre:a"]

    def test_post_hook_runs_after_node(self):
        g = Graph(name="test")
        g.add_node("a", handler="h.a")
        g.set_entry("a")
        g.set_terminal("a")

        hook_calls: list[str] = []

        def post_hook(state, node):
            hook_calls.append(f"post:{node.id}")
            return state

        engine = GraphEngine(g)
        engine.register_handler("h.a", _make_handler({}))
        engine.add_post_hook(post_hook)

        run = engine.run()
        assert run.status == RunStatus.COMPLETED
        assert hook_calls == ["post:a"]

    def test_pre_hook_failure_aborts_node(self):
        g = Graph(name="test")
        g.add_node("a", handler="h.a")
        g.set_entry("a")
        g.set_terminal("a")

        def failing_hook(state, node):
            raise RuntimeError("Security check failed")

        engine = GraphEngine(g)
        engine.register_handler("h.a", _make_handler({}))
        engine.add_pre_hook(failing_hook)

        run = engine.run()
        assert run.status == RunStatus.FAILED
        assert run.history[0].status == ResultStatus.FAILURE
        assert "Pre-hook failed" in run.history[0].output["error"]

    def test_multiple_hooks_run_in_order(self):
        g = Graph(name="test")
        g.add_node("a", handler="h.a")
        g.set_entry("a")
        g.set_terminal("a")

        calls: list[str] = []

        engine = GraphEngine(g)
        engine.register_handler("h.a", _make_handler({}))
        engine.add_pre_hook(lambda s, n: (calls.append("pre1"), s)[1])
        engine.add_pre_hook(lambda s, n: (calls.append("pre2"), s)[1])
        engine.add_post_hook(lambda s, n: (calls.append("post1"), s)[1])
        engine.add_post_hook(lambda s, n: (calls.append("post2"), s)[1])

        engine.run()
        assert calls == ["pre1", "pre2", "post1", "post2"]


class TestApprovalNode:
    def test_approval_pauses_execution(self):
        g = Graph(
            name="test",
            state_schema=StateSchema(fields={
                "data": FieldSpec(field_type="str", default=""),
            }),
        )
        g.add_node("prepare", handler="h.prepare")
        g.add_node("approve", handler="h.noop", node_type=NodeType.APPROVAL)
        g.add_node("execute", handler="h.execute")
        g.add_edge("prepare", "approve")
        g.add_edge("approve", "execute")
        g.set_entry("prepare")
        g.set_terminal("execute")

        engine = GraphEngine(g)
        engine.register_handler("h.prepare", _make_handler({"data": "ready"}))
        engine.register_handler("h.noop", _make_handler({}))
        engine.register_handler("h.execute", _make_handler({"data": "done"}))

        run = engine.run()
        assert run.status == RunStatus.AWAITING_APPROVAL
        assert run.paused_at_node == "approve"
        assert run.state["data"] == "ready"

    def test_resume_after_approval(self):
        g = Graph(
            name="test",
            state_schema=StateSchema(fields={
                "data": FieldSpec(field_type="str", default=""),
            }),
        )
        g.add_node("prepare", handler="h.prepare")
        g.add_node("approve", handler="h.noop", node_type=NodeType.APPROVAL)
        g.add_node("execute", handler="h.execute")
        g.add_edge("prepare", "approve")
        g.add_edge("approve", "execute")
        g.set_entry("prepare")
        g.set_terminal("execute")

        engine = GraphEngine(g)
        engine.register_handler("h.prepare", _make_handler({"data": "ready"}))
        engine.register_handler("h.noop", _make_handler({}))
        engine.register_handler("h.execute", _make_handler({"data": "done"}))

        # First run pauses at approval
        run = engine.run()
        assert run.status == RunStatus.AWAITING_APPROVAL

        # Resume with approval
        resumed = engine.resume(
            run_id=run.run_id,
            state=run.state,
            history=run.history,
            from_node="approve",
            approved=True,
        )
        assert resumed.status == RunStatus.COMPLETED
        assert resumed.state["data"] == "done"

    def test_resume_with_rejection(self):
        g = Graph(name="test")
        g.add_node("approve", handler="h.noop", node_type=NodeType.APPROVAL)
        g.set_entry("approve")
        g.set_terminal("approve")

        engine = GraphEngine(g)
        engine.register_handler("h.noop", _make_handler({}))

        run = engine.run()
        resumed = engine.resume(
            run_id=run.run_id,
            state=run.state,
            history=run.history,
            from_node="approve",
            approved=False,
        )
        assert resumed.status == RunStatus.FAILED
        assert "rejected" in (resumed.error or "").lower()


class TestStateProjection:
    def test_input_projection_filters_state(self):
        g = Graph(
            name="test",
            state_schema=StateSchema(fields={
                "query": FieldSpec(field_type="str", default=""),
                "secret": FieldSpec(field_type="str", default="hidden"),
            }),
        )
        g.add_node("a", handler="h.a",
                   input_projection=["query"])  # Can't see 'secret'
        g.set_entry("a")
        g.set_terminal("a")

        received_state = {}

        def capture_handler(state):
            received_state.update(state)
            return {}

        engine = GraphEngine(g)
        engine.register_handler("h.a", capture_handler)

        engine.run({"query": "hello", "secret": "password123"})
        assert "query" in received_state
        assert "secret" not in received_state

    def test_output_fields_restricts_writes(self):
        g = Graph(
            name="test",
            state_schema=StateSchema(fields={
                "allowed": FieldSpec(field_type="str", default=""),
                "forbidden": FieldSpec(field_type="str", default="safe"),
            }),
        )
        g.add_node("a", handler="h.a", output_fields=["allowed"])
        g.set_entry("a")
        g.set_terminal("a")

        engine = GraphEngine(g)
        engine.register_handler(
            "h.a",
            _make_handler({"allowed": "written", "forbidden": "hacked"}),
        )

        run = engine.run()
        assert run.state["allowed"] == "written"
        assert run.state["forbidden"] == "safe"  # Not overwritten


class TestErrorHandling:
    def test_missing_handler_fails_gracefully(self):
        g = Graph(name="test")
        g.add_node("a", handler="h.nonexistent")
        g.set_entry("a")
        g.set_terminal("a")

        engine = GraphEngine(g)
        run = engine.run()
        assert run.status == RunStatus.FAILED
        assert "No handler" in (run.history[0].output.get("error", ""))

    def test_handler_exception_fails_gracefully(self):
        g = Graph(name="test")
        g.add_node("a", handler="h.boom")
        g.set_entry("a")
        g.set_terminal("a")

        def boom(state):
            raise ValueError("Something went wrong")

        engine = GraphEngine(g)
        engine.register_handler("h.boom", boom)

        run = engine.run()
        assert run.status == RunStatus.FAILED
        assert "Something went wrong" in run.history[0].output["error"]

    def test_initial_state_override(self):
        g = Graph(
            name="test",
            state_schema=StateSchema(fields={
                "x": FieldSpec(field_type="int", default=0),
            }),
        )
        g.add_node("a", handler="h.a")
        g.set_entry("a")
        g.set_terminal("a")

        engine = GraphEngine(g)
        engine.register_handler("h.a", _make_handler({}))

        run = engine.run({"x": 42})
        assert run.state["x"] == 42
