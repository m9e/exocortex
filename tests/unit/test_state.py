"""Tests for state management and reducers."""

import pytest

from exocortex.core.state import (
    FieldSpec,
    MergeConflictError,
    ReducerType,
    StateSchema,
    apply_reducer,
    merge_branch_states,
)


class TestStateSchema:
    def test_create_initial_state(self):
        schema = StateSchema(fields={
            "query": FieldSpec(field_type="str", default=""),
            "results": FieldSpec(field_type="list", default=[]),
            "score": FieldSpec(field_type="float", default=0.0),
        })
        state = schema.create_initial_state()
        assert state == {"query": "", "results": [], "score": 0.0}

    def test_initial_state_deep_copies_defaults(self):
        schema = StateSchema(fields={
            "items": FieldSpec(field_type="list", default=[]),
        })
        s1 = schema.create_initial_state()
        s2 = schema.create_initial_state()
        s1["items"].append("x")
        assert s2["items"] == []

    def test_validate_state_valid(self):
        schema = StateSchema(fields={
            "query": FieldSpec(field_type="str", default=""),
        })
        errors = schema.validate_state({"query": "hello"})
        assert errors == []

    def test_validate_state_missing_required(self):
        schema = StateSchema(fields={
            "query": FieldSpec(field_type="str"),  # No default = required
        })
        errors = schema.validate_state({})
        assert len(errors) == 1
        assert "Missing required field" in errors[0]

    def test_validate_state_unknown_field(self):
        schema = StateSchema(fields={
            "query": FieldSpec(field_type="str", default=""),
        })
        errors = schema.validate_state({"query": "hi", "extra": "bad"})
        assert len(errors) == 1
        assert "Unknown field" in errors[0]

    def test_validate_state_ignores_internal_fields(self):
        schema = StateSchema(fields={
            "query": FieldSpec(field_type="str", default=""),
        })
        errors = schema.validate_state({"query": "hi", "_iteration_count": 3})
        assert errors == []


class TestApplyReducer:
    def test_last_write(self):
        assert apply_reducer(ReducerType.LAST_WRITE, "old", "new") == "new"

    def test_append_lists(self):
        assert apply_reducer(ReducerType.APPEND, [1, 2], [3, 4]) == [1, 2, 3, 4]

    def test_append_single(self):
        assert apply_reducer(ReducerType.APPEND, [1], 2) == [1, 2]

    def test_append_to_none(self):
        assert apply_reducer(ReducerType.APPEND, None, [1]) == [1]

    def test_merge_dict(self):
        result = apply_reducer(ReducerType.MERGE_DICT, {"a": 1}, {"b": 2})
        assert result == {"a": 1, "b": 2}

    def test_merge_dict_overwrites(self):
        result = apply_reducer(ReducerType.MERGE_DICT, {"a": 1}, {"a": 2})
        assert result == {"a": 2}

    def test_max(self):
        assert apply_reducer(ReducerType.MAX, 3, 7) == 7
        assert apply_reducer(ReducerType.MAX, 7, 3) == 7

    def test_max_none_current(self):
        assert apply_reducer(ReducerType.MAX, None, 5) == 5

    def test_min(self):
        assert apply_reducer(ReducerType.MIN, 3, 7) == 3

    def test_union(self):
        result = apply_reducer(ReducerType.UNION, [1, 2], [2, 3])
        assert set(result) == {1, 2, 3}


class TestMergeBranchStates:
    def _schema(self, **field_reducers: ReducerType | None) -> StateSchema:
        return StateSchema(fields={
            name: FieldSpec(field_type="any", default=None, reducer=reducer)
            for name, reducer in field_reducers.items()
        })

    def test_empty_branches(self):
        schema = self._schema(x=None)
        result = merge_branch_states(schema, {"x": 1}, [])
        assert result == {"x": 1}

    def test_single_branch(self):
        schema = self._schema(x=None)
        result = merge_branch_states(schema, {"x": 1}, [("a", {"x": 2})])
        assert result == {"x": 2}

    def test_two_branches_no_conflict(self):
        schema = self._schema(x=None, y=None)
        result = merge_branch_states(
            schema,
            {"x": 0, "y": 0},
            [("a", {"x": 1, "y": 0}), ("b", {"x": 0, "y": 2})],
        )
        assert result == {"x": 1, "y": 2}

    def test_two_branches_conflict_raises(self):
        schema = self._schema(x=None)  # No reducer!
        with pytest.raises(MergeConflictError) as exc_info:
            merge_branch_states(
                schema,
                {"x": 0},
                [("a", {"x": 1}), ("b", {"x": 2})],
            )
        assert exc_info.value.field == "x"

    def test_two_branches_with_append_reducer(self):
        schema = self._schema(items=ReducerType.APPEND)
        result = merge_branch_states(
            schema,
            {"items": []},
            [("a", {"items": ["x"]}), ("b", {"items": ["y"]})],
        )
        assert set(result["items"]) == {"x", "y"}

    def test_two_branches_with_max_reducer(self):
        schema = self._schema(score=ReducerType.MAX)
        result = merge_branch_states(
            schema,
            {"score": 0},
            [("a", {"score": 5}), ("b", {"score": 3})],
        )
        assert result["score"] == 5

    def test_internal_fields_pass_through(self):
        schema = self._schema(x=None)
        result = merge_branch_states(
            schema,
            {"x": 0, "_iter": 0},
            [("a", {"x": 1, "_iter": 3})],
        )
        assert result["_iter"] == 3
