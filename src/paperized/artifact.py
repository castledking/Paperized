"""The compiled artifact: a versioned package a runtime backend can read.

    Paperized compiler ──▶ paperized package ──▶ any backend

A backend that can read JSON can consume Paperized's output. That is the entire point, and
it is why the package is the contract rather than the Python API: CraftEngine, a Paper
plugin and a future Paperized Server all have to read it, and none of them should have to
import this compiler or inherit its internals.

## Geometry lives per state, not per block

Farmer's Delight's stuffed pumpkin is 12 flat states and 8 taller ones, so the same block
compiles under two different collision policies. A ``block -> collision`` shape cannot
represent that, and getting it wrong is not a schema nit: the compiler once reported that
block as ``none`` at 36 cubes, reading as free while eight states cost 36 entities each.

So the authoritative unit is

    block -> states[] -> { visual, collision }

and anything block-level -- the set of policies used, whether it is mixed, the worst
state's cost -- lives under ``derived`` and is explicitly reported rather than stored.

## Nothing backend-specific is in here

No shulker, no furniture, no CraftEngine, no carrier, no note block. Collision is a list of
axis-aligned cubes and nothing more; what a runtime hangs off a cube is that runtime's
business. The artifact says ``cubes: 4``, never ``shulkers: 4``, which is precisely what
lets one compiled package feed three backends that place collision differently.

Asserted against this module's AST in the tests, because the vocabulary leaks in through
prose long before anyone decides to add it.

## Nothing is silently dropped

A state that could not be compiled is present with a ``status`` saying why -- ``no-geometry``
(the source model describes no geometry), ``undecided`` (the policy table did not decide),
or ``refused`` (a policy was chosen and cannot be represented). 68 of Farmer's Delight's 132
blockstates are the first case, and a package that omitted them would look identical to one
that never saw them.
"""

from __future__ import annotations

import json
import pathlib
import shutil
from typing import Any, Iterable, Mapping

from .compile import BlockPlan
from .ir import Box, Geometry
from .tile import Cube

#: Bumped on any incompatible change. A backend reads this first and refuses what it does
#: not understand, which is cheaper than misreading a field that changed meaning.
FORMAT = "paperized"
VERSION = 1

#: Why a state has no geometry. Descriptive strings, not enums a backend must import.
COMPILED = "compiled"
NO_GEOMETRY = "no-geometry"
UNDECIDED = "undecided"
REFUSED = "refused"


class ArtifactError(Exception):
    """The package cannot be written or read. Always fatal."""


def cube_json(cube: Cube) -> dict[str, list[float]]:
    """A cube as min and max corners.

    Derived with the tiler's exact addition rather than ``x + side``, because that is the
    whole reason the tiler has an ``as_box``: in floats 6.02 + 1.02 is 7.039999..., which
    leaves a gap before a neighbour at 7.04. Serialising the side and letting the backend
    add it would move that bug to the far side of the boundary.
    """
    box = cube.as_box()
    return {"min": [_n(v) for v in box.as_tuple()[:3]],
            "max": [_n(v) for v in box.as_tuple()[3:]]}


def _n(value: float) -> float | int:
    return int(value) if float(value).is_integer() else value


def geometry_json(geometry: Geometry) -> dict[str, Any]:
    return {
        "boxes": [[_n(c) for c in b.as_tuple()] for b in geometry.boxes],
        "oriented": [{"corners": [[_n(c) for c in corner] for corner in o.corners],
                      "exact": o.exact} for o in geometry.oriented],
        "exact": geometry.exact,
    }


def state_json(state) -> dict[str, Any]:
    """One enumerated state: what it draws, and what it collides with.

    ``visual`` is what the model draws. ``collision`` is what was chosen *and representable*,
    so a state either has both or has a status explaining why it has neither.
    """
    entry: dict[str, Any] = {
        "state": {k: v for k, v in state.state},
        "status": COMPILED,
    }
    if state.chosen is None:
        entry["status"] = _status(state)
        # A code and a note, never prose alone. manifest.py's rule, and it matters here:
        # a backend has to tell "this state draws nothing" from "this state cannot be
        # represented" without parsing an English sentence, and the raw refusal embeds the
        # block name and the whole state dict in front of the reason.
        entry["reason"] = _reason(state)
        entry["note"] = _clean(state)
        return entry
    entry["visual"] = geometry_json(state.geometry)
    entry["collision"] = {
        "policy": state.chosen.policy.value,
        # Taken from the compilation, not re-tiled here: a package must not be able to
        # disagree with the run that produced it.
        "cubes": [cube_json(c) for c in state.tiled],
        "cut": state.chosen.cut,
        "exact": state.geometry.exact,
    }
    if state.chosen.left_out:
        # Parts with no axis-aligned volume, counted rather than hidden.
        entry["collision"]["left_out"] = state.chosen.left_out
    return entry


#: Machine-readable reasons, matched on the refusal text. A backend switches on these and
#: shows the note to a human.
REASONS = {
    "no-part-applies": "no-part-applies",
    "nothing to compose": "no-part-applies",
    "defines no geometry": "no-geometry",
    "textures only": "no-geometry",
    "model chain broken": "model-chain-broken",
    "thinner than the smallest cube": "too-thin",
    "zero-volume": "too-thin",
    "will not tile": "not-tileable",
    "parent chain too deep": "cyclic-chain",
}


def _reason(state) -> str:
    text = (state.refusal or "").lower()
    for needle, code in REASONS.items():
        if needle in text:
            return code
    return "not-decided" if state.refusal is None else "unrepresentable"


def _clean(state) -> str:
    """The refusal without the block name and state dict the compose stage prefixes."""
    note = state.refusal or "the policy table did not decide this state"
    # Split on the "}: " that ends the state dict, not on the first ": " -- the dict is full
    # of them, so partitioning on the colon lands inside `{'east': '<unmentioned>'...}`.
    _, marker, tail = note.rpartition("}: ")
    return tail if marker and tail else note


def _status(state) -> str:
    if state.refusal and "no geometry" in state.refusal:
        return NO_GEOMETRY
    if state.refusal and "textures only" in state.refusal:
        return NO_GEOMETRY
    if state.refusal:
        return REFUSED
    return UNDECIDED


def block_json(plan: BlockPlan) -> dict[str, Any]:
    """One block. ``states`` is authoritative; ``derived`` is reporting."""
    names: list[str] = []
    for state in plan.states:
        for key, value in state.state:
            if key not in names:
                names.append(key)
    document: dict[str, Any] = {
        "properties": names,
        "states": [state_json(s) for s in plan.states],
    }
    # Derived, and labelled: a backend must read `states`, never this. It exists so a
    # consumer can ask "how bad is this block" without walking every state, and so the
    # mixed-policy case is visible rather than inferred.
    document["derived"] = {
        "state_count": len(plan.states),
        "compiled": sum(1 for s in plan.states if s.decided),
        "policies": [p.value for p in plan.policies],
        "mixed": plan.mixed,
        "cubes_worst": plan.cubes,
    }
    if plan.note:
        document["derived"]["note"] = plan.note
    return document


def definitions_json(plans: Iterable[BlockPlan], namespace: str,
                     source: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The whole package's definitions, in the versioned envelope."""
    blocks = {f"{namespace}:{p.id}": block_json(p) for p in sorted(plans, key=lambda p: p.id)}
    statuses: dict[str, int] = {}
    for document in blocks.values():
        for state in document["states"]:
            statuses[state["status"]] = statuses.get(state["status"], 0) + 1
    return {
        "format": FORMAT,
        "version": VERSION,
        "source": {"namespace": namespace, **dict(source or {})},
        "blocks": blocks,
        "summary": {
            "blocks": len(blocks),
            "states": sum(len(d["states"]) for d in blocks.values()),
            "statuses": dict(sorted(statuses.items())),
        },
    }


def package_json(definitions: Mapping[str, Any]) -> dict[str, Any]:
    """The small index a backend reads first: what this is, and what is in it."""
    return {
        "format": definitions["format"],
        "version": definitions["version"],
        "source": definitions["source"],
        "files": {
            "definitions": "definitions.json",
            "assets": "assets",
        },
        "summary": definitions["summary"],
    }


def write_package(
    out: pathlib.Path,
    plans: Iterable[BlockPlan],
    namespace: str,
    asset_dirs: list[pathlib.Path] | None = None,
    source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write ``manifest.json``, ``definitions.json`` and ``assets/``.

    The split is deliberate. The JSON says what exists and how it behaves; the asset
    directory holds the payload. A backend that only wants collision reads the definitions
    and never touches the textures.
    """
    definitions = definitions_json(plans, namespace, source)
    out.mkdir(parents=True, exist_ok=True)
    (out / "definitions.json").write_text(
        json.dumps(definitions, indent=2) + "\n", encoding="utf-8")
    (out / "manifest.json").write_text(
        json.dumps(package_json(definitions), indent=2) + "\n", encoding="utf-8")

    assets = out / "assets" / namespace
    written = 0
    for root in asset_dirs or []:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            target = assets / path.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            written += 1
    return {
        "definitions": definitions,
        "manifest": package_json(definitions),
        "asset_files": written,
    }


def read_package(path: pathlib.Path) -> dict[str, Any]:
    """Read a package, refusing a version this build does not understand.

    Refusing beats misreading: a ``version`` that changed the meaning of a field would
    otherwise produce a backend that loads and then places things wrongly.
    """
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        raise ArtifactError(f"{path} has no manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != FORMAT:
        raise ArtifactError(f"{path} is not a {FORMAT} package")
    if manifest.get("version") != VERSION:
        raise ArtifactError(
            f"{path} is version {manifest.get('version')}, this build reads version {VERSION}"
        )
    definitions = json.loads((path / "definitions.json").read_text(encoding="utf-8"))
    return {"manifest": manifest, "definitions": definitions}


__all__ = [
    "ArtifactError",
    "FORMAT",
    "VERSION",
    "block_json",
    "cube_json",
    "definitions_json",
    "package_json",
    "read_package",
    "write_package",
]