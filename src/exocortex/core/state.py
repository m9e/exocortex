"""Typed state management with per-field reducers for parallel branch merging."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class ReducerType(StrEnum):
    LAST_WRITE = "last_write"
    APPEND = "append"
    MERGE_DICT = "merge_dict"
    MAX = "max"
    MIN = "min"
    UNION = "union"


class FieldSpec(BaseModel):
    """Specification for a single state field."""

    field_type: str
    default: Any = None
    reducer: ReducerType | None = None
    description: str = ""


class StateSchema(BaseModel):
    """Schema definition for a graph's state. Strictly typed."""

    fields: dict[str, FieldSpec]

    def validate_state(self, state: dict[str, Any]) -> list[str]:
        """Return list of validation errors. Empty = valid."""
        errors: list[str] = []
        for name, spec in self.fields.items():
            if name not in state and spec.default is None:
                errors.append(f"Missing required field: {name}")
        for name in state:
            if name.startswith("_"):
                continue  # Internal fields like _iteration_count
            if name not in self.fields:
                errors.append(f"Unknown field: {name}")
        return errors

    def create_initial_state(self) -> dict[str, Any]:
        """Create a state dict with all defaults populated."""
        state: dict[str, Any] = {}
        for name, spec in self.fields.items():
            state[name] = deepcopy(spec.default)
        return state


class StateUpdate(BaseModel):
    """A single state modification with provenance."""

    field: str
    value: Any
    writer_node: str
    writer_agent: str | None = None
    timestamp: datetime
    revision: int


class MergeConflictError(Exception):
    """Raised when parallel branches write the same field without a reducer."""

    def __init__(self, field: str, writers: list[str]) -> None:
        self.field = field
        self.writers = writers
        super().__init__(
            f"Merge conflict on field '{field}' from nodes {writers}. "
            f"Declare a ReducerType for this field."
        )


def apply_reducer(reducer: ReducerType, current: Any, incoming: Any) -> Any:
    """Apply a reducer to merge two values."""
    match reducer:
        case ReducerType.LAST_WRITE:
            return incoming
        case ReducerType.APPEND:
            if not isinstance(current, list):
                current = [] if current is None else [current]
            if isinstance(incoming, list):
                return current + incoming
            return current + [incoming]
        case ReducerType.MERGE_DICT:
            if not isinstance(current, dict):
                current = {} if current is None else current
            if not isinstance(incoming, dict):
                return current
            return {**current, **incoming}
        case ReducerType.MAX:
            if current is None:
                return incoming
            return max(current, incoming)
        case ReducerType.MIN:
            if current is None:
                return incoming
            return min(current, incoming)
        case ReducerType.UNION:
            current_set = set(current) if isinstance(current, (list, set)) else set()
            incoming_set = set(incoming) if isinstance(incoming, (list, set)) else {incoming}
            return list(current_set | incoming_set)


def merge_branch_states(
    schema: StateSchema,
    base_state: dict[str, Any],
    branch_states: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    """Merge multiple branch states back into a single state.

    Args:
        schema: The graph's state schema with reducer declarations.
        base_state: The state at the fork point.
        branch_states: List of (branch_node_id, branch_state) pairs.

    Returns:
        Merged state.

    Raises:
        MergeConflictError: If branches wrote the same field without a reducer.
    """
    if not branch_states:
        return deepcopy(base_state)

    if len(branch_states) == 1:
        return deepcopy(branch_states[0][1])

    merged = deepcopy(base_state)
    field_writers: dict[str, list[str]] = {}

    for node_id, branch_state in branch_states:
        for field, value in branch_state.items():
            if field.startswith("_"):
                merged[field] = value
                continue

            base_value = base_state.get(field)
            if value == base_value:
                continue  # No change from this branch

            if field not in field_writers:
                field_writers[field] = []
                merged[field] = value
            else:
                field_writers[field].append(node_id)
                spec = schema.fields.get(field)
                if spec is None or spec.reducer is None:
                    all_writers = field_writers[field]
                    raise MergeConflictError(field, all_writers)
                merged[field] = apply_reducer(spec.reducer, merged[field], value)

        # Track first writer
        for field, value in branch_state.items():
            if field.startswith("_"):
                continue
            base_value = base_state.get(field)
            if value != base_value and field not in field_writers:
                field_writers[field] = [node_id]

    return merged


def now_utc() -> datetime:
    return datetime.now(UTC)
