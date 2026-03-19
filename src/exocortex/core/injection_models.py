"""Pydantic v2 models for the injection/hook system.

Defines forced and opt-in injections, hook specs, injection phases,
and failure policies.
"""

from datetime import timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class InjectionPhase(StrEnum):
    """When an injection runs relative to node execution."""

    PRE = "pre"
    POST = "post"
    ON_MUTATION = "on_mutation"


class FailurePolicy(StrEnum):
    """What to do when a hook or map item fails."""

    ABORT = "abort"
    WARN = "warn"
    RETRY = "retry"
    QUARANTINE = "quarantine"


# ---------------------------------------------------------------------------
# Hook spec (used by NodeSpec for per-node hooks)
# ---------------------------------------------------------------------------


class HookSpec(BaseModel):
    """Reference to a hook that a node opts into."""

    model_config = ConfigDict(strict=True)

    name: str
    handler: str
    timeout: timedelta = timedelta(seconds=30)
    on_failure: FailurePolicy = FailurePolicy.ABORT


# ---------------------------------------------------------------------------
# Forced injections (every node, cannot be bypassed)
# ---------------------------------------------------------------------------


class ForcedInjection(BaseModel):
    """A hook that every node must run. Cannot be bypassed."""

    model_config = ConfigDict(strict=True)

    name: str
    phase: InjectionPhase
    handler: str
    timeout: timedelta = timedelta(seconds=30)
    on_failure: FailurePolicy = FailurePolicy.ABORT


# ---------------------------------------------------------------------------
# Opt-in injections (available via capability grants)
# ---------------------------------------------------------------------------


class OptInInjection(BaseModel):
    """A capability available to nodes that request it."""

    model_config = ConfigDict(strict=True)

    name: str
    capability: str
    handler: str
    description: str
