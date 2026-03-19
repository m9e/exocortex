"""Integration test: engine + checkpoint store working together."""

from pathlib import Path

import pytest

from exocortex.core.checkpoint import SQLiteCheckpointStore
from exocortex.core.engine import GraphEngine, RunStatus
from exocortex.core.graph import Graph, NodeType
from exocortex.core.state import FieldSpec, StateSchema


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_checkpoints.db"


class TestCheckpointIntegration:
    async def test_checkpoints_created_on_each_node(self, db_path: Path):
        store = SQLiteCheckpointStore(db_path)
        try:
            g = Graph(
                name="test-graph",
                state_schema=StateSchema(fields={
                    "step": FieldSpec(field_type="int", default=0),
                }),
            )
            g.add_node("a", handler="h.a")
            g.add_node("b", handler="h.b")
            g.add_node("c", handler="h.c")
            g.add_edge("a", "b")
            g.add_edge("b", "c")
            g.set_entry("a")
            g.set_terminal("c")

            engine = GraphEngine(g, checkpoint_store=store)
            engine.register_handler("h.a", lambda s: {"step": 1})
            engine.register_handler("h.b", lambda s: {"step": 2})
            engine.register_handler("h.c", lambda s: {"step": 3})

            result = await engine.arun()
            assert result.status == RunStatus.COMPLETED

            checkpoints = await store.list_by_run(result.run_id)
            assert len(checkpoints) == 3  # One per node

            assert checkpoints[0].node_id == "a"
            assert checkpoints[1].node_id == "b"
            assert checkpoints[2].node_id == "c"

            # Each checkpoint has the state at that point
            assert checkpoints[0].state["step"] == 1
            assert checkpoints[1].state["step"] == 2
            assert checkpoints[2].state["step"] == 3

            # Parent chain is correct
            assert checkpoints[0].parent_id is None
            assert checkpoints[1].parent_id == checkpoints[0].id
            assert checkpoints[2].parent_id == checkpoints[1].id
        finally:
            await store.close()

    async def test_checkpoint_on_approval_pause(self, db_path: Path):
        store = SQLiteCheckpointStore(db_path)
        try:
            g = Graph(
                name="approval-graph",
                state_schema=StateSchema(fields={
                    "data": FieldSpec(field_type="str", default=""),
                }),
            )
            g.add_node("prepare", handler="h.prep")
            g.add_node("approve", handler="h.noop", node_type=NodeType.APPROVAL)
            g.add_node("finish", handler="h.finish")
            g.add_edge("prepare", "approve")
            g.add_edge("approve", "finish")
            g.set_entry("prepare")
            g.set_terminal("finish")

            engine = GraphEngine(g, checkpoint_store=store)
            engine.register_handler("h.prep", lambda s: {"data": "ready"})
            engine.register_handler("h.noop", lambda s: {})
            engine.register_handler("h.finish", lambda s: {"data": "done"})

            # Run until approval gate
            result = await engine.arun()
            assert result.status == RunStatus.AWAITING_APPROVAL

            checkpoints = await store.list_by_run(result.run_id)
            # 1 from prepare node + 1 from approval pause
            assert len(checkpoints) == 2
            assert checkpoints[1].node_id == "approve"
        finally:
            await store.close()

    async def test_latest_by_graph(self, db_path: Path):
        store = SQLiteCheckpointStore(db_path)
        try:
            g = Graph(name="latest-test")
            g.add_node("a", handler="h.a")
            g.set_entry("a")
            g.set_terminal("a")

            engine = GraphEngine(g, checkpoint_store=store)
            engine.register_handler("h.a", lambda s: {})

            # Run twice
            await engine.arun()
            await engine.arun()

            latest = await store.latest_by_graph("latest-test")
            assert latest is not None
        finally:
            await store.close()

    async def test_engine_works_without_checkpoint_store(self):
        """Engine should work fine with no checkpoint store."""
        g = Graph(name="no-store")
        g.add_node("a", handler="h.a")
        g.set_entry("a")
        g.set_terminal("a")

        engine = GraphEngine(g)  # No store
        engine.register_handler("h.a", lambda s: {})

        result = await engine.arun()
        assert result.status == RunStatus.COMPLETED
