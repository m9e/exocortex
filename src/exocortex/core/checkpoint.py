"""Checkpoint storage with SQLite backend.

Implements the CheckpointStore protocol from the architecture spec (section 2.2)
using aiosqlite with WAL mode and a single writer queue (section 5.1).

All writes are funneled through a background asyncio task to prevent
'database is locked' contention. Reads are concurrent via WAL mode.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite
from pydantic import BaseModel, Field


class StateUpdate(BaseModel):
    """A single state modification with provenance."""

    field: str
    value: Any
    writer_node: str
    writer_agent: str | None = None
    timestamp: datetime
    revision: int


class Checkpoint(BaseModel):
    """Snapshot of graph state at a node boundary."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    graph_id: str
    run_id: str
    node_id: str
    state: dict[str, Any]
    state_patches: list[StateUpdate] = []
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    parent_id: str | None = None


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS checkpoints (
    id TEXT PRIMARY KEY,
    graph_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    state TEXT NOT NULL,
    state_patches TEXT NOT NULL,
    created_at TEXT NOT NULL,
    parent_id TEXT
);
"""

_CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_checkpoints_run_id ON checkpoints (run_id);",
    "CREATE INDEX IF NOT EXISTS idx_checkpoints_graph_id_created"
    " ON checkpoints (graph_id, created_at);",
]

_INSERT_SQL = """
INSERT INTO checkpoints (id, graph_id, run_id, node_id, state, state_patches, created_at, parent_id)
VALUES (?, ?, ?, ?, ?, ?, ?, ?);
"""

_SELECT_BY_ID_SQL = "SELECT * FROM checkpoints WHERE id = ?;"

_SELECT_BY_RUN_SQL = "SELECT * FROM checkpoints WHERE run_id = ? ORDER BY created_at;"

_SELECT_LATEST_BY_GRAPH_SQL = (
    "SELECT * FROM checkpoints WHERE graph_id = ? ORDER BY created_at DESC LIMIT 1;"
)


def _row_to_checkpoint(row: aiosqlite.Row) -> Checkpoint:
    """Convert a database row to a Checkpoint model."""
    return Checkpoint(
        id=row[0],
        graph_id=row[1],
        run_id=row[2],
        node_id=row[3],
        state=json.loads(row[4]),
        state_patches=[StateUpdate.model_validate(p) for p in json.loads(row[5])],
        created_at=datetime.fromisoformat(row[6]),
        parent_id=row[7],
    )


class SQLiteCheckpointStore:
    """SQLite-backed checkpoint storage with single writer queue.

    Uses WAL mode for concurrent reads and funnels all writes through
    a single background task via an asyncio.Queue to avoid contention.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._write_queue: asyncio.Queue[tuple[Checkpoint, asyncio.Future[None]]] = asyncio.Queue()
        self._writer_task: asyncio.Task[None] | None = None
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def _ensure_initialized(self) -> None:
        """Create the database, table, and indexes on first use."""
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            async with aiosqlite.connect(str(self._db_path)) as db:
                await db.execute("PRAGMA journal_mode=WAL;")
                await db.execute(_CREATE_TABLE_SQL)
                for idx_sql in _CREATE_INDEXES_SQL:
                    await db.execute(idx_sql)
                await db.commit()
            self._writer_task = asyncio.get_running_loop().create_task(self._writer_loop())
            self._initialized = True

    async def _writer_loop(self) -> None:
        """Background task that processes all writes sequentially."""
        while True:
            checkpoint, future = await self._write_queue.get()
            try:
                async with aiosqlite.connect(str(self._db_path)) as db:
                    await db.execute("PRAGMA journal_mode=WAL;")
                    await db.execute(
                        _INSERT_SQL,
                        (
                            checkpoint.id,
                            checkpoint.graph_id,
                            checkpoint.run_id,
                            checkpoint.node_id,
                            json.dumps(checkpoint.state),
                            json.dumps(
                                [p.model_dump(mode="json") for p in checkpoint.state_patches]
                            ),
                            checkpoint.created_at.isoformat(),
                            checkpoint.parent_id,
                        ),
                    )
                    await db.commit()
                future.set_result(None)
            except Exception as exc:
                future.set_exception(exc)
            finally:
                self._write_queue.task_done()

    async def save(self, checkpoint: Checkpoint) -> None:
        """Enqueue a checkpoint for writing. Awaits until the write completes."""
        await self._ensure_initialized()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()
        await self._write_queue.put((checkpoint, future))
        await future

    async def load(self, checkpoint_id: str) -> Checkpoint:
        """Load a checkpoint by its id. Raises KeyError if not found."""
        await self._ensure_initialized()
        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.execute("PRAGMA journal_mode=WAL;")
            cursor = await db.execute(_SELECT_BY_ID_SQL, (checkpoint_id,))
            row = await cursor.fetchone()
        if row is None:
            raise KeyError(f"Checkpoint not found: {checkpoint_id}")
        return _row_to_checkpoint(row)

    async def list_by_run(self, run_id: str) -> list[Checkpoint]:
        """List all checkpoints for a given run, ordered by created_at."""
        await self._ensure_initialized()
        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.execute("PRAGMA journal_mode=WAL;")
            cursor = await db.execute(_SELECT_BY_RUN_SQL, (run_id,))
            rows = await cursor.fetchall()
        return [_row_to_checkpoint(row) for row in rows]

    async def latest_by_graph(self, graph_id: str) -> Checkpoint | None:
        """Return the most recent checkpoint for a graph, or None."""
        await self._ensure_initialized()
        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.execute("PRAGMA journal_mode=WAL;")
            cursor = await db.execute(_SELECT_LATEST_BY_GRAPH_SQL, (graph_id,))
            row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_checkpoint(row)

    async def close(self) -> None:
        """Drain the write queue and cancel the writer task."""
        if self._writer_task is not None:
            await self._write_queue.join()
            self._writer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._writer_task
            self._writer_task = None
            self._initialized = False
