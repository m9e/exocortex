# Exocortex Architecture Design

**Date**: 2026-03-18
**Author**: Matt + Claude (initial design), Codex + Gemini (adversarial review)
**Status**: Draft v2 (post-review revision)
**Review History**: v1 reviewed by Codex (gpt-5.3-codex-spark) and Gemini; critical findings incorporated

## 1. Vision

An external cognitive system that coordinates memory, agents, and compute across arbitrary substrate. Not a single tool — a distributed, goal-oriented system that becomes increasingly autonomous.

The system maintains persistent objective graphs, prioritizes work, spawns agents to handle it, and keeps Matt informed. It can reach out and consume any authorized compute — from local GPUs to cloud inference to CLI agents (Claude Code, Codex, Gemini).

## 2. Design Center: The Graph Execution Engine

Everything in the exocortex is a node in an execution graph. The graph engine is the center of the universe. All other subsystems — memory, security, compute, agents — exist as injections into the graph, either **forced** (every node must run them) or **opt-in** (available if useful).

**Note**: This is a directed graph, not a DAG. Cycles are permitted for agentic loops (retry, reflect, refine) with mandatory iteration limits to prevent runaway execution.

### 2.1 Why Graph-Centric

The alternative architectures considered and rejected:

- **Event-driven / message-only**: Agents react to events on a bus. Problem: no structured control flow, no dependency management, no ability to prescribe execution order when you need it. You get autonomy but lose determinism.
- **Pipeline / linear**: Fixed sequence of steps. Problem: can't branch, can't parallelize, can't let agents decide their own path. You get determinism but lose autonomy.
- **Pure agent mesh**: Agents negotiate work peer-to-peer. Problem: no central visibility into what's happening, hard to inject constraints, hard to replay/debug. You get flexibility but lose observability.

The graph engine gives you all modes — prescribed, autonomous, constrained, and human-in-the-loop — in the same graph, with cycles for iterative refinement. A single execution can have deterministic steps, agent-decided branches, approval gates, and sandboxed autonomous work, all coordinated through the same state management and checkpoint system.

### 2.2 Core Abstractions

#### Nodes

A node is a unit of work. Every node has:

```python
class NodeSpec(BaseModel):
    """Definition of a node in the execution graph."""
    id: str
    name: str
    node_type: NodeType
    handler: str  # dotted path to handler function or agent spec

    # Autonomy scoping
    autonomy: AutonomySpec = AutonomySpec()

    # State projection — which state fields this node can see/write
    input_projection: list[str] | None = None   # None = all fields
    output_fields: list[str] | None = None      # Fields this node may write

    # Injection points (in addition to forced global hooks)
    pre_hooks: list[HookSpec] = []
    post_hooks: list[HookSpec] = []

    # Resource requirements and limits
    compute: ComputeRequirements | None = None
    timeout: timedelta = timedelta(minutes=5)
    retries: int = 0
    max_output_bytes: int = 10 * 1024 * 1024  # 10MB — transport boundary protection

class NodeType(str, Enum):
    PRESCRIBED = "prescribed"    # Fixed function, deterministic
    AUTONOMOUS = "autonomous"    # Agent-driven, goal-oriented
    CONSTRAINED = "constrained"  # Autonomous but bounded
    APPROVAL = "approval"        # Human-in-the-loop gate

class AutonomySpec(BaseModel):
    """Defines the boundaries of agent freedom within a node."""
    capabilities: list[CapabilityGrant] = []      # Explicit capability grants
    denied_capabilities: list[str] = []            # Explicit denials (override grants)
    allowed_subgraph_mutations: bool = False
    max_sub_nodes: int = 10
    sandbox: SandboxSpec | None = None

class CapabilityGrant(BaseModel):
    """A specific capability granted to an agent, scoped by domain."""
    capability: str          # e.g., "tool.web_search", "memory.write", "agent.spawn"
    domains: list[str] = []  # Scoping — e.g., ["*.github.com"] for web_search
    max_invocations: int | None = None  # Rate limit per execution
```

**Four node types:**

| Type | Control | Use Case |
|------|---------|----------|
| `prescribed` | Deterministic. Runs a fixed function. | Data transforms, API calls, file I/O |
| `constrained` | Autonomous within boundaries. Agent picks approach but capabilities are scoped. | Research tasks, code generation with review |
| `autonomous` | Full freedom within capability grants. Can propose graph mutations. | Open-ended goals, creative work |
| `approval` | Suspends execution, notifies human, waits for explicit approval or rejection. | High-risk actions, expense approvals, deploy gates |

#### Edges

```python
class EdgeSpec(BaseModel):
    """Definition of a transition between nodes."""
    source: str  # node id
    target: str  # node id
    edge_type: EdgeType
    condition: ConditionSpec | None = None  # Declarative condition (NOT code execution)
    protected: bool = False  # If true, cannot be removed/rewired by mutations
    max_traversals: int | None = None  # Cycle limit — required for back-edges

class EdgeType(str, Enum):
    STATIC = "static"          # Always follow: A -> B
    CONDITIONAL = "conditional" # Follow if condition evaluates true
    DYNAMIC = "dynamic"        # Agent decides at runtime

class ConditionSpec(BaseModel):
    """Declarative condition — NO arbitrary code execution."""
    field: str                 # State field to evaluate
    operator: ConditionOp      # Comparison operator
    value: Any                 # Value to compare against

class ConditionOp(str, Enum):
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
```

**Design decision**: Conditions are declarative, not arbitrary Python expressions. This eliminates the RCE vector identified in v1 review. Complex routing logic belongs in prescribed nodes, not in edge conditions.

#### Cycles and Iteration Control

Cycles are allowed but controlled:

```python
class CyclePolicy(BaseModel):
    """Controls iterative loops in the graph."""
    max_iterations: int = 10          # Hard limit on cycle traversals
    iteration_field: str = "_iteration_count"  # State field tracking count
    on_limit: CycleLimitPolicy = CycleLimitPolicy.ERROR

class CycleLimitPolicy(str, Enum):
    ERROR = "error"        # Fail the graph
    BREAK = "break"        # Continue to next non-cycle edge
    WARN = "warn"          # Log warning, continue to next edge
```

Back-edges (edges that create cycles) must have `max_traversals` set. The engine tracks iteration counts per cycle and enforces limits.

#### State

State flows through the graph. Each graph defines a **strict schema** — no arbitrary extension.

```python
class StateSchema(BaseModel):
    """Schema definition for a graph's state. Strictly typed."""
    fields: dict[str, FieldSpec]

class FieldSpec(BaseModel):
    """Specification for a single state field."""
    type: str                          # Python type annotation as string
    default: Any = None
    reducer: ReducerType | None = None # How to merge parallel branches
    description: str = ""

class ReducerType(str, Enum):
    LAST_WRITE = "last_write"   # Last writer wins (default for scalars)
    APPEND = "append"           # Append to list
    MERGE_DICT = "merge_dict"   # Shallow merge dicts
    MAX = "max"                 # Take maximum value
    MIN = "min"                 # Take minimum value
    UNION = "union"             # Set union
    CUSTOM = "custom"           # Custom reducer function (handler path)
```

**Per-field reducers** resolve parallel branch merges deterministically. Every field that may be written by parallel branches must declare a reducer. If two branches write the same field and no reducer is declared, the engine raises a `MergeConflictError` rather than silently clobbering.

**State provenance**: Every state update includes metadata:

```python
class StateUpdate(BaseModel):
    """A single state modification with provenance."""
    field: str
    value: Any
    writer_node: str
    writer_agent: str | None = None
    timestamp: datetime
    revision: int  # Monotonically increasing per field
```

The engine applies updates as immutable patches, maintaining a full history for audit and conflict resolution.

#### Checkpoints

Every node transition creates a checkpoint. Checkpoints enable:
- **Resume**: Pick up where you left off after crash/interrupt
- **Replay**: Re-run from any point with modified state
- **Audit**: Full history of what happened and why
- **Human-in-the-loop**: Approval nodes create checkpoints and suspend

```python
class Checkpoint(BaseModel):
    """Snapshot of graph state at a node boundary."""
    id: str  # uuid
    graph_id: str
    run_id: str
    node_id: str
    state: dict[str, Any]  # Serialized state
    state_patches: list[StateUpdate]  # Patches since last checkpoint
    created_at: datetime
    parent_id: str | None = None

class CheckpointStore(Protocol):
    """Storage backend for checkpoints."""
    async def save(self, checkpoint: Checkpoint) -> None: ...
    async def load(self, checkpoint_id: str) -> Checkpoint: ...
    async def list_by_run(self, run_id: str) -> list[Checkpoint]: ...
    async def latest_by_graph(self, graph_id: str) -> Checkpoint | None: ...
```

Default backend: SQLite (single-host). Postgres for multi-host deployments.

### 2.3 Graph Definition

Graphs are defined in Python (primary) or YAML (serialization/version control):

```python
# Python DSL
graph = Graph(
    name="research-and-report",
    state_schema=StateSchema(fields={
        "query": FieldSpec(type="str"),
        "sources": FieldSpec(type="list[dict]", reducer=ReducerType.APPEND),
        "findings": FieldSpec(type="list[str]", reducer=ReducerType.APPEND),
        "security_passed": FieldSpec(type="bool", default=False),
        "report": FieldSpec(type="str", default=""),
    }),
    run_budget=RunBudget(
        max_nodes=50,
        max_total_tokens=500_000,
        max_cost_usd=10.0,
        max_wall_time=timedelta(hours=1),
    ),
)

graph.add_node("decompose", handler="exocortex.handlers.decompose_query",
               node_type=NodeType.PRESCRIBED)
graph.add_node("research", handler="exocortex.agents.researcher",
               node_type=NodeType.CONSTRAINED,
               autonomy=AutonomySpec(
                   capabilities=[
                       CapabilityGrant(capability="tool.web_search"),
                       CapabilityGrant(capability="tool.web_fetch"),
                       CapabilityGrant(capability="memory.query"),
                   ],
                   max_sub_nodes=5
               ),
               input_projection=["query", "sources"],
               output_fields=["sources", "findings"])
graph.add_node("security_review", handler="exocortex.security.review_output",
               node_type=NodeType.PRESCRIBED)
graph.add_node("synthesize", handler="exocortex.handlers.synthesize",
               node_type=NodeType.CONSTRAINED,
               autonomy=AutonomySpec(
                   capabilities=[
                       CapabilityGrant(capability="memory.query"),
                       CapabilityGrant(capability="memory.write"),
                   ],
               ),
               input_projection=["findings", "query"],
               output_fields=["report"])

graph.add_edge("decompose", "research", EdgeType.STATIC)
graph.add_edge("research", "security_review", EdgeType.STATIC, protected=True)
graph.add_edge("security_review", "synthesize", EdgeType.CONDITIONAL,
               condition=ConditionSpec(field="security_passed", operator=ConditionOp.IS_TRUE),
               protected=True)

graph.set_entry("decompose")
graph.set_terminal("synthesize")
```

**Design decision**: Graph definitions live as Python/YAML files in version control. Only run executions and checkpoints go to the database. This gives version control, CI/CD testing, and rollback for definitions while keeping runtime state queryable.

### 2.4 Fan-Out / Map-Reduce

For dynamic parallel execution (e.g., process N items concurrently):

```python
class MapSpec(BaseModel):
    """Dynamic fan-out specification for parallel processing."""
    input_field: str           # State field containing iterable to map over
    node_template: NodeSpec    # Template for each parallel node
    output_field: str          # State field to collect results (must have APPEND reducer)
    max_concurrency: int = 10  # Max parallel executions
    on_item_failure: FailurePolicy = FailurePolicy.WARN  # Per-item failure policy
```

The engine creates ephemeral sub-nodes at runtime, one per item, executes them in parallel (up to `max_concurrency`), and collects results via the field's reducer.

### 2.5 Dynamic Graph Mutation

Autonomous and constrained nodes (when `allowed_subgraph_mutations=True`) can propose changes to the graph during execution:

```python
class GraphMutation(BaseModel):
    """Proposed change to the execution graph from an autonomous node."""
    mutation_type: MutationType
    node_spec: NodeSpec | None = None
    edge_spec: EdgeSpec | None = None
    reason: str
    idempotency_key: str | None = None  # Prevent duplicate mutations

class MutationType(str, Enum):
    ADD_NODE = "add_node"
    ADD_EDGE = "add_edge"
    # No REMOVE_NODE or REMOVE_EDGE — mutations are additive only
```

**Mutation validation** (all must pass):
1. Requesting node has `allowed_subgraph_mutations=True`
2. New nodes don't exceed run-level `max_nodes` budget
3. New node capabilities are a subset of the requesting node's capabilities (no escalation)
4. New node handler must be in the **handler allowlist** (registered safe modules)
5. Protected edges cannot be targeted or bypassed
6. Forced hooks are automatically applied to new nodes
7. New edges creating cycles must declare `max_traversals`
8. Mutation is logged to tamper-evident audit trail
9. Idempotency key prevents duplicate mutations from retries

**Design decision**: Mutations are additive only. No edge removal, no node removal. This prevents the "bypass security review by deleting the edge" attack vector identified in review.

### 2.6 Run Budget

Every graph execution has resource limits:

```python
class RunBudget(BaseModel):
    """Resource limits for a single graph execution."""
    max_nodes: int = 100                         # Total nodes (including dynamic)
    max_total_tokens: int = 1_000_000            # Total LLM tokens across all nodes
    max_cost_usd: float = 50.0                   # Total cost ceiling
    max_wall_time: timedelta = timedelta(hours=4) # Wall clock limit
    max_state_bytes: int = 50 * 1024 * 1024      # 50MB state size limit

class RunAccounting(BaseModel):
    """Runtime tracking of resource consumption."""
    nodes_executed: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    started_at: datetime | None = None
    # Updated after every node execution
```

The engine checks budget before each node and aborts if any limit is exceeded.

## 3. Injection System

The injection system is how all other subsystems attach to the graph. Two categories:

### 3.1 Forced Injections

Every node runs these. Cannot be bypassed. Configured at the graph level or globally.

```python
class ForcedInjection(BaseModel):
    """A hook that every node must run. Cannot be bypassed."""
    name: str
    phase: InjectionPhase  # pre | post | on_mutation
    handler: str
    timeout: timedelta = timedelta(seconds=30)
    on_failure: FailurePolicy = FailurePolicy.ABORT

class InjectionPhase(str, Enum):
    PRE = "pre"              # Before node executes
    POST = "post"            # After node executes
    ON_MUTATION = "on_mutation"  # When a mutation is proposed

class FailurePolicy(str, Enum):
    ABORT = "abort"      # Stop the graph
    WARN = "warn"        # Log and continue
    RETRY = "retry"      # Retry the node
    QUARANTINE = "quarantine"  # Move to dead-letter queue
```

**Default forced injections:**

| Phase | Injection | Purpose |
|-------|-----------|---------|
| PRE | `security.validate_input` | Content sanitization (trust-level-gated) |
| PRE | `security.check_capabilities` | Verify node's agent has required capabilities |
| PRE | `budget.check_remaining` | Abort if run budget exceeded |
| POST | `security.validate_output` | Scan output for injection/exfil, enforce `max_output_bytes` |
| POST | `memory.record_execution` | Write execution record to memory fabric |
| POST | `audit.log_result` | Append to tamper-evident audit trail |
| POST | `budget.record_usage` | Track token/cost consumption |
| ON_MUTATION | `security.validate_mutation` | Check mutation against all validation rules |

### 3.2 Opt-In Injections

Available to nodes that request them via capability grants.

```python
class OptInInjection(BaseModel):
    """A capability available to nodes that request it."""
    name: str
    capability: str
    handler: str
    description: str
```

**Available opt-in capabilities:**

| Capability | What It Does |
|-----------|--------------|
| `memory.query` | Query the shared memory fabric |
| `memory.write` | Write to memory (facts, entities, objectives) |
| `compute.discover` | Discover available compute via pdash |
| `compute.allocate` | Request compute resources |
| `agent.spawn` | Spawn a sub-agent (CLI or container) |
| `agent.delegate` | Delegate to Claude/Codex/Gemini CLI |
| `bus.publish` | Publish message to NATS bus |
| `bus.subscribe` | Subscribe to NATS topic |

## 4. Agent Runtime

### 4.1 Agent Identity and Capabilities

Every agent in the system has a persistent identity with capability-based security:

```python
class AgentIdentity(BaseModel):
    """Persistent identity for an agent in the mesh."""
    id: str  # uuid
    name: str
    agent_type: AgentType
    capabilities: list[CapabilityGrant]  # What this agent can do (IAM-style)
    runtime: RuntimeSpec
    created_at: datetime
    track_record: TrackRecord

class AgentType(str, Enum):
    LOCAL_FUNCTION = "local_function"  # Python function in-process
    CLI_AGENT = "cli_agent"           # Claude Code, Codex, Gemini CLI
    CONTAINER_AGENT = "container"      # kbox-sandboxed agent
    VM_AGENT = "vm"                    # VM-isolated agent
    REMOTE_AGENT = "remote"            # Agent on another host

class TrackRecord(BaseModel):
    """Accumulated history that informs capability expansion."""
    total_tasks: int = 0
    successful_tasks: int = 0
    failed_tasks: int = 0
    security_violations: int = 0
    last_active: datetime | None = None
    proven_domains: list[str] = []  # Domains with established track record
    capability_history: list[CapabilityChange] = []  # Audit trail of grants/revocations

class CapabilityChange(BaseModel):
    """Record of a capability being granted or revoked."""
    capability: str
    action: str  # "grant" | "revoke"
    reason: str
    changed_at: datetime
    changed_by: str  # "system" | "human" | agent_id
```

**Design decision**: Capabilities replace scalar trust levels. Instead of `UNTRUSTED → SUPERVISED → TRUSTED → PRIVILEGED`, agents have explicit capability grants scoped by domain. An agent can be trusted for `memory.query` but untrusted for `agent.spawn`. This follows the principle of least privilege and maps cleanly to IAM-style authorization.

The security pipeline still uses trust-level-like tiers for content sanitization depth, but these are derived from the agent's capability set, not stored as a separate scalar.

### 4.2 Agent Registry

```python
class AgentRegistry(Protocol):
    """Registry for discovering and managing agents."""
    async def register(self, agent: AgentIdentity) -> None: ...
    async def deregister(self, agent_id: str) -> None: ...
    async def discover(self, required_capabilities: list[str]) -> list[AgentIdentity]: ...
    async def heartbeat(self, agent_id: str) -> None: ...
    async def get(self, agent_id: str) -> AgentIdentity | None: ...
    async def update_track_record(self, agent_id: str, result: TaskResult) -> None: ...
    async def grant_capability(self, agent_id: str, grant: CapabilityGrant,
                                reason: str, grantor: str) -> None: ...
    async def revoke_capability(self, agent_id: str, capability: str,
                                 reason: str, revoker: str) -> None: ...
```

### 4.3 CLI Delegation

The system can delegate work to external CLI agents:

```python
class CLIDelegation(BaseModel):
    """Specification for delegating work to a CLI agent."""
    cli: CLIType
    prompt: str
    working_directory: str
    timeout: timedelta = timedelta(minutes=30)
    sandbox: SandboxSpec | None = None
    max_output_bytes: int = 10 * 1024 * 1024  # Transport boundary protection

class CLIType(str, Enum):
    CLAUDE = "claude"   # claude -p "prompt"
    CODEX = "codex"     # codex exec "prompt"
    GEMINI = "gemini"   # gemini -p "prompt"

class CLIResult(BaseModel):
    """Result from a CLI agent execution."""
    cli: CLIType
    exit_code: int
    stdout: str
    stderr: str
    duration: timedelta
    files_changed: list[str] = []
    token_usage: TokenUsage | None = None

class TokenUsage(BaseModel):
    """Token consumption tracking for cost budgeting."""
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    estimated_cost_usd: float = 0.0
```

CLI agents run as subprocesses (or in kbox containers for isolation). Output is size-limited at the transport boundary before deserialization to prevent OOM attacks.

### 4.4 Sandbox Integration

For untrusted or high-risk work, agents run in sandboxes:

```python
class SandboxSpec(BaseModel):
    """Specification for sandboxed execution."""
    sandbox_type: SandboxType
    image: str = "kbox-agent:latest"
    memory_limit: str = "4g"
    cpu_limit: float = 2.0
    network: NetworkPolicy = NetworkPolicy.RESTRICTED
    mount_workspace: bool = True
    credential_proxy: str | None = None  # locksmith URL

class SandboxType(str, Enum):
    CONTAINER = "container"  # kbox Docker/Podman
    VM = "vm"                # Full VM isolation

class NetworkPolicy(str, Enum):
    NONE = "none"            # No network access
    RESTRICTED = "restricted" # Only through locksmith proxy
    FULL = "full"            # Unrestricted (requires explicit capability)
```

## 5. Memory Fabric

### 5.1 Tiered Storage

```python
class MemoryTier(str, Enum):
    HOT = "hot"    # Current task context. Redis, sub-ms access.
    WARM = "warm"  # Session/project memory. SQLite (single-writer), ms access.
    COLD = "cold"  # Everything else. Vector-indexed, query-in.

class MemoryEntry(BaseModel):
    """A single entry in the memory fabric."""
    id: str
    content: str
    entry_type: str  # fact | entity | objective | observation
    tier: MemoryTier
    tags: list[str] = []
    source_agent: str | None = None
    source_graph: str | None = None
    created_at: datetime
    last_accessed: datetime
    access_count: int = 0
    access_capabilities: list[str] = []  # Which capabilities are needed to read this

class MemoryFabric(Protocol):
    """Interface to the shared memory system."""
    async def store(self, entry: MemoryEntry) -> None: ...
    async def query(self, query: str, tier: MemoryTier | None = None,
                    limit: int = 10) -> list[MemoryEntry]: ...
    async def promote(self, entry_id: str) -> None: ...
    async def demote(self, entry_id: str) -> None: ...
```

**Design decision (Hot tier)**: Redis for hot tier. In-process LRU fails in multi-worker FastAPI setups (workers don't share memory). Redis provides shared sub-ms access, TTL expiry, and doubles as a cache layer. Single dependency for hot tier + potential pub/sub complement.

**Design decision (Warm tier)**: SQLite with WAL mode and a **single async writer queue**. All writes are funneled through one writer task to prevent `database is locked` contention. Reads are concurrent (WAL allows this). Migration path to Postgres is via the protocol interface.

### 5.2 Access-Frequency Promotion

Entries automatically promote based on access patterns:
- Accessed 3+ times in an hour → promote to HOT
- Not accessed for 24 hours → demote from HOT to WARM
- Not accessed for 7 days → demote from WARM to COLD
- Thresholds configurable per deployment

### 5.3 Objective Graph

The system maintains a persistent graph of objectives — things to know about, track, or accomplish:

```python
class Objective(BaseModel):
    """A goal or interest that the system tracks."""
    id: str
    title: str
    description: str
    priority: Priority
    status: ObjectiveStatus  # active | paused | completed | abandoned
    parent_id: str | None = None
    children: list[str] = []
    dependencies: list[str] = []

    # Automation
    auto_spawn: bool = False
    spawn_graph: str | None = None  # Graph template to use
    check_interval: timedelta | None = None

    # Tracking
    last_checked: datetime | None = None
    last_updated: datetime | None = None
    findings: list[str] = []  # Memory entry IDs

    # Budget constraints
    max_cost_per_check: float = 5.0  # USD ceiling per automated check
    max_tokens_per_check: int = 100_000

class Priority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    BACKGROUND = "background"
```

**Design decision (Objective storage)**: Same database as memory (SQLite/Postgres) but separate tables with a relational schema optimized for tree queries (materialized path or adjacency list). No graph database until traversal performance actually bottlenecks.

## 6. Compute Substrate

### 6.1 Compute Discovery

Following the pdash pattern — discover all available compute:

```python
class ComputeNode(BaseModel):
    """A compute resource the system can use."""
    id: str
    name: str
    host: str
    node_type: ComputeType
    status: ComputeStatus  # online | offline | busy
    capabilities: ComputeCapabilities
    last_seen: datetime

class ComputeType(str, Enum):
    LOCAL = "local"
    KAMIWAZA = "kamiwaza"
    CLI_TOKENS = "cli_tokens"
    VM = "vm"

class ComputeCapabilities(BaseModel):
    """What this compute node can do."""
    gpus: list[str] = []
    gpu_memory_gb: float = 0
    cpu_cores: int = 0
    memory_gb: float = 0
    models_available: list[str] = []
    cli_available: list[CLIType] = []
    can_spawn_containers: bool = False
    can_spawn_vms: bool = False

class ComputeRegistry(Protocol):
    """Registry for discovering compute resources."""
    async def discover(self) -> list[ComputeNode]: ...
    async def allocate(self, requirements: ComputeRequirements) -> ComputeNode | None: ...
    async def release(self, node_id: str) -> None: ...
    async def health_check(self, node_id: str) -> ComputeStatus: ...
```

### 6.2 Message Bus

NATS JetStream-based, dual-bus architecture:

```python
class BusConfig(BaseModel):
    """Configuration for the NATS message bus."""
    primary: NATSConnection
    secondary: NATSConnection
    active: str = "primary"

class NATSConnection(BaseModel):
    """Connection details for a NATS server."""
    url: str  # nats://host:port
    name: str
    credentials: str | None = None

class MessageBus(Protocol):
    """Interface to the NATS message bus."""
    async def publish(self, topic: str, message: BusMessage) -> None: ...
    async def subscribe(self, topic: str, handler: Callable) -> Subscription: ...
    async def request(self, topic: str, message: BusMessage,
                      timeout: timedelta = timedelta(seconds=30)) -> BusMessage: ...
    async def failover(self) -> None: ...

class BusMessage(BaseModel):
    """Message on the bus."""
    id: str  # uuid
    topic: str
    source_agent: str
    payload: dict[str, Any]
    timestamp: datetime
    reply_to: str | None = None
    idempotency_key: str | None = None  # For deduplication
```

**Message semantics**: At-least-once delivery via JetStream with idempotency keys for deduplication. Dead-letter subjects for messages that fail processing after max retries.

**Topic hierarchy:**
- `exo.agents.{agent_id}.heartbeat` — Agent health
- `exo.agents.{agent_id}.commands` — Commands to agent
- `exo.graphs.{graph_id}.events` — Graph execution events
- `exo.graphs.{graph_id}.approvals` — Approval requests for HITL nodes
- `exo.memory.updates` — Memory fabric changes
- `exo.objectives.updates` — Objective graph changes
- `exo.compute.discovery` — Compute node announcements
- `exo.security.alerts` — Security events
- `exo.dlq.{topic}` — Dead-letter queue per topic

## 7. Security Envelope

### 7.1 Capability-Based Security

Security is capability-based, not scalar trust levels. Agents have explicit grants:

```python
class SecurityPolicy(BaseModel):
    """Global security policy configuration."""
    handler_allowlist: list[str]  # Module prefixes allowed as handlers
    default_capabilities: list[CapabilityGrant]  # Baseline for new agents
    escalation_requires_human: bool = True  # New capabilities need human approval
    max_capability_grants_per_agent: int = 50
    content_sanitization_tiers: dict[str, str]  # capability -> sanitization level
```

**Content sanitization** is determined by the agent's capability set:
- Agent with no granted capabilities → full pipeline (sanitize + guardrail + scan)
- Agent with basic capabilities (`memory.query`, `tool.web_search`) → light pipeline
- Agent with proven track record in domain → minimal sanitization
- Human override can bypass sanitization for specific operations

### 7.2 Security Pipeline Integration

```python
class SecurityPipeline:
    """Integration with tool-untrusted-content."""

    async def pre_hook(self, state: dict, node: NodeSpec, agent: AgentIdentity) -> HookResult:
        """Run before every node. Sanitize inputs based on agent capabilities."""
        sanitization_level = self.determine_level(agent)
        if sanitization_level == "full":
            return await self.full_pipeline(state)
        elif sanitization_level == "light":
            return await self.light_pipeline(state)
        else:
            return await self.minimal_pipeline(state)

    async def post_hook(self, state: dict, result: NodeResult, node: NodeSpec) -> HookResult:
        """Run after every node. Validate outputs."""
        # Enforce max_output_bytes before deserialization
        # Check for prompt injection in output
        # Check for credential/data exfiltration attempts
        # Verify output only writes to declared output_fields
        ...
```

### 7.3 Audit Trail

```python
class AuditEntry(BaseModel):
    """Tamper-evident audit log entry."""
    id: str
    timestamp: datetime
    event_type: str  # node_start | node_end | mutation | capability_change | security_alert
    graph_id: str | None = None
    run_id: str | None = None
    node_id: str | None = None
    agent_id: str | None = None
    details: dict[str, Any]
    previous_hash: str  # Hash of previous entry (append-only chain)
    entry_hash: str     # Hash of this entry (SHA-256)

class AuditStore(Protocol):
    """Append-only audit log."""
    async def append(self, entry: AuditEntry) -> None: ...
    async def query(self, filters: dict) -> list[AuditEntry]: ...
    async def verify_chain(self, start_id: str, end_id: str) -> bool: ...
```

### 7.4 Credential Management

Follows the locksmith pattern — agents never hold credentials directly:

```python
class CredentialProxy(BaseModel):
    """Configuration for locksmith-style credential injection."""
    url: str
    agent_token: str | None = None

class ToolAccess(BaseModel):
    """How an agent accesses external tools."""
    proxy: CredentialProxy
    allowed_tools: list[str]
```

### 7.5 Dead-Letter Queue

When a node produces output that crashes deserialization or repeatedly fails post-hooks:

```python
class DeadLetterEntry(BaseModel):
    """A quarantined item that could not be processed."""
    id: str
    graph_id: str
    run_id: str
    node_id: str
    agent_id: str | None = None
    raw_output: bytes  # Raw bytes, not deserialized
    failure_reason: str
    failure_count: int
    first_failure: datetime
    last_failure: datetime
    status: str = "quarantined"  # quarantined | reviewed | discarded
```

## 8. API Surface

FastAPI service exposing the system:

### 8.1 Graph Management
```
POST   /api/graphs                    # Register a graph definition
GET    /api/graphs                    # List all graphs
GET    /api/graphs/{id}               # Get graph definition
POST   /api/graphs/{id}/run           # Execute a graph
GET    /api/graphs/{id}/runs          # List executions
GET    /api/graphs/{id}/runs/{run_id} # Get execution status/state/accounting
POST   /api/graphs/{id}/runs/{run_id}/resume    # Resume from checkpoint
POST   /api/graphs/{id}/runs/{run_id}/approve   # Approve HITL gate
POST   /api/graphs/{id}/runs/{run_id}/reject    # Reject HITL gate
DELETE /api/graphs/{id}/runs/{run_id}            # Cancel execution
```

### 8.2 Agent Management
```
POST   /api/agents                    # Register an agent
GET    /api/agents                    # List agents
GET    /api/agents/{id}               # Get agent details + capabilities
DELETE /api/agents/{id}               # Deregister agent
POST   /api/agents/{id}/heartbeat     # Agent heartbeat
GET    /api/agents/{id}/track-record  # Get capability history
POST   /api/agents/{id}/capabilities  # Grant capability
DELETE /api/agents/{id}/capabilities/{cap}  # Revoke capability
```

### 8.3 Memory
```
POST   /api/memory                    # Store entry
GET    /api/memory/query              # Query memory
GET    /api/memory/{id}               # Get specific entry
PUT    /api/memory/{id}/promote       # Promote tier
PUT    /api/memory/{id}/demote        # Demote tier
```

### 8.4 Objectives
```
POST   /api/objectives               # Create objective
GET    /api/objectives               # List objectives (tree)
GET    /api/objectives/{id}          # Get objective details
PUT    /api/objectives/{id}          # Update objective
POST   /api/objectives/{id}/spawn    # Manually spawn agent for objective
```

### 8.5 Compute
```
GET    /api/compute                   # Discover all compute
GET    /api/compute/{id}              # Get compute node details
POST   /api/compute/{id}/allocate     # Allocate compute
POST   /api/compute/{id}/release      # Release compute
```

### 8.6 Audit
```
GET    /api/audit                     # Query audit trail
GET    /api/audit/verify              # Verify chain integrity
GET    /api/dlq                       # List dead-letter queue entries
POST   /api/dlq/{id}/review          # Mark DLQ entry as reviewed
```

## 9. Project Structure

```
exocortex/
├── pyproject.toml
├── AGENTS.md
├── docs/
│   └── superpowers/specs/
├── src/
│   └── exocortex/
│       ├── __init__.py
│       ├── core/
│       │   ├── __init__.py
│       │   ├── engine.py              # Graph execution engine
│       │   ├── graph.py               # Graph definition, nodes, edges
│       │   ├── state.py               # Typed state management + reducers
│       │   ├── checkpoint.py          # Checkpoint/resume (SQLite backend)
│       │   ├── mutations.py           # Mutation validation
│       │   ├── budget.py              # Run budget tracking
│       │   ├── conditions.py          # Declarative condition evaluation
│       │   ├── fanout.py              # Map/fan-out execution
│       │   └── models.py              # Core Pydantic models
│       ├── injection/
│       │   ├── __init__.py
│       │   ├── hooks.py               # Pre/post/on_mutation hook execution
│       │   ├── registry.py            # Hook registration
│       │   └── policies.py            # Forced vs opt-in classification
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── registry.py            # Agent registration/discovery
│       │   ├── identity.py            # Agent identity + capabilities
│       │   ├── runtime.py             # Agent execution (subprocess, CLI)
│       │   ├── cli.py                 # Claude/Codex/Gemini CLI wrappers
│       │   └── sandbox.py             # kbox + VM integration
│       ├── memory/
│       │   ├── __init__.py
│       │   ├── fabric.py              # Memory fabric interface
│       │   ├── tiers.py               # Hot (Redis) / warm (SQLite) / cold
│       │   ├── objectives.py          # Objective graph
│       │   ├── store.py               # SQLite storage backend (single-writer)
│       │   └── redis_store.py         # Redis hot tier backend
│       ├── compute/
│       │   ├── __init__.py
│       │   ├── discovery.py           # Compute discovery (pdash pattern)
│       │   ├── allocation.py          # Resource allocation
│       │   ├── credentials.py         # Locksmith integration
│       │   └── bus.py                 # NATS JetStream message bus
│       ├── security/
│       │   ├── __init__.py
│       │   ├── capabilities.py        # Capability-based authorization
│       │   ├── pipeline.py            # Content sanitization
│       │   ├── audit.py               # Tamper-evident audit trail
│       │   ├── dlq.py                 # Dead-letter queue
│       │   └── sandbox.py             # Sandbox lifecycle management
│       └── api/
│           ├── __init__.py
│           ├── app.py                 # FastAPI application
│           ├── routes/
│           │   ├── __init__.py
│           │   ├── graphs.py
│           │   ├── agents.py
│           │   ├── memory.py
│           │   ├── objectives.py
│           │   ├── compute.py
│           │   └── audit.py
│           └── middleware.py          # Auth + capability checking
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── unit/
│   │   ├── __init__.py
│   │   ├── test_engine.py
│   │   ├── test_graph.py
│   │   ├── test_state.py
│   │   ├── test_conditions.py
│   │   ├── test_checkpoint.py
│   │   ├── test_mutations.py
│   │   ├── test_fanout.py
│   │   ├── test_hooks.py
│   │   ├── test_budget.py
│   │   ├── test_capabilities.py
│   │   ├── test_agent_registry.py
│   │   ├── test_memory_fabric.py
│   │   ├── test_objectives.py
│   │   └── test_audit.py
│   └── integration/
│       ├── __init__.py
│       ├── test_graph_execution.py    # Full graph execution with hooks
│       ├── test_cycles.py             # Cycle iteration and limits
│       ├── test_fanout.py             # Map/reduce execution
│       ├── test_approval.py           # HITL approval flow
│       ├── test_cli_delegation.py     # CLI agent delegation
│       ├── test_api.py                # FastAPI endpoint tests
│       └── test_bus.py                # NATS bus integration
└── scripts/
    └── run.py
```

## 10. Technology Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Language | Python 3.12+ | Matt's preference, consistent with pdash/tool-untrusted-content |
| Data models | Pydantic v2 | Matt's preference, strict validation + serialization |
| API framework | FastAPI | Matt's preference, consistent with existing infra |
| Database | SQLite (aiosqlite) + WAL | Portable, single-writer queue for concurrency |
| Hot cache | Redis | Shared hot tier across workers, sub-ms access |
| Message bus | NATS JetStream (nats-py) | Durable pub/sub, at-least-once, clustering |
| Async | asyncio + uvicorn | Standard Python async stack |
| Testing | pytest + pytest-asyncio + httpx | Standard, with async support |
| Container mgmt | Docker SDK for Python | kbox integration |
| CLI execution | asyncio.subprocess | For Claude/Codex/Gemini delegation |
| Package mgmt | uv | Fast, modern Python package manager |

## 11. Implementation Priority

Phase 1 — Graph Engine Core:
1. Graph definition (nodes, edges, state schemas, conditions)
2. Prescribed-node execution with state management
3. Per-field reducers for parallel branch merging
4. Checkpoint/resume with SQLite
5. Pre/post hook system (forced injections)
6. Run budget tracking and enforcement
7. Cycle support with iteration limits

Phase 2 — Agent Runtime:
8. Agent identity and capability-based registry
9. CLI delegation (Claude/Codex/Gemini wrappers)
10. Async/parallel node execution
11. Fan-out / map-reduce
12. Approval (HITL) nodes

Phase 3 — Memory + Objectives:
13. Memory fabric with tiered storage (Redis hot, SQLite warm)
14. Objective graph with tree queries
15. Memory-driven agent spawning

Phase 4 — Compute + Bus:
16. Compute discovery (pdash integration)
17. NATS JetStream message bus (dual-bus)
18. Multi-host coordination

Phase 5 — Security Hardening:
19. Full capability-based authorization
20. Tamper-evident audit trail
21. Security pipeline integration (untrusted-content)
22. Dead-letter queue
23. Sandbox integration (kbox)

## 12. Resolved Design Decisions

These were open questions in v1, now resolved based on Codex/Gemini review:

1. **Graph persistence**: Definitions as Python/YAML files in Git (version control, CI/CD). Run executions and checkpoints in the database (queryable, lockable).

2. **State reducers**: Mandatory per-field reducers for any field writable by parallel branches. Conflict raises `MergeConflictError` if no reducer declared. Inspired by LangGraph but with strict enforcement.

3. **Message bus**: NATS JetStream. Durable streams, at-least-once delivery, idempotency keys for dedup. Dead-letter subjects for poison messages.

4. **Hot tier**: Redis. Shared across FastAPI workers, TTL expiry, sub-ms access.

5. **Objective storage**: Same database as memory, separate tables with materialized path for tree queries. No graph database until proven necessary.

6. **Edge conditions**: Declarative condition DSL (field + operator + value). No arbitrary code execution. Complex routing logic goes in prescribed nodes.

7. **Mutations**: Additive only (no edge/node removal). Handler allowlist. Protected edges. Run-level node budget. Tamper-evident audit.

8. **Trust model**: Capability-based (IAM-style grants) instead of scalar trust levels. Per-capability, per-domain scoping.

## 13. Schema Versioning

All Pydantic models include version metadata:

```python
class SchemaVersion(BaseModel):
    """Version tracking for schema evolution."""
    version: int = 1
    min_compatible: int = 1  # Minimum version that can read this data
```

Migration strategy:
- Additive changes (new optional fields): bump version, no migration needed
- Breaking changes: bump version + min_compatible, write migration function
- Checkpoint store includes schema version; old checkpoints are migrated on load
- NATS messages include schema version in headers for forward/backward compatibility
