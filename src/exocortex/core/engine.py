"""Graph execution engine — the center of the exocortex."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from exocortex.core.conditions import evaluate_condition
from exocortex.core.graph import EdgeType, Graph, NodeSpec, NodeType, RunBudget


class ResultStatus(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"
    BUDGET_EXCEEDED = "budget_exceeded"
    AWAITING_APPROVAL = "awaiting_approval"


class NodeResult:
    """Result of executing a single node."""

    __slots__ = ("node_id", "status", "output", "started_at", "completed_at")

    def __init__(
        self,
        node_id: str,
        status: ResultStatus,
        output: dict[str, Any],
        started_at: datetime,
        completed_at: datetime,
    ) -> None:
        self.node_id = node_id
        self.status = status
        self.output = output
        self.started_at = started_at
        self.completed_at = completed_at


class RunAccounting:
    """Tracks resource consumption during a run."""

    def __init__(self, budget: RunBudget, nodes_already: int = 0) -> None:
        self.budget = budget
        self.nodes_executed = nodes_already
        self.total_tokens = 0
        self.total_cost_usd = 0.0
        self.started_at = datetime.now(UTC)

    def check_budget(self) -> str | None:
        """Return error message if budget exceeded, None if OK."""
        if self.nodes_executed >= self.budget.max_nodes:
            return f"Node budget exceeded: {self.nodes_executed}/{self.budget.max_nodes}"
        if self.total_tokens >= self.budget.max_total_tokens:
            return f"Token budget exceeded: {self.total_tokens}/{self.budget.max_total_tokens}"
        if self.total_cost_usd >= self.budget.max_cost_usd:
            return (
                f"Cost budget exceeded: "
                f"${self.total_cost_usd:.2f}/${self.budget.max_cost_usd:.2f}"
            )
        elapsed = (datetime.now(UTC) - self.started_at).total_seconds()
        if elapsed >= self.budget.max_wall_seconds:
            return f"Wall time exceeded: {elapsed:.0f}s/{self.budget.max_wall_seconds:.0f}s"
        return None

    def record_node(self, tokens: int = 0, cost: float = 0.0) -> None:
        self.nodes_executed += 1
        self.total_tokens += tokens
        self.total_cost_usd += cost


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BUDGET_EXCEEDED = "budget_exceeded"
    AWAITING_APPROVAL = "awaiting_approval"


NodeHandler = Callable[[dict[str, Any]], dict[str, Any]]
HookHandler = Callable[[dict[str, Any], NodeSpec], dict[str, Any]]


class GraphEngine:
    """Executes a graph definition, managing state and transitions."""

    def __init__(self, graph: Graph) -> None:
        errors = graph.validate()
        if errors:
            raise ValueError(f"Invalid graph: {errors}")
        self.graph = graph
        self._handlers: dict[str, NodeHandler] = {}
        self._pre_hooks: list[HookHandler] = []
        self._post_hooks: list[HookHandler] = []

    def register_handler(self, handler_path: str, fn: NodeHandler) -> None:
        self._handlers[handler_path] = fn

    def add_pre_hook(self, hook: HookHandler) -> None:
        self._pre_hooks.append(hook)

    def add_post_hook(self, hook: HookHandler) -> None:
        self._post_hooks.append(hook)

    def run(self, initial_state: dict[str, Any] | None = None) -> RunResult:
        """Execute the graph synchronously."""
        run_id = str(uuid.uuid4())
        state = self.graph.state_schema.create_initial_state()
        if initial_state:
            state.update(initial_state)

        assert self.graph.entry is not None
        return self._execute_loop(
            run_id=run_id,
            state=state,
            history=[],
            start_node=self.graph.entry,
            traversal_counts={},
            nodes_already=0,
        )

    def resume(
        self,
        run_id: str,
        state: dict[str, Any],
        history: list[NodeResult],
        from_node: str,
        approved: bool = True,
        traversal_counts: dict[str, int] | None = None,
    ) -> RunResult:
        """Resume a paused run (e.g., after HITL approval)."""
        if not approved:
            return RunResult(
                run_id=run_id,
                status=RunStatus.FAILED,
                state=state,
                history=history,
                error=f"Approval rejected at node '{from_node}'",
                traversal_counts=traversal_counts or {},
            )

        counts = dict(traversal_counts) if traversal_counts else {}
        next_node = self._resolve_next(from_node, state, counts)

        if next_node is None:
            return RunResult(
                run_id=run_id,
                status=RunStatus.COMPLETED,
                state=state,
                history=history,
                traversal_counts=counts,
            )

        return self._execute_loop(
            run_id=run_id,
            state=state,
            history=history,
            start_node=next_node,
            traversal_counts=counts,
            nodes_already=len(history),
        )

    def _execute_loop(
        self,
        run_id: str,
        state: dict[str, Any],
        history: list[NodeResult],
        start_node: str,
        traversal_counts: dict[str, int],
        nodes_already: int,
    ) -> RunResult:
        """Core execution loop shared by run() and resume()."""
        accounting = RunAccounting(self.graph.run_budget, nodes_already)
        current: str | None = start_node

        while current is not None:
            node = self.graph.nodes[current]

            budget_err = accounting.check_budget()
            if budget_err:
                return RunResult(
                    run_id=run_id,
                    status=RunStatus.BUDGET_EXCEEDED,
                    state=state,
                    history=history,
                    error=budget_err,
                    traversal_counts=traversal_counts,
                )

            if node.node_type == NodeType.APPROVAL:
                return RunResult(
                    run_id=run_id,
                    status=RunStatus.AWAITING_APPROVAL,
                    state=state,
                    history=history,
                    paused_at_node=current,
                    traversal_counts=traversal_counts,
                )

            result = self._execute_node(node, state)
            history.append(result)
            accounting.record_node()

            if result.status == ResultStatus.FAILURE:
                return RunResult(
                    run_id=run_id,
                    status=RunStatus.FAILED,
                    state=state,
                    history=history,
                    error=f"Node '{current}' failed",
                    traversal_counts=traversal_counts,
                )

            self._apply_output(node, state, result.output)

            current = self._resolve_next(current, state, traversal_counts)

        return RunResult(
            run_id=run_id,
            status=RunStatus.COMPLETED,
            state=state,
            history=history,
            traversal_counts=traversal_counts,
        )

    @staticmethod
    def _apply_output(
        node: NodeSpec, state: dict[str, Any], output: dict[str, Any]
    ) -> None:
        """Apply handler output to state, respecting output_fields."""
        for key, value in output.items():
            if node.output_fields is None or key in node.output_fields:
                state[key] = value

    def _execute_node(
        self, node: NodeSpec, state: dict[str, Any]
    ) -> NodeResult:
        """Execute a single node with pre/post hooks."""
        started_at = datetime.now(UTC)

        hook_state = deepcopy(state)
        for hook in self._pre_hooks:
            try:
                hook_state = hook(hook_state, node)
            except Exception as e:
                return self._fail(node.id, f"Pre-hook failed: {e}", started_at)

        projected = self._project_input(node, hook_state)

        handler = self._handlers.get(node.handler)
        if handler is None:
            return self._fail(
                node.id, f"No handler registered for '{node.handler}'", started_at
            )

        try:
            output = handler(projected)
        except Exception as e:
            return self._fail(node.id, str(e), started_at)

        if not isinstance(output, Mapping):
            return self._fail(
                node.id,
                f"Handler must return dict, got {type(output).__name__}",
                started_at,
            )

        output = dict(output)
        completed_at = datetime.now(UTC)

        for hook in self._post_hooks:
            try:
                hook({**state, **output}, node)
            except Exception as e:
                return NodeResult(
                    node_id=node.id,
                    status=ResultStatus.FAILURE,
                    output={"error": f"Post-hook failed: {e}"},
                    started_at=started_at,
                    completed_at=completed_at,
                )

        return NodeResult(
            node_id=node.id,
            status=ResultStatus.SUCCESS,
            output=output,
            started_at=started_at,
            completed_at=completed_at,
        )

    @staticmethod
    def _project_input(
        node: NodeSpec, state: dict[str, Any]
    ) -> dict[str, Any]:
        if node.input_projection:
            return {k: state[k] for k in node.input_projection if k in state}
        return state

    @staticmethod
    def _fail(node_id: str, error: str, started_at: datetime) -> NodeResult:
        return NodeResult(
            node_id=node_id,
            status=ResultStatus.FAILURE,
            output={"error": error},
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )

    def _resolve_next(
        self,
        current: str,
        state: dict[str, Any],
        traversal_counts: dict[str, int],
    ) -> str | None:
        """Determine the next node based on outgoing edges and state."""
        edges = self.graph.outgoing_edges(current)
        if not edges:
            return None

        for edge in edges:
            edge_key = (edge.source, edge.target)

            if (
                edge.max_traversals is not None
                and traversal_counts.get(edge_key, 0) >= edge.max_traversals
            ):
                continue

            matched = False
            match edge.edge_type:
                case EdgeType.STATIC:
                    matched = True
                case EdgeType.CONDITIONAL:
                    if edge.condition and evaluate_condition(edge.condition, state):
                        matched = True
                case EdgeType.DYNAMIC:
                    matched = True

            if matched:
                traversal_counts[edge_key] = traversal_counts.get(edge_key, 0) + 1
                return edge.target

        return None


class RunResult:
    """Result of a graph execution."""

    __slots__ = (
        "run_id", "status", "state", "history",
        "error", "paused_at_node", "traversal_counts",
    )

    def __init__(
        self,
        run_id: str,
        status: RunStatus,
        state: dict[str, Any],
        history: list[NodeResult],
        error: str | None = None,
        paused_at_node: str | None = None,
        traversal_counts: dict[Any, int] | None = None,
    ) -> None:
        self.run_id = run_id
        self.status = status
        self.state = state
        self.history = history
        self.error = error
        self.paused_at_node = paused_at_node
        self.traversal_counts = traversal_counts or {}
