"""Placed geometries -> one geometry. Union, and nothing else.

    decomposed geometry x N  ->  rotate  ->  GeometryComposer  ->  geometry  ->  BoxMerger

Two operations, both exact and neither an optimisation:

* :func:`rotate` -- turn one geometry by a blockstate's ``x`` and ``y``, right angles only.
  It is a coordinate permutation about the block centre: every box stays a box, the count
  is unchanged, and nothing is merged, dropped or clipped.
* :func:`compose` -- the union of several geometries, **as a list**: every box of every
  input, in order, then sorted. Coincident boxes stay coincident; overlapping boxes stay
  overlapping; nothing is de-duplicated.

**Composition does not merge.** A wall's post and its arms overlap, and a pane's post
coincides with four ``noside`` boxes. Deciding how to represent that space is
:mod:`paperized.merge`'s one job, and a composer that also tidied up would be a second
place that changes geometry -- one that could quietly disagree with the first.

No blockstate knowledge either: which models apply, and with which rotation, is
:mod:`paperized.blockstate`'s question. This module sees geometries and angles.

## Rotation, as the format defines it

A blockstate turns a model about the block centre ``(8, 8, 8)``: ``x`` first, then ``y``,
each clockwise looking down its axis toward the origin, in steps of 90.

* ``y: 90`` takes north to east: ``(x, z) -> (16 - z, x)``. A stair model faces east, and
  ``facing=south`` is ``y: 90``.
* ``x: 90`` takes the model's top to north and its bottom to south:
  ``(y, z) -> (z, 16 - y)``. A floor button (``5,0,6 -> 11,2,10``) turned ``x: 90`` becomes
  ``5,6,14 -> 11,10,16``, which is the game's own shape for a button facing north.
"""

from __future__ import annotations

from typing import Iterable

from .ir import Box, Geometry, OrientedBox

SIZE = 16


class CompositionError(Exception):
    """Geometries cannot be composed or turned. Always fatal, never a fallback."""


def rotate(geometry: Geometry, x: int = 0, y: int = 0) -> Geometry:
    """``geometry`` turned by a blockstate's ``x`` then ``y``, in right angles."""
    for axis, angle in (("x", x), ("y", y)):
        if angle % 90:
            raise CompositionError(f"{axis} rotation {angle} is not a right angle")
    if not x % 360 and not y % 360:
        return geometry

    def point(p: tuple[float, float, float]) -> tuple[float, float, float]:
        px, py, pz = p
        for _ in range((x // 90) % 4):
            py, pz = pz, SIZE - py
        for _ in range((y // 90) % 4):
            px, pz = SIZE - pz, px
        return (px, py, pz)

    def box(b: Box) -> Box:
        x0, y0, z0, x1, y1, z1 = b.as_tuple()
        a, c = point((x0, y0, z0)), point((x1, y1, z1))
        # Box normalises an inverted pair, so the turned corners can go in as they come.
        return Box(*a, *c)

    def oriented(o: OrientedBox) -> OrientedBox:
        return OrientedBox(tuple(point(c) for c in o.corners), exact=o.exact)

    turn = f"x={x % 360},y={y % 360}"
    return Geometry(
        boxes=tuple(sorted((box(b) for b in geometry.boxes), key=Box.as_tuple)),
        source=f"{geometry.source} @{turn}",
        oriented=tuple(sorted((oriented(o) for o in geometry.oriented), key=lambda o: o.corners)),
        exact=geometry.exact,
    )


def compose(geometries: Iterable[Geometry]) -> Geometry:
    """Every box of every geometry, in one geometry. The union, kept as a list.

    Raises on no geometries at all: an empty union is indistinguishable downstream from a
    shape that genuinely occupies nothing, and "this state draws no models" is something
    the caller should hear about, not infer.
    """
    parts = list(geometries)
    if not parts:
        raise CompositionError("nothing to compose: no part applies")
    for part in parts:
        if not part.resolved and not part.oriented:
            raise CompositionError(f"part {part.source!r} has no geometry")
    return Geometry(
        boxes=tuple(sorted((b for p in parts for b in p.boxes), key=Box.as_tuple)),
        source=" + ".join(p.source for p in parts),
        oriented=tuple(sorted((o for p in parts for o in p.oriented), key=lambda o: o.corners)),
        exact=all(p.exact for p in parts),
    )


__all__ = ["CompositionError", "compose", "rotate"]
