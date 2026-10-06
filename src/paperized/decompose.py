"""Resolved model -> :class:`paperized.ir.Geometry`. One question, asked once.

    resolved model  ->  BoxDecomposer  ->  VisualGeometry

**What geometry does this resolved model describe?**

That is the entire contract, and the restrictions that make it worth having are the reason
it is a separate stage rather than a function buried in measurement:

* no family vocabulary -- it does not know slab, pillar, pane, wall, or stairs
* no carrier lookup -- no CraftEngine, no vanilla state, nothing about runtime
* no collision semantics -- these are *visual* boxes, because deciding otherwise is
  :func:`paperized.analysis.geometry.collision_from`'s job and folding the two together is
  how the pillar's two full cubes quietly become one field
* deterministic -- the same resolved model always yields the same boxes
* no merging -- boxes are reported as authored. Merging is :mod:`paperized.merge`'s problem,
  and a decomposer that also optimises cannot be checked against anything

## Rotations are applied, not ignored

The obvious implementation reads ``from``/``to`` and stops. That is wrong, and wrong
*quietly*: Farmer's Delight has 35 elements rotated by ±22.5° or ±45°, and a decomposer that
ignores ``rotation`` reports the unrotated box -- a different shape under the right name,
with no error anywhere.

Rotation is applied here, and the result is the axis-aligned bounding box of the rotated
element, which is what an axis-aligned runtime box has to be.

Angles that are multiples of 90 are handled by exact integer permutation, so the common
case stays exact and float-free. Other angles cannot be represented in integer 0..16 space
at all, so the geometry is quantised and flagged :attr:`ir.Geometry.exact` ``False`` rather
than passed off as exact.

``display`` transforms are deliberately *not* applied. They position a model for a GUI or
hand, not in the world.

## Failure is loud

An unresolvable chain, a multipart blockstate, or a model that defines no geometry at all
raises :class:`GeometryError`. It does not return an empty :class:`~paperized.ir.Geometry`,
because an empty geometry is indistinguishable downstream from a real shape -- and
"these blocks have no geometry" surfacing three stages later is the exact failure mode the
whole pipeline is arranged to prevent.

The one deliberate exception is ``minecraft:block/cube``, a model with neither elements nor
parent. That is a format fact rather than an assumption: it is what the vanilla format
defines the empty model to be, and every cube in Minecraft inherits its geometry from it.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Callable, Mapping

from .ir import FULL_BLOCK, Box, Geometry, OrientedBox

Loader = Callable[[str], Mapping | None]

MAX_DEPTH = 32

# Right-angle cos/sin, so the common case is an exact integer permutation with no float.
_EXACT_TRIG: dict[int, tuple[int, int]] = {
    0: (1, 0),
    90: (0, 1),
    180: (-1, 0),
    270: (0, -1),
    -90: (0, -1),
    -180: (-1, 0),
    -270: (0, 1),
}

AXES = ("x", "y", "z")


class GeometryError(Exception):
    """A model could not be decomposed. Always fatal, never a fallback."""


@dataclasses.dataclass(frozen=True)
class ResolvedModel:
    """A model with its parent chain already walked. What the decomposer consumes."""

    ref: str
    elements: tuple[Mapping, ...]
    chain: tuple[str, ...]
    model_rotation: Mapping | None = None

    @property
    def is_vanilla_cube(self) -> bool:
        return self.ref.split(":")[-1].split("/")[-1] == "cube" and ":" in self.ref


def _name(ref: str) -> str:
    """Strip namespace and directory: ``minecraft:block/cube`` -> ``cube``."""
    return ref.split(":")[-1].split("/")[-1]


def resolve(ref: str, load: Loader) -> ResolvedModel:
    """Walk the parent chain to the model that actually carries elements.

    An empty ``elements`` list continues to the parent rather than stopping, because
    Farmer's Delight uses empty-element models purely as indirection.
    """
    chain: list[str] = []
    current = ref

    for _ in range(MAX_DEPTH):
        chain.append(current)
        data = load(current)
        if data is None:
            raise GeometryError(
                f"model {current!r} not found (chain: {' -> '.join(chain)})"
            )

        elements = data.get("elements")
        if elements:
            return ResolvedModel(
                ref=current,
                elements=tuple(elements),
                chain=tuple(chain),
                model_rotation=data.get("rotation"),
            )

        parent = data.get("parent")
        if not parent:
            # No elements anywhere in the chain and no parent. In vanilla this is
            # `minecraft:block/cube`, and inheriting from it means inheriting a full box.
            # Any other bare model defines nothing, which is not the same as being a cube.
            if _name(current) == "cube" and ":" in current:
                return ResolvedModel(ref=current, elements=(), chain=tuple(chain))
            raise GeometryError(
                f"model {current!r} defines no geometry and is not minecraft:block/cube "
                f"(chain: {' -> '.join(chain)}). Refusing to guess a shape."
            )
        current = str(parent)

    raise GeometryError(
        f"parent chain from {ref!r} exceeded {MAX_DEPTH} links "
        f"(chain: {' -> '.join(chain)})"
    )


def _corners(box: Box) -> list[tuple[float, float, float]]:
    x0, y0, z0, x1, y1, z1 = box.as_tuple()
    return [
        (x, y, z)
        for x in (x0, x1)
        for y in (y0, y1)
        for z in (z0, z1)
    ]


def _rotate(point: tuple[float, float, float], axis: str, angle: int) -> tuple[float, float, float]:
    """Rotate ``point`` about ``axis`` through the origin.

    Kept separate from pivoting so the integer fast path stays readable: for multiples of
    90 this is a permutation of coordinates and nothing else.
    """
    x, y, z = point
    cos, sin = _EXACT_TRIG[int(angle) % 360]
    if axis == "x":
        return (x, y * cos - z * sin, y * sin + z * cos)
    if axis == "y":
        return (x * cos + z * sin, y, -x * sin + z * cos)
    if axis == "z":
        return (x * cos - y * sin, x * sin + y * cos, z)
    raise GeometryError(f"rotation axis {axis!r} is not one of {AXES}")


def _element_box(element: Mapping) -> tuple[Box | None, OrientedBox | None, bool]:
    """One element's geometry. Returns ``(box, oriented, exact)``.

    Exactly one of ``box``/``oriented`` is set. A right-angle-rotated element is still
    axis-aligned, so it stays a :class:`Box`. Anything else becomes an
    :class:`OrientedBox` rather than its axis-aligned bounds -- see the class docstring for
    why that projection is not an acceptable substitute.
    """
    frm, to = element.get("from"), element.get("to")
    if not frm or not to or len(frm) != 3 or len(to) != 3:
        raise GeometryError(f"element needs 3-value from and to, got {frm!r}/{to!r}")

    try:
        values = [float(v) for v in (*frm, *to)]
    except (TypeError, ValueError) as exc:
        raise GeometryError(f"element has a non-numeric coordinate: {frm!r}/{to!r}") from exc

    box = Box(*values)
    integral = all(v.is_integer() for v in values)
    rotation = element.get("rotation")

    if not rotation:
        return box, None, integral

    angle = float(rotation.get("angle", 0) or 0)
    axis = str(rotation.get("axis", "")).lower()
    if axis not in AXES:
        raise GeometryError(f"rotation axis {axis!r} is not one of {AXES}")

    # `rescale: true` means "rotate about the element's own centre, not about origin".
    # Vanilla implements it by translating the element so its midpoint lands on the origin
    # and then rotating. Ignoring it moves the element whenever the origin is not already
    # its centre, which is the normal case -- and the shift is silent.
    origin = [float(o) for o in (rotation.get("origin") or [8, 8, 8])]
    if rotation.get("rescale"):
        centre = [(box.as_tuple()[i] + box.as_tuple()[i + 3]) / 2 for i in range(3)]
        origin = centre

    right_angle = angle.is_integer() and int(angle) % 90 == 0
    step = int(angle) % 360 if right_angle else 0

    corners = _corners(box)
    turned: list[tuple[float, float, float]] = []
    for p in corners:
        rel = (p[0] - origin[0], p[1] - origin[1], p[2] - origin[2])
        if right_angle:
            rotated = _rotate(rel, axis, step)
        else:
            radians = math.radians(angle)
            cos, sin = math.cos(radians), math.sin(radians)
            if axis == "x":
                rotated = (rel[0], rel[1] * cos - rel[2] * sin, rel[1] * sin + rel[2] * cos)
            elif axis == "y":
                rotated = (rel[0] * cos + rel[2] * sin, rel[1], -rel[0] * sin + rel[2] * cos)
            else:
                rotated = (rel[0] * cos - rel[1] * sin, rel[0] * sin + rel[1] * cos, rel[2])
        turned.append((rotated[0] + origin[0], rotated[1] + origin[1], rotated[2] + origin[2]))

    exact = integral and all(float(v).is_integer() for p in turned for v in p)

    if right_angle:
        def q(v: float) -> int:
            return int(math.floor(v + 0.5)) if v >= 0 else -int(math.floor(-v + 0.5))

        return Box(*(q(v) for v in _axis_extent(turned))), None, exact

    return None, OrientedBox(tuple(turned), exact=exact), exact


def _axis_extent(points: list[tuple[float, float, float]]) -> list[float]:
    lo = [min(p[i] for p in points) for i in range(3)]
    hi = [max(p[i] for p in points) for i in range(3)]
    return [*lo, *hi]


def decompose(resolved: ResolvedModel) -> Geometry:
    """The canonical geometry a resolved model describes.

    Axis-aligned elements come out in :attr:`~paperized.ir.Geometry.boxes`, rotated ones in
    :attr:`~paperized.ir.Geometry.oriented`. Boxes are sorted but never de-duplicated or
    merged: two authored elements that share one bounds are two elements, and collapsing them
    turns "different shapes, same bounds" into "one shape". Merging belongs to
    :mod:`paperized.merge`, where it is one visible decision instead of a side effect.
    """
    if not resolved.elements:
        return Geometry(
            (FULL_BLOCK,),
            source="model:" + " -> ".join(resolved.chain) + " (cube)",
        )

    boxes: list[Box] = []
    oriented: list[OrientedBox] = []
    exact = True
    for element in resolved.elements:
        box, oriented_box, element_exact = _element_box(element)
        if box is not None:
            boxes.append(box)
        if oriented_box is not None:
            oriented.append(oriented_box)
        exact = exact and element_exact

    return Geometry(
        boxes=tuple(sorted(boxes, key=lambda b: b.as_tuple())),
        source="model:" + " -> ".join(resolved.chain),
        oriented=tuple(sorted(oriented, key=lambda o: o.corners)),
        exact=exact,
    )


def decompose_ref(ref: str, load: Loader) -> Geometry:
    """Convenience: resolve then decompose. Two stages, still two calls internally."""
    return decompose(resolve(ref, load))
