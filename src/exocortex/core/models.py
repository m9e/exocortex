"""Core Pydantic v2 models for the graph execution engine.

Defines nodes, edges, state, checkpoints, results, budgets, mutations,
and map/fan-out specs. Injection/hook models live in injection_models.py.
"""

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from exocortex.core.injection_models import FailurePolicy, HookSpec

_STRICT = ConfigDict(strict=True)


class NodeType(StrEnum):
    PRESCRIBED = "prescribed"
    AUTONOMOUS = "autonomous"
    CONSTRAINED = "constrained"
    APPROVAL = "approval"


class EdgeType(StrEnum):
    STATIC = "static"
    CONDITIONAL = "conditional"
    DYNAMIC = "dynamic"


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


class ReducerType(StrEnum):
    LAST_WRITE = "last_write"
    APPEND = "append"
    MERGE_DICT = "merge_dict"
    MAX = "max"
    MIN = "min"
    UNION = "union"
    CUSTOM = "custom"


class CycleLimitPolicy(StrEnum):
    ERROR = "error"
    BREAK = "break"
    WARN = "warn"


class ResultStatus(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"
    ABORTED = "aborted"


class MutationType(StrEnum):
    ADD_NODE = "add_node"
    ADD_EDGE = "add_edge"


class ConditionSpec(BaseModel):
    """Declarative condition -- NO arbitrary code execution."""

    model_config = _STRICT
    field: str
    operator: ConditionOp
    value: Any = None


class EdgeSpec(BaseModel):
    """Definition of a transition between nodes."""

    model_config = _STRICT
    source: str
    target: str
    edge_type: EdgeType
    condition: ConditionSpec | None = None
    protected: bool = False
    max_traversals: int | None = None


class CapabilityGrant(BaseModel):
    """A specific capability granted to an agent, scoped by domain."""

    model_config = _STRICT
    capability: str
    domains: list[str] = []
    max_invocations: int | None = None


class AutonomySpec(BaseModel):
    """Defines the boundaries of agent freedom within a node."""

    model_config = _STRICT
    capabilities: list[CapabilityGrant] = []
    denied_capabilities: list[str] = []
    allowed_subgraph_mutations: bool = False
    max_sub_nodes: int = 10


class NodeSpec(BaseModel):
    """Definition of a node in the execution graph."""

    model_config = _STRICT
    id: str
    name: str
    node_type: NodeType
    handler: str
    autonomy: AutonomySpec = AutonomySpec()
    input_projection: list[str] | None = None
    output_fields: list[str] | None = None
    pre_hooks: list[HookSpec] = []
    post_hooks: list[HookSpec] = []
    timeout: timedelta = timedelta(minutes=5)
    retries: int = 0
    max_output_bytes: int = 10 * 1024 * 1024


class FieldSpec(BaseModel):
    """Specification for a single state field."""

    model_config = _STRICT
    field_type: str
    default: Any = None
    reducer: ReducerType | None = None
    description: str = ""


class StateSchema(BaseModel):
    """Schema definition for a graph's state. Strictly typed."""

    model_config = _STRICT
    fields: dict[str, FieldSpec]


class StateUpdate(BaseModel):
    """A single state modification with provenance."""

    model_config = _STRICT
    field: str
    value: Any
    writer_node: str
    writer_agent: str | None = None
    timestamp: datetime
    revision: int


class CyclePolicy(BaseModel):
    """Controls iterative loops in the graph."""

    model_config = _STRICT
    max_iterations: int = 10
    iteration_field: str = "_iteration_count"
    on_limit: CycleLimitPolicy = CycleLimitPolicy.ERROR


class ErrorRecord(BaseModel):
    """Structured error information from a node execution."""

    model_config = _STRICT
    error_type: str
    message: str
    node_id: str
    timestamp: datetime
    traceback: str | None = None


class NodeResult(BaseModel):
    """Outcome of executing a single node."""

    model_config = _STRICT
    node_id: str
    status: ResultStatus
    state_updates: list[StateUpdate] = []
    errors: list[ErrorRecord] = []
    tokens_used: int = 0
    cost_usd: float = 0.0
    wall_time: timedelta | None = None


class Checkpoint(BaseModel):
    """Snapshot of graph state at a node boundary."""

    model_config = _STRICT
    id: str
    graph_id: str
    run_id: str
    node_id: str
    state: dict[str, Any]
    state_patches: list[StateUpdate] = []
    created_at: datetime
    parent_id: str | None = None


class GraphMutation(BaseModel):
    """Proposed change to the execution graph from an autonomous node."""

    model_config = _STRICT
    mutation_type: MutationType
    node_spec: NodeSpec | None = None
    edge_spec: EdgeSpec | None = None
    reason: str
    idempotency_key: str | None = None


class RunBudget(BaseModel):
    """Resource limits for a single graph execution."""

    model_config = _STRICT
    max_nodes: int = 100
    max_total_tokens: int = 1_000_000
    max_cost_usd: float = 50.0
    max_wall_time: timedelta = timedelta(hours=4)
    max_state_bytes: int = 50 * 1024 * 1024


class RunAccounting(BaseModel):
    """Runtime tracking of resource consumption."""

    model_config = _STRICT
    nodes_executed: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    started_at: datetime | None = None


class MapSpec(BaseModel):
    """Dynamic fan-out specification for parallel processing."""

    model_config = _STRICT
    input_field: str
    node_template: NodeSpec
    output_field: str
    max_concurrency: int = 10
    on_item_failure: FailurePolicy = FailurePolicy.WARN
