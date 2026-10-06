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

from ..ir import Box, Capabilities, FULL_BLOCK, Geometry, Properties, Property
from .shape import Geometry as MeasuredShape
from .shape import Shape, classify, first_model


def boxes_from_model(shape: MeasuredShape) -> tuple[Box, ...]:
    """The cuboids a resolved model describes, in 0..16 model space.

    ``INHERITS`` resolves to a full block, since that is what a model with neither elements
    nor a parent inherits from ``minecraft:block/cube``. ``UNKNOWN`` yields nothing rather
    than a guess: an empty set has to be reported, a plausible one does not.
    """
    if shape.shape is Shape.FULL_CUBE:
        return (FULL_BLOCK,)
    if shape.shape is Shape.INHERITS:
        return (FULL_BLOCK,)
    if shape.shape is Shape.UNKNOWN:
        return ()

    boxes: list[Box] = []
    for element in shape.elements:
        frm, to = element.get("from"), element.get("to")
        if not frm or not to or len(frm) != 3 or len(to) != 3:
            continue
        try:
            boxes.append(
                Box(
                    int(round(frm[0])), int(round(frm[1])), int(round(frm[2])),
                    int(round(to[0])), int(round(to[1])), int(round(to[2])),
                )
            )
        except (TypeError, ValueError):
            # A non-numeric element is malformed. Dropping it changes the box count, which
            # is visible; guessing would not be.
            continue
    return tuple(sorted(boxes, key=lambda b: b.as_tuple()))


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

    The geometry here is *visual*: what the model chain describes. It is not yet
    collision. Deciding that is :func:`collision_from`, below.
    """
    shape = classify(block, first_model(blockstate), mod_model_roots, vanilla_models)
    boxes = boxes_from_model(shape)
    geometry = Geometry(
        boxes=boxes,
        source="model:" + (shape.chain[0] if shape.chain else "none"),
    )
    return geometry, properties_from(blockstate), "multipart" in blockstate


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
    "properties_from",
]
