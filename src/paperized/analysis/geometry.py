"""Measure a mod's blockstates into IR geometry. One path, one set of types.

This module's whole job is the first arrow of the pipeline:

    source blockstate + model roots  ──▶  ir.Geometry

Everything downstream -- capabilities, families, runtime strategy -- reads what this
produces. It deliberately produces **IR types directly** rather than a parallel
representation that something else converts.

That is not tidiness. There were briefly two `Box` types and two `Capabilities` types, one
set here and one in `ir.py`. The symptom was silent in both cases: a measured visual
geometry never compared equal to a derived collision geometry, so `differs` reported `True`
for every block, including ones whose two geometries were byte-identical. Duplicate value
types break equality quietly, and the only symptom is a field that is always wrong.

The `BoxDecomposer` boundary that follows this module answers "what geometry does this
resolved model describe?" and nothing else. Deciding whether a box is *collision* is not
its job -- see `CollisionDerivation` below, and the pillar, whose visual and collision
legitimately differ.

Traps this module already handles, each of which silently reported every block as
unmeasurable until fixed:

- models split across `src/main/resources` and `src/generated/resources`
- `minecraft:block/x` needing its directory stripped, or it looks for `block/block/x.json`
- a variant value that is a *list* of models, not a dict
- property names living in the variant *key*, not a nested `properties` object
"""

from __future__ import annotations

import json
import pathlib
from typing import Mapping

from ..blockstate import BlockstateError
from ..blockstate import placements as blockstate_placements
from ..compose import CompositionError, compose, rotate
from ..decompose import GeometryError, Loader, ResolvedModel, _name, decompose, resolve
from ..ir import Box, Capabilities, FULL_BLOCK, Geometry, Properties, Property
from .shape import first_model


def boxes_from_model(resolved: ResolvedModel) -> tuple[Box, ...]:
    """Kept as the measurement path's entry point into the decomposer.

    It used to do its own element->box conversion. It no longer does, and the reason is
    worth recording: an independent second implementation disagreed with the decomposer on
    20 of Farmer's Delight's blocks, and on inspection the *decomposer* was right in every
    case. geometry.py ignored ``rotation``; FD has 35 elements rotated by +-22.5 or +-45
    degrees, so it reported unrotated boxes for them -- a different shape under the right
    name, no error.

    A second measurement path is only useful if both are correct. Keeping one that was
    quietly wrong to cross-check against would have meant two bugs to fix on the next format
    change and no earlier warning than a test someone had to write on purpose.
    """
    return decompose(resolved).boxes


def properties_from(blockstate: dict) -> Properties:
    """The declared state space, read from the variant keys.

    A resolver assuming ``variants[key]["properties"]`` finds nothing on every block.
    Only *names* are recoverable from a blockstate -- the value sets live in the mod's Java
    registration, so they are declared, not measured, and default to empty.
    """
    names: set[str] = set()
    for key in blockstate.get("variants") or {}:
        for part in str(key).split(","):
            if "=" in part:
                names.add(part.split("=", 1)[0].strip())
    return Properties(tuple(Property(n, ()) for n in sorted(names)))


def measure_blockstate(
    block: str,
    blockstate: dict,
    mod_model_roots: list[pathlib.Path],
    vanilla_models: pathlib.Path | None = None,
) -> tuple[Geometry, Properties, bool]:
    """Measure one blockstate. Returns ``(geometry, properties, multipart)``.

    The geometry is *visual*: what the model chain describes. It is not collision, and
    :func:`collision_from` decides that separately.

    Raises :class:`~paperized.decompose.GeometryError` when a model chain resolves to
    nothing. It used to return an empty box set instead, and that turned out to hide the
    single largest measurement error found so far -- see the canvas-sign note below.
    """
    if "multipart" in blockstate:
        # A multipart blockstate's geometry is the *union* of its parts. Decomposing part
        # zero and returning it as the block's geometry reports a post as if it were a wall,
        # which is the same lie as inventing a cube for a canvas sign: a partial shape that
        # looks like a complete one. Which parts apply depends on the state, so the
        # composed geometry is measure_state()'s answer, per state.
        raise GeometryError(
            f"{block}: multipart blockstate has {len(blockstate['multipart'])} parts, so it "
            f"has no one geometry; measure_state() measures it for a given state."
        )

    ref = first_model(blockstate)
    if ref is None:
        raise GeometryError(f"{block}: blockstate names no model")

    resolved = resolve(ref, _loader(mod_model_roots, vanilla_models))
    geometry = decompose(resolved)
    return geometry, properties_from(blockstate), "multipart" in blockstate


def measure_state(
    block: str,
    blockstate: dict,
    state: Mapping[str, str],
    mod_model_roots: list[pathlib.Path],
    vanilla_models: pathlib.Path | None = None,
) -> Geometry:
    """The geometry a blockstate draws for one state: variants or multipart alike.

    The pipeline, one stage per arrow, each stage its own module::

        blockstate, state  ->  placements        (paperized.blockstate)
        each model         ->  resolve, decompose (paperized.decompose)
        each geometry      ->  rotate            (paperized.compose)
        all of them        ->  compose           (paperized.compose)

    The result is the union *as authored*: overlapping and coincident boxes included,
    nothing merged. Hand it to :func:`paperized.merge.merge` for a region set.

    A random choice of models (a list ``apply``) is accepted only when every choice draws
    the same geometry once turned -- the usual case, rotated copies of a cube. If they
    differ, the block has no single shape and this raises rather than picking one.
    """
    load = _loader(mod_model_roots, vanilla_models)
    try:
        applied = blockstate_placements(blockstate, state)
    except BlockstateError as exc:
        raise GeometryError(f"{block} {dict(state)}: {exc}") from exc

    parts: list[Geometry] = []
    for placement in applied:
        choices = [rotate(decompose(resolve(m.ref, load)), m.x, m.y) for m in placement.alternatives]
        shapes = {(c.boxes, c.oriented) for c in choices}
        if len(shapes) != 1:
            raise GeometryError(
                f"{block} {dict(state)}: a random choice between "
                f"{[m.ref for m in placement.alternatives]} draws {len(shapes)} different "
                f"shapes, so the block has no single geometry"
            )
        parts.append(choices[0])
    try:
        return compose(parts)
    except CompositionError as exc:
        raise GeometryError(f"{block} {dict(state)}: {exc}") from exc


def _loader(roots: list[pathlib.Path], vanilla_models: pathlib.Path | None) -> Loader:
    """A model lookup over the mod's roots, falling back to vanilla.

    Vanilla is included because mod models routinely parent into it -- ``orientable`` and
    friends -- and those answers live in the client jar, not the mod.
    """
    search: list[pathlib.Path] = []
    for root in roots:
        if (root / "block").is_dir():
            search.append(root / "block")
        elif (root / "models" / "block").is_dir():
            search.append(root / "models" / "block")
        else:
            search.append(root)
    if vanilla_models is not None:
        search.append(vanilla_models / "block")

    def load(ref: str) -> Mapping | None:
        name = _name(ref)
        for root in search:
            candidate = root / f"{name}.json"
            if candidate.is_file():
                try:
                    return json.loads(candidate.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    return None
        return None

    return load


def collision_from(
    visual: Geometry,
    carrier: str | None = None,
    declared: Geometry | None = None,
) -> tuple[Geometry, str]:
    """Decide collision geometry, and record *why*.

    Kept separate from :func:`measure_blockstate` deliberately. The pillar is the proof
    that this cannot be folded in: its model resolves to a full cube and its carrier is a
    note block, so both are cubes here -- but for a slab the visual is 16x8x16 and there is
    no carrier at all, so the two must be allowed to differ.

    Returns ``(collision, source)`` where source is ``'carrier'``, ``'declared'`` or
    ``'visual'``. Carrying it is what lets a caller tell an intentional difference from an
    oversight.
    """
    if declared is not None:
        return declared, "declared"
    if carrier:
        # A carrier supplies collision by definition; its geometry is the vanilla state's,
        # which is not something this module measures.
        return Geometry((FULL_BLOCK,), source="carrier:" + carrier), "carrier"
    return visual, "visual"


__all__ = [
    "Box",
    "Capabilities",
    "FULL_BLOCK",
    "Geometry",
    "Properties",
    "Property",
    "boxes_from_model",
    "collision_from",
    "measure_blockstate",
    "measure_state",
    "properties_from",
]
