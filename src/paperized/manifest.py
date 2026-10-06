"""The manifest: Paperized's contract with whatever consumes its output.

CraftEngine's YAML is the artifact a server loads, but it is a poor interface for a
program. This manifest is the interface — it says what was served, what it cost, and why
anything is missing, without requiring the consumer to parse CraftEngine's config format.

Every deferral carries a machine-readable reason, not prose. A consumer deciding whether
to enable a family needs to distinguish "no safe carrier exists" from "another pack
claimed it" from "you asked for more than the capacity", and those call for different
responses.
"""

from __future__ import annotations

import dataclasses
import enum
import json
import pathlib
from typing import Any


class Reason(enum.Enum):
    """Why a block was not served.

    Stable identifiers — consumers may switch on these, so do not reword casually.
    Add new members rather than changing existing ones.
    """

    NO_SAFE_CARRIER = "no_safe_carrier"
    MULTIPART_UNSAFE = "multipart_unsafe"
    CLAIMED_ELSEWHERE = "claimed_elsewhere"
    CAPACITY_EXHAUSTED = "capacity_exhausted"
    NOT_SELECTED = "not_selected"
    FAMILY_DEFERRED = "family_deferred"
    UNIMPLEMENTED_BEHAVIOUR = "unimplemented_behaviour"
    VARIANT_DISABLED = "variant_disabled"


@dataclasses.dataclass(frozen=True)
class Deferred:
    """One block that was not served, and why."""

    block: str
    reason: Reason
    detail: str


@dataclasses.dataclass(frozen=True)
class Family:
    """One shape family and the carriers available to it."""

    name: str
    candidates: int
    safe_carriers: int
    capacity_states: int
    assigned_states: int

    @property
    def free_states(self) -> int:
        return max(0, self.capacity_states - self.assigned_states)

    @property
    def exhausted(self) -> bool:
        return self.assigned_states >= self.capacity_states


@dataclasses.dataclass(frozen=True)
class Manifest:
    """Everything a consumer needs to know about one build.

    Versioned from the start. This file is meant to be consumed by plugins that are not
    rebuilt in step with this generator, so additive change only.
    """

    schema: int
    mc_version: str
    blocks_served: int
    internal_states_used: int
    internal_states_max: int
    families: tuple[Family, ...]
    deferred: tuple[Deferred, ...]
    externally_claimed: dict[str, str]

    @property
    def states_free(self) -> int:
        return max(0, self.internal_states_max - self.internal_states_used)

    def deferrals(self, reason: Reason) -> tuple[Deferred, ...]:
        return tuple(d for d in self.deferred if d.reason is reason)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "mc_version": self.mc_version,
            "blocks_served": self.blocks_served,
            "internal_states": {
                "used": self.internal_states_used,
                "max": self.internal_states_max,
                "free": self.states_free,
            },
            "families": [
                {
                    "name": f.name,
                    "candidates": f.candidates,
                    "safe_carriers": f.safe_carriers,
                    "capacity_states": f.capacity_states,
                    "assigned_states": f.assigned_states,
                    "free_states": f.free_states,
                    "exhausted": f.exhausted,
                }
                for f in self.families
            ],
            "deferred": [
                {"block": d.block, "reason": d.reason.value, "detail": d.detail}
                for d in self.deferred
            ],
            "externally_claimed": self.externally_claimed,
        }

    def write(self, path: pathlib.Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), indent=2) + "\n", encoding="utf-8")
