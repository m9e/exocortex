"""Graph execution engine — the center of the exocortex."""

from __future__ import annotations

import uuid
from collections.abc import Callable
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

    def __init__(self, budget: RunBudget) -> None:
        self.budget = budget
        self.nodes_executed = 0
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


# Handler type: takes state dict, returns updated state dict
NodeHandler = Callable[[dict[str, Any]], dict[str, Any]]
AsyncNodeHandler = Callable[[dict[str, Any]], Any]  # Coroutine

# Hook type: takes state dict and node spec, returns state dict (or raises to abort)
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

    def register_handler(self, handler_path: str, handler: NodeHandler) -> None:
        """Register a handler function for a handler path."""
        self._handlers[handler_path] = handler

    def add_pre_hook(self, hook: HookHandler) -> None:
        self._pre_hooks.append(hook)

    def add_post_hook(self, hook: HookHandler) -> None:
        self._post_hooks.append(hook)

    def run(self, initial_state: dict[str, Any] | None = None) -> RunResult:
        """Execute the graph synchronously. Returns final state and history."""
        run_id = str(uuid.uuid4())
        state = self.graph.state_schema.create_initial_state()
        if initial_state:
            state.update(initial_state)

        accounting = RunAccounting(self.graph.run_budget)
        history: list[NodeResult] = []
        traversal_counts: dict[str, int] = {}

        assert self.graph.entry is not None
        current_node_id: str | None = self.graph.entry

        while current_node_id is not None:
            node = self.graph.nodes[current_node_id]

            # Check budget
            budget_error = accounting.check_budget()
            if budget_error:
                return RunResult(
                    run_id=run_id,
                    status=RunStatus.BUDGET_EXCEEDED,
                    state=state,
                    history=history,
                    error=budget_error,
                )

            # Handle approval nodes
            if node.node_type == NodeType.APPROVAL:
                return RunResult(
                    run_id=run_id,
                    status=RunStatus.AWAITING_APPROVAL,
                    state=state,
                    history=history,
                    paused_at_node=current_node_id,
                )

            # Execute node
            result = self._execute_node(node, state)
            history.append(result)
            accounting.record_node()

            if result.status == ResultStatus.FAILURE:
                return RunResult(
                    run_id=run_id,
                    status=RunStatus.FAILED,
                    state=state,
                    history=history,
                    error=f"Node '{current_node_id}' failed",
                )

            # Apply output to state
            if result.output:
                for key, value in result.output.items():
                    if node.output_fields is None or key in node.output_fields:
                        state[key] = value

            # Find next node
            current_node_id = self._resolve_next_node(
                current_node_id, state, traversal_counts
            )

        return RunResult(
            run_id=run_id,
            status=RunStatus.COMPLETED,
            state=state,
            history=history,
        )

    def resume(
        self,
        run_id: str,
        state: dict[str, Any],
        history: list[NodeResult],
        from_node: str,
        approved: bool = True,
    ) -> RunResult:
        """Resume a paused run (e.g., after HITL approval)."""
        if not approved:
            return RunResult(
                run_id=run_id,
                status=RunStatus.FAILED,
                state=state,
                history=history,
                error=f"Approval rejected at node '{from_node}'",
            )

        # Find next node after the approval gate
        traversal_counts: dict[str, int] = {}
        next_node = self._resolve_next_node(from_node, state, traversal_counts)

        accounting = RunAccounting(self.graph.run_budget)
        accounting.nodes_executed = len(history)

        current_node_id = next_node
        while current_node_id is not None:
            node = self.graph.nodes[current_node_id]

            budget_error = accounting.check_budget()
            if budget_error:
                return RunResult(
                    run_id=run_id,
                    status=RunStatus.BUDGET_EXCEEDED,
                    state=state,
                    history=history,
                    error=budget_error,
                )

            if node.node_type == NodeType.APPROVAL:
                return RunResult(
                    run_id=run_id,
                    status=RunStatus.AWAITING_APPROVAL,
                    state=state,
                    history=history,
                    paused_at_node=current_node_id,
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
                    error=f"Node '{current_node_id}' failed",
                )

            if result.output:
                for key, value in result.output.items():
                    if node.output_fields is None or key in node.output_fields:
                        state[key] = value

            current_node_id = self._resolve_next_node(
                current_node_id, state, traversal_counts
            )

        return RunResult(
            run_id=run_id,
            status=RunStatus.COMPLETED,
            state=state,
            history=history,
        )

    def _execute_node(self, node: NodeSpec, state: dict[str, Any]) -> NodeResult:
        """Execute a single node with pre/post hooks."""
        started_at = datetime.now(UTC)

        # Run pre-hooks
        hook_state = deepcopy(state)
        for hook in self._pre_hooks:
            try:
                hook_state = hook(hook_state, node)
            except Exception as e:
                return NodeResult(
                    node_id=node.id,
                    status=ResultStatus.FAILURE,
                    output={"error": f"Pre-hook failed: {e}"},
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                )

        # Project state if input_projection is set
        if node.input_projection:
            projected = {k: hook_state[k] for k in node.input_projection if k in hook_state}
        else:
            projected = hook_state

        # Get handler
        handler = self._handlers.get(node.handler)
        if handler is None:
            return NodeResult(
                node_id=node.id,
                status=ResultStatus.FAILURE,
                output={"error": f"No handler registered for '{node.handler}'"},
                started_at=started_at,
                completed_at=datetime.now(UTC),
            )

        # Execute handler
        try:
            output = handler(projected)
        except Exception as e:
            return NodeResult(
                node_id=node.id,
                status=ResultStatus.FAILURE,
                output={"error": str(e)},
                started_at=started_at,
                completed_at=datetime.now(UTC),
            )

        completed_at = datetime.now(UTC)

        # Run post-hooks
        for hook in self._post_hooks:
            try:
                state_with_output = {**state, **output}
                hook(state_with_output, node)
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

    def _resolve_next_node(
        self,
        current: str,
        state: dict[str, Any],
        traversal_counts: dict[str, int],
    ) -> str | None:
        """Determine the next node based on outgoing edges and state."""
        edges = self.graph.outgoing_edges(current)

        # Terminal with no outgoing edges = done
        if not edges:
            return None

        # Try to follow an outgoing edge
        for edge in edges:
            edge_key = f"{edge.source}->{edge.target}"

            # Check cycle limits
            if edge.max_traversals is not None:
                count = traversal_counts.get(edge_key, 0)
                if count >= edge.max_traversals:
                    continue

            match edge.edge_type:
                case EdgeType.STATIC:
                    traversal_counts[edge_key] = traversal_counts.get(edge_key, 0) + 1
                    return edge.target
                case EdgeType.CONDITIONAL:
                    if edge.condition and evaluate_condition(edge.condition, state):
                        traversal_counts[edge_key] = traversal_counts.get(edge_key, 0) + 1
                        return edge.target
                case EdgeType.DYNAMIC:
                    traversal_counts[edge_key] = traversal_counts.get(edge_key, 0) + 1
                    return edge.target

        # No edge was followed — if this is a terminal, that's a clean stop
        # If not a terminal, we're stuck (no valid transitions)
        return None


class RunResult:
    """Result of a graph execution."""

    def __init__(
        self,
        run_id: str,
        status: RunStatus,
        state: dict[str, Any],
        history: list[NodeResult],
        error: str | None = None,
        paused_at_node: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.status = status
        self.state = state
        self.history = history
        self.error = error
        self.paused_at_node = paused_at_node
