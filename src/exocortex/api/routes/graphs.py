"""Graph management API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from exocortex.core.engine import GraphEngine, RunResult, RunStatus

router = APIRouter(tags=["graphs"])


# --- Request/Response models ---


class RegisterGraphRequest(BaseModel):
    """Register a graph definition by name with its serialized spec."""

    name: str
    definition: dict[str, Any]


class RunGraphRequest(BaseModel):
    initial_state: dict[str, Any] | None = None


class ApprovalRequest(BaseModel):
    approved: bool


class RunSummary(BaseModel):
    run_id: str
    graph_name: str
    status: str
    node_count: int
    error: str | None = None
    paused_at_node: str | None = None


class RunDetail(BaseModel):
    run_id: str
    graph_name: str
    status: str
    state: dict[str, Any]
    node_count: int
    error: str | None = None
    paused_at_node: str | None = None
    traversal_counts: dict[str, int] = {}
    history: list[dict[str, Any]] = []


def _run_to_summary(graph_name: str, r: RunResult) -> RunSummary:
    return RunSummary(
        run_id=r.run_id,
        graph_name=graph_name,
        status=r.status,
        node_count=len(r.history),
        error=r.error,
        paused_at_node=r.paused_at_node,
    )


def _run_to_detail(graph_name: str, r: RunResult) -> RunDetail:
    tc = {f"{k[0]}->{k[1]}": v for k, v in r.traversal_counts.items()}
    history = [
        {
            "node_id": nr.node_id,
            "status": nr.status,
            "output": nr.output,
            "started_at": nr.started_at.isoformat(),
            "completed_at": nr.completed_at.isoformat(),
        }
        for nr in r.history
    ]
    return RunDetail(
        run_id=r.run_id,
        graph_name=graph_name,
        status=r.status,
        state=r.state,
        node_count=len(r.history),
        error=r.error,
        paused_at_node=r.paused_at_node,
        traversal_counts=tc,
        history=history,
    )


# --- Helpers ---


def _get_engine(request: Request, graph_name: str) -> GraphEngine:
    engines = request.app.state.engines
    if graph_name not in engines:
        raise HTTPException(404, f"Graph '{graph_name}' not registered")
    return engines[graph_name]


def _get_run(request: Request, run_id: str) -> tuple[str, RunResult]:
    runs = request.app.state.runs
    if run_id not in runs:
        raise HTTPException(404, f"Run '{run_id}' not found")
    return runs[run_id]


# --- Routes ---


@router.get("/graphs")
async def list_graphs(request: Request) -> list[str]:
    return list(request.app.state.engines.keys())


@router.post("/graphs/{graph_name}/run", response_model=RunSummary)
async def run_graph(
    graph_name: str,
    body: RunGraphRequest,
    request: Request,
) -> RunSummary:
    engine = _get_engine(request, graph_name)
    result = await engine.arun(body.initial_state)

    request.app.state.runs[result.run_id] = (graph_name, result)
    return _run_to_summary(graph_name, result)


@router.get("/graphs/{graph_name}/runs", response_model=list[RunSummary])
async def list_runs(graph_name: str, request: Request) -> list[RunSummary]:
    _get_engine(request, graph_name)  # Validates graph exists
    runs = request.app.state.runs
    return [_run_to_summary(gn, r) for rid, (gn, r) in runs.items() if gn == graph_name]


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(run_id: str, request: Request) -> RunDetail:
    graph_name, result = _get_run(request, run_id)
    return _run_to_detail(graph_name, result)


@router.post("/runs/{run_id}/approve", response_model=RunSummary)
async def approve_run(
    run_id: str,
    body: ApprovalRequest,
    request: Request,
) -> RunSummary:
    graph_name, result = _get_run(request, run_id)

    if result.status != RunStatus.AWAITING_APPROVAL:
        raise HTTPException(400, f"Run is not awaiting approval (status: {result.status})")

    if result.paused_at_node is None:
        raise HTTPException(400, "Run has no paused node")

    engine = _get_engine(request, graph_name)
    resumed = await engine.aresume(
        run_id=run_id,
        state=result.state,
        history=result.history,
        from_node=result.paused_at_node,
        approved=body.approved,
        traversal_counts=result.traversal_counts,
    )

    request.app.state.runs[run_id] = (graph_name, resumed)
    return _run_to_summary(graph_name, resumed)


@router.delete("/runs/{run_id}")
async def cancel_run(run_id: str, request: Request) -> dict[str, str]:
    if run_id not in request.app.state.runs:
        raise HTTPException(404, f"Run '{run_id}' not found")
    del request.app.state.runs[run_id]
    return {"status": "cancelled", "run_id": run_id}
