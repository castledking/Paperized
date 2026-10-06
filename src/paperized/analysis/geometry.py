"""Normalized collision geometry: boxes, plus the capabilities derivable from them.

This is the primitive the rest of the compiler keys on, and the reason is measured rather
than assumed. Clustering Farmer's Delight's 132 blocks showed the family set is a power
law, not a taxonomy -- 92 blocks are one geometry, and the remaining 40 are 21 distinct
geometries of which 17 are singletons. A family list would need an entry per singleton,
which is a lookup table wearing a taxonomy's clothes.

So a block is described by boxes. "Wall" and "bespoke" are interpretations of boxes, not
the thing anything depends on.

Coordinates are normalised to a 0..16 model space and kept as ints where the source is
integral, because CraftEngine's scaled-shulker hitboxes are placed in exactly this space
and a float here becomes a sub-tile misalignment that is invisible until someone walks
into it.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib

from .shape import Geometry, Shape, classify, first_model


@dataclasses.dataclass(frozen=True)
class Box:
    """One axis-aligned cuboid, normalised to 0..16."""

    x0: int
    y0: int
    z0: int
    x1: int
    y1: int
    z1: int

    @property
    def width(self) -> int:
        return self.x1 - self.x0

    @property
    def height(self) -> int:
        return self.y1 - self.y0

    @property
    def depth(self) -> int:
        return self.z1 - self.z0

    def as_tuple(self) -> tuple[int, ...]:
        return (self.x0, self.y0, self.z0, self.x1, self.y1, self.z1)

    def to_json(self) -> dict:
        return {"min": [self.x0, self.y0, self.z0], "max": [self.x1, self.y1, self.z1]}


FULL_BLOCK = Box(0, 0, 0, 16, 16, 16)


@dataclasses.dataclass(frozen=True)
class Capabilities:
    """What a box set implies, derived rather than declared.

    Every field here is a *measurement*. None of it names a Minecraft family, which is
    the point: a caller can decide that "thin on one axis and full height" means a pane
    without this module having an opinion about panes.

    ``full_footprint`` is the measured answer, carried on the record rather than
    recomputed. It used to be a property that compared ``box_count == 1`` against a
    constant without looking at the box at all, which reported a bottom slab -- a single
    0,0,0..16,8,16 box -- as a full cube. Every slab in CMB measured as a cube because
    of it. Anything that answers "is this a full cube" from a count instead of from the
    geometry will do this.
    """

    box_count: int
    full_height: bool
    full_footprint: bool
    """One box filling all of 0..16 on all three axes."""
    full_width_or_depth: bool
    thin_axis: str | None
    """Which axis is thin, or None. A pane is thin on one horizontal axis."""
    grounded: bool
    """Touches y=0."""
    symmetric_y: bool
    """Mirrors about mid-height. True for most decor, false for ground-planted crops."""

    @property
    def is_single_box(self) -> bool:
        return self.box_count == 1

    @property
    def is_full_cube(self) -> bool:
        return self.full_footprint


def boxes_from_geometry(geometry: Geometry) -> tuple[Box, ...]:
    """The collision boxes a measured geometry implies.

    ``INHERITS`` resolves to a full block, because that is what a model with neither
    elements nor a parent inherits from ``minecraft:block/cube``. ``UNKNOWN`` yields
    nothing rather than a guess -- a wrong box is worse than no box, since an empty set
    has to be reported and a plausible one does not.
    """
    if geometry.shape is Shape.FULL_CUBE:
        return (FULL_BLOCK,)
    if geometry.shape is Shape.INHERITS:
        return (FULL_BLOCK,)
    if geometry.shape is Shape.UNKNOWN:
        return ()
    boxes: list[Box] = []
    for element in geometry.elements:
        frm = element.get("from")
        to = element.get("to")
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
            # A non-numeric element is malformed. Drop it rather than guess; the count
            # then differs from the source and the caller can see something is off.
            continue
    return tuple(sorted(boxes, key=lambda b: b.as_tuple()))


def capabilities(boxes: tuple[Box, ...]) -> Capabilities:
    if not boxes:
        return Capabilities(0, False, False, False, None, False, False)
    if len(boxes) == 1 and boxes[0].as_tuple() == FULL_BLOCK.as_tuple():
        return Capabilities(1, True, True, True, None, True, True)

    full_height = any(b.y0 <= 0 and b.y1 >= 16 for b in boxes)
    grounded = any(b.y0 <= 0 for b in boxes)

    min_x = min(b.x0 for b in boxes)
    max_x = max(b.x1 for b in boxes)
    min_y = min(b.y0 for b in boxes)
    max_y = max(b.y1 for b in boxes)
    min_z = min(b.z0 for b in boxes)
    max_z = max(b.z1 for b in boxes)

    # "Thin" is relative to the shape's own span, not an absolute 2/16. A cabinet that is
    # 14 wide and 16 deep is not a pane; a plate that is 16 by 2 is.
    span_x = max_x - min_x
    span_z = max_z - min_z
    threshold = 4
    thin_x = span_x <= threshold
    thin_z = span_z <= threshold
    thin_axis = "x" if thin_x and not thin_z else ("z" if thin_z and not thin_x else None)

    full_width_or_depth = (span_x >= 16 or span_z >= 16) and not (thin_x and thin_z)

    ys = tuple(b.as_tuple()[1::3] for b in boxes)
    symmetric = all(
        sorted({b.y0 for b in boxes}) == sorted({16 - b.y1 for b in boxes})
        for _ in (0,)
    ) and len({b.y0 for b in boxes}) == len({b.y1 for b in boxes}) or len(boxes) == 1

    return Capabilities(
        box_count=len(boxes),
        full_height=full_height,
        full_footprint=False,
        full_width_or_depth=full_width_or_depth,
        thin_axis=thin_axis,
        grounded=grounded,
        symmetric_y=bool(symmetric),
    )


@dataclasses.dataclass(frozen=True)
class Measured:
    """A block's geometry, measured and normalised. The IR's input."""

    block: str
    properties: tuple[str, ...]
    boxes: tuple[Box, ...]
    caps: Capabilities
    multipart: bool
    resolved: bool

    def to_json(self) -> dict:
        return {
            "block": self.block,
            "properties": list(self.properties),
            "collision": {
                "boxes": [b.to_json() for b in self.boxes],
                "box_count": self.caps.box_count,
            },
            "capabilities": {
                "full_height": self.caps.full_height,
                "thin_axis": self.caps.thin_axis,
                "grounded": self.caps.grounded,
                "symmetric_y": self.caps.symmetric_y,
                "full_width_or_depth": self.caps.full_width_or_depth,
            },
            "multipart": self.multipart,
            "resolved": self.resolved,
        }


def properties_of(blockstate: dict) -> tuple[str, ...]:
    """Property names, which live in the variant *key*, not a nested object.

    That is the fourth trap from the FD probe: a resolver assuming
    ``variants[key]["properties"]`` finds nothing on every block. It is right here so the
    next extractor does not rediscover it.
    """
    names: set[str] = set()
    for key in blockstate.get("variants") or {}:
        for part in str(key).split(","):
            if "=" in part:
                names.add(part.split("=", 1)[0].strip())
    if "multipart" in blockstate:
        names.add("multipart")
    return tuple(sorted(names))


def measure(
    block: str,
    blockstate: dict,
    mod_model_roots: list[pathlib.Path],
    vanilla_models: pathlib.Path | None = None,
) -> Measured:
    geometry = classify(block, first_model(blockstate), mod_model_roots, vanilla_models)
    boxes = boxes_from_geometry(geometry)
    return Measured(
        block=block,
        properties=properties_of(blockstate),
        boxes=boxes,
        caps=capabilities(boxes),
        multipart="multipart" in blockstate,
        resolved=geometry.resolved,
    )
