"""Tests for SQLiteCheckpointStore."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from exocortex.core.checkpoint import Checkpoint, SQLiteCheckpointStore, StateUpdate


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "checkpoints.db"


@pytest.fixture
async def store(db_path: Path) -> SQLiteCheckpointStore:
    s = SQLiteCheckpointStore(db_path)
    yield s
    await s.close()


def _make_checkpoint(
    *,
    graph_id: str = "graph-1",
    run_id: str = "run-1",
    node_id: str = "node-1",
    state: dict | None = None,
    parent_id: str | None = None,
    created_at: datetime | None = None,
) -> Checkpoint:
    kwargs: dict = {
        "graph_id": graph_id,
        "run_id": run_id,
        "node_id": node_id,
        "state": state or {"key": "value"},
        "parent_id": parent_id,
    }
    if created_at is not None:
        kwargs["created_at"] = created_at
    return Checkpoint(**kwargs)


# ------------------------------------------------------------------
# Save and load roundtrip
# ------------------------------------------------------------------


async def test_save_and_load_roundtrip(store: SQLiteCheckpointStore) -> None:
    cp = Checkpoint(
        graph_id="graph-1",
        run_id="run-1",
        node_id="node-1",
        state={"counter": 42, "items": [1, 2, 3]},
        state_patches=[
            StateUpdate(
                field="counter",
                value=42,
                writer_node="node-1",
                timestamp=datetime.now(UTC),
                revision=1,
            ),
        ],
    )
    await store.save(cp)

    loaded = await store.load(cp.id)

    assert loaded.id == cp.id
    assert loaded.graph_id == cp.graph_id
    assert loaded.run_id == cp.run_id
    assert loaded.node_id == cp.node_id
    assert loaded.state == cp.state
    assert len(loaded.state_patches) == 1
    assert loaded.state_patches[0].field == "counter"
    assert loaded.state_patches[0].value == 42
    assert loaded.parent_id == cp.parent_id


async def test_load_missing_raises_key_error(store: SQLiteCheckpointStore) -> None:
    with pytest.raises(KeyError, match="Checkpoint not found"):
        await store.load("nonexistent-id")


# ------------------------------------------------------------------
# list_by_run
# ------------------------------------------------------------------


async def test_list_by_run_returns_correct_checkpoints(
    store: SQLiteCheckpointStore,
) -> None:
    now = datetime.now(UTC)
    cp1 = _make_checkpoint(run_id="run-A", node_id="n1", created_at=now)
    cp2 = _make_checkpoint(
        run_id="run-A", node_id="n2", created_at=now + timedelta(seconds=1)
    )
    cp_other = _make_checkpoint(run_id="run-B", node_id="n3")

    await store.save(cp1)
    await store.save(cp2)
    await store.save(cp_other)

    results = await store.list_by_run("run-A")

    assert len(results) == 2
    assert results[0].id == cp1.id
    assert results[1].id == cp2.id


async def test_list_by_run_empty(store: SQLiteCheckpointStore) -> None:
    results = await store.list_by_run("no-such-run")
    assert results == []


# ------------------------------------------------------------------
# latest_by_graph
# ------------------------------------------------------------------


async def test_latest_by_graph_returns_most_recent(
    store: SQLiteCheckpointStore,
) -> None:
    now = datetime.now(UTC)
    cp_old = _make_checkpoint(
        graph_id="g1", run_id="r1", created_at=now - timedelta(seconds=10)
    )
    cp_new = _make_checkpoint(
        graph_id="g1", run_id="r2", created_at=now
    )
    cp_other_graph = _make_checkpoint(
        graph_id="g2", run_id="r3", created_at=now + timedelta(seconds=5)
    )

    await store.save(cp_old)
    await store.save(cp_new)
    await store.save(cp_other_graph)

    latest = await store.latest_by_graph("g1")

    assert latest is not None
    assert latest.id == cp_new.id


async def test_latest_by_graph_returns_none_when_empty(
    store: SQLiteCheckpointStore,
) -> None:
    result = await store.latest_by_graph("nonexistent-graph")
    assert result is None


# ------------------------------------------------------------------
# Concurrent saves via writer queue
# ------------------------------------------------------------------


async def test_concurrent_saves_do_not_crash(store: SQLiteCheckpointStore) -> None:
    """Fire many concurrent saves and verify all land in the database."""
    count = 50
    checkpoints = [
        _make_checkpoint(
            run_id="concurrent-run",
            node_id=f"node-{i}",
            state={"index": i},
        )
        for i in range(count)
    ]

    await asyncio.gather(*(store.save(cp) for cp in checkpoints))

    results = await store.list_by_run("concurrent-run")
    assert len(results) == count

    stored_ids = {r.id for r in results}
    expected_ids = {cp.id for cp in checkpoints}
    assert stored_ids == expected_ids


# ------------------------------------------------------------------
# Database auto-creation
# ------------------------------------------------------------------


async def test_auto_creates_database(tmp_path: Path) -> None:
    db_path = tmp_path / "subdir" / "deep" / "checkpoints.db"
    assert not db_path.exists()

    store = SQLiteCheckpointStore(db_path)
    try:
        cp = _make_checkpoint()
        await store.save(cp)

        assert db_path.exists()

        loaded = await store.load(cp.id)
        assert loaded.id == cp.id
    finally:
        await store.close()
