"""Graph definition — nodes, edges, and structural validation."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from exocortex.core.state import StateSchema


class ConditionOp(StrEnum):
    EQ = "eq"
    NEQ = "neq"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    NOT_IN = "not_in"
    IS_TRUE = "is_true"
    IS_FALSE = "is_false"
    EXISTS = "exists"


class ConditionSpec(BaseModel):
    """Declarative condition — no arbitrary code execution."""

    field: str
    operator: ConditionOp
    value: Any = None


class NodeType(StrEnum):
    PRESCRIBED = "prescribed"
    AUTONOMOUS = "autonomous"
    CONSTRAINED = "constrained"
    APPROVAL = "approval"


class CapabilityGrant(BaseModel):
    capability: str
    domains: list[str] = []
    max_invocations: int | None = None


class AutonomySpec(BaseModel):
    capabilities: list[CapabilityGrant] = []
    denied_capabilities: list[str] = []
    allowed_subgraph_mutations: bool = False
    max_sub_nodes: int = 10


class HookSpec(BaseModel):
    name: str
    handler: str
    timeout_seconds: float = 30.0


class NodeSpec(BaseModel):
    """Definition of a node in the execution graph."""

    id: str
    name: str
    node_type: NodeType
    handler: str

    autonomy: AutonomySpec = AutonomySpec()
    input_projection: list[str] | None = None
    output_fields: list[str] | None = None

    pre_hooks: list[HookSpec] = []
    post_hooks: list[HookSpec] = []

    timeout_seconds: float = 300.0
    retries: int = 0
    max_output_bytes: int = 10 * 1024 * 1024


class EdgeType(StrEnum):
    STATIC = "static"
    CONDITIONAL = "conditional"
    DYNAMIC = "dynamic"


class EdgeSpec(BaseModel):
    """Definition of a transition between nodes."""

    source: str
    target: str
    edge_type: EdgeType
    condition: ConditionSpec | None = None
    protected: bool = False
    max_traversals: int | None = None


class RunBudget(BaseModel):
    max_nodes: int = 100
    max_total_tokens: int = 1_000_000
    max_cost_usd: float = 50.0
    max_wall_seconds: float = 14400.0  # 4 hours
    max_state_bytes: int = 50 * 1024 * 1024


class GraphDefinitionError(Exception):
    pass


class Graph:
    """Mutable graph builder. Validates structure on build."""

    def __init__(
        self,
        name: str,
        state_schema: StateSchema | None = None,
        run_budget: RunBudget | None = None,
    ) -> None:
        self.name = name
        self.state_schema = state_schema or StateSchema(fields={})
        self.run_budget = run_budget or RunBudget()
        self._nodes: dict[str, NodeSpec] = {}
        self._edges: list[EdgeSpec] = []
        self._entry: str | None = None
        self._terminals: set[str] = set()

    def add_node(
        self,
        node_id: str,
        handler: str,
        node_type: NodeType = NodeType.PRESCRIBED,
        name: str | None = None,
        **kwargs: Any,
    ) -> None:
        if node_id in self._nodes:
            raise GraphDefinitionError(f"Duplicate node id: {node_id}")
        self._nodes[node_id] = NodeSpec(
            id=node_id,
            name=name or node_id,
            node_type=node_type,
            handler=handler,
            **kwargs,
        )

    def add_edge(
        self,
        source: str,
        target: str,
        edge_type: EdgeType = EdgeType.STATIC,
        condition: ConditionSpec | None = None,
        protected: bool = False,
        max_traversals: int | None = None,
    ) -> None:
        self._edges.append(
            EdgeSpec(
                source=source,
                target=target,
                edge_type=edge_type,
                condition=condition,
                protected=protected,
                max_traversals=max_traversals,
            )
        )

    def set_entry(self, node_id: str) -> None:
        self._entry = node_id

    def set_terminal(self, node_id: str) -> None:
        self._terminals.add(node_id)

    @property
    def nodes(self) -> dict[str, NodeSpec]:
        return dict(self._nodes)

    @property
    def edges(self) -> list[EdgeSpec]:
        return list(self._edges)

    @property
    def entry(self) -> str | None:
        return self._entry

    @property
    def terminals(self) -> set[str]:
        return set(self._terminals)

    def outgoing_edges(self, node_id: str) -> list[EdgeSpec]:
        return [e for e in self._edges if e.source == node_id]

    def incoming_edges(self, node_id: str) -> list[EdgeSpec]:
        return [e for e in self._edges if e.target == node_id]

    def validate(self) -> list[str]:
        """Validate graph structure. Returns list of errors."""
        errors: list[str] = []

        if not self._entry:
            errors.append("No entry node set")
        elif self._entry not in self._nodes:
            errors.append(f"Entry node '{self._entry}' not found in nodes")

        for t in self._terminals:
            if t not in self._nodes:
                errors.append(f"Terminal node '{t}' not found in nodes")

        if not self._terminals:
            errors.append("No terminal nodes set")

        for edge in self._edges:
            if edge.source not in self._nodes:
                errors.append(f"Edge source '{edge.source}' not in nodes")
            if edge.target not in self._nodes:
                errors.append(f"Edge target '{edge.target}' not in nodes")
            if edge.edge_type == EdgeType.CONDITIONAL and edge.condition is None:
                errors.append(f"Conditional edge {edge.source}->{edge.target} has no condition")

        # Check back-edges have max_traversals
        back_edges = self._find_back_edges()
        for edge in back_edges:
            if edge.max_traversals is None:
                errors.append(
                    f"Back-edge {edge.source}->{edge.target} creates a cycle "
                    f"but has no max_traversals limit"
                )

        # Check reachability from entry
        if self._entry and self._entry in self._nodes:
            reachable = self._reachable_from(self._entry)
            for node_id in self._nodes:
                if node_id not in reachable:
                    errors.append(f"Node '{node_id}' is unreachable from entry")

        return errors

    def _find_back_edges(self) -> list[EdgeSpec]:
        """Find edges that create cycles using DFS."""
        if not self._entry:
            return []

        back_edges: list[EdgeSpec] = []
        visited: set[str] = set()
        in_stack: set[str] = set()

        def dfs(node: str) -> None:
            visited.add(node)
            in_stack.add(node)
            for edge in self.outgoing_edges(node):
                if edge.target in in_stack:
                    back_edges.append(edge)
                elif edge.target not in visited:
                    dfs(edge.target)
            in_stack.discard(node)

        dfs(self._entry)
        return back_edges

    def _reachable_from(self, start: str) -> set[str]:
        """BFS to find all reachable nodes."""
        visited: set[str] = set()
        queue = [start]
        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            for edge in self.outgoing_edges(node):
                if edge.target not in visited:
                    queue.append(edge.target)
        return visited
