"""Integration tests for the FastAPI service."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from exocortex.api.app import create_app
from exocortex.core.engine import GraphEngine
from exocortex.core.graph import Graph, NodeType
from exocortex.core.state import FieldSpec, StateSchema


def _register_test_graph(app_state: Any) -> None:
    """Register a simple test graph in the app state."""
    g = Graph(
        name="test-pipeline",
        state_schema=StateSchema(
            fields={
                "message": FieldSpec(field_type="str", default=""),
            }
        ),
    )
    g.add_node("greet", handler="h.greet")
    g.add_node("upper", handler="h.upper")
    g.add_edge("greet", "upper")
    g.set_entry("greet")
    g.set_terminal("upper")

    engine = GraphEngine(g, checkpoint_store=app_state.checkpoint_store)
    engine.register_handler("h.greet", lambda s: {"message": "hello world"})
    engine.register_handler("h.upper", lambda s: {"message": s.get("message", "").upper()})
    app_state.engines["test-pipeline"] = engine


def _register_approval_graph(app_state: Any) -> None:
    """Register a graph with an approval gate."""
    g = Graph(
        name="approval-flow",
        state_schema=StateSchema(
            fields={
                "data": FieldSpec(field_type="str", default=""),
            }
        ),
    )
    g.add_node("prepare", handler="h.prep")
    g.add_node("gate", handler="h.noop", node_type=NodeType.APPROVAL)
    g.add_node("finish", handler="h.finish")
    g.add_edge("prepare", "gate")
    g.add_edge("gate", "finish")
    g.set_entry("prepare")
    g.set_terminal("finish")

    engine = GraphEngine(g, checkpoint_store=app_state.checkpoint_store)
    engine.register_handler("h.prep", lambda s: {"data": "ready"})
    engine.register_handler("h.noop", lambda s: {})
    engine.register_handler("h.finish", lambda s: {"data": "done"})
    app_state.engines["approval-flow"] = engine


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        _register_test_graph(app.state)
        _register_approval_graph(app.state)
        yield c


class TestHealthEndpoint:
    def test_health(self, client: TestClient):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


class TestGraphRoutes:
    def test_list_graphs(self, client: TestClient):
        r = client.get("/api/graphs")
        assert r.status_code == 200
        names = r.json()
        assert "test-pipeline" in names
        assert "approval-flow" in names

    def test_run_graph(self, client: TestClient):
        r = client.post("/api/graphs/test-pipeline/run", json={})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "completed"
        assert body["node_count"] == 2
        assert body["graph_name"] == "test-pipeline"

    def test_run_nonexistent_graph(self, client: TestClient):
        r = client.post("/api/graphs/nope/run", json={})
        assert r.status_code == 404

    def test_get_run_detail(self, client: TestClient):
        # Run a graph
        run_resp = client.post("/api/graphs/test-pipeline/run", json={})
        run_id = run_resp.json()["run_id"]

        # Get detail
        r = client.get(f"/api/runs/{run_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["state"]["message"] == "HELLO WORLD"
        assert len(body["history"]) == 2

    def test_list_runs(self, client: TestClient):
        client.post("/api/graphs/test-pipeline/run", json={})
        client.post("/api/graphs/test-pipeline/run", json={})

        r = client.get("/api/graphs/test-pipeline/runs")
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_cancel_run(self, client: TestClient):
        run_resp = client.post("/api/graphs/test-pipeline/run", json={})
        run_id = run_resp.json()["run_id"]

        r = client.delete(f"/api/runs/{run_id}")
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"

        # Verify it's gone
        r = client.get(f"/api/runs/{run_id}")
        assert r.status_code == 404


class TestApprovalFlow:
    def test_approval_pauses_and_resumes(self, client: TestClient):
        # Run graph — should pause at approval gate
        run_resp = client.post("/api/graphs/approval-flow/run", json={})
        body = run_resp.json()
        assert body["status"] == "awaiting_approval"
        run_id = body["run_id"]

        # Approve
        r = client.post(f"/api/runs/{run_id}/approve", json={"approved": True})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "completed"

        # Verify final state
        detail = client.get(f"/api/runs/{run_id}").json()
        assert detail["state"]["data"] == "done"

    def test_approval_rejection(self, client: TestClient):
        run_resp = client.post("/api/graphs/approval-flow/run", json={})
        run_id = run_resp.json()["run_id"]

        r = client.post(f"/api/runs/{run_id}/approve", json={"approved": False})
        assert r.status_code == 200
        assert r.json()["status"] == "failed"

    def test_approve_non_waiting_run(self, client: TestClient):
        run_resp = client.post("/api/graphs/test-pipeline/run", json={})
        run_id = run_resp.json()["run_id"]

        r = client.post(f"/api/runs/{run_id}/approve", json={"approved": True})
        assert r.status_code == 400
