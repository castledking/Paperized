"""Regions -> cubes covering exactly the same space. One question, asked once.

    region set  ->  HitboxTiler  ->  cubes

**How is this geometry represented with the available primitive -- an axis-aligned cube
whose side lies within given limits?**

That is the entire contract. The primitive is described by :class:`CubeLimits` and nothing
else: the tiler does not know what will stand in for a cube at runtime, where the
geometry came from, or whether the state that drew it can occur. Reachability belongs to
the caller, upstream of :func:`paperized.analysis.geometry.measure_state`.

## The invariant

**The union of the cubes is the union of the regions: no missing space, no extra space.**
Every cube lies inside the region it was cut for, and every point of every region is in
some cube.

Cubes may **overlap**, unlike the merger's regions. That is a deliberate difference. The
merger's output is a description of space, and overlap would make its volume uncheckable.
The tiler's output is a set of things to place, where the cost is how many there are and
two overlapping cubes block exactly what their union blocks. Forbidding overlap would only
make the count worse.

The invariant is checked on every call; a violation raises :class:`TilingError` rather than
being returned.

## Optimal per region, provably

For one region with edges ``L1, L2, L3`` and shortest edge ``m``, the cover uses cubes of
side ``s = min(m, max_side)``, ``ceil(Li / s)`` along each axis, each row flush to both ends
(the last cube overlaps its neighbour when ``s`` does not divide the edge). That count is the
minimum for any cover of the region by cubes inside it:

* no cube inside the region is larger than ``s``, and a smaller cube never needs fewer per
  axis, so ``ceil(Li / s)`` per axis is achievable and no single size does better;
* for the lower bound, place ``ceil(Li / s)`` points along each axis, evenly from one end to
  the other. Neighbours are more than ``s`` apart, so no cube of side at most ``s`` holds two
  points that differ on that axis -- and the product of those counts is how many points
  need a cube each.

The tests check the bound with exactly those witness points, independently of this code.

Optimal **per region**, not across regions. A cube may not cross from one region into
another here, so how the space was cut into regions changes the count. That choice is the
caller's: merged regions or authored boxes are both valid input, since only the union
matters.

## Refusals

A region with no volume has no cube cover, and one thinner than ``min_side`` has no exact
one. Both raise. Making something thick enough to be represented is a decision about
*which geometry to represent*, and it belongs upstream where it is visible, not here as a
quiet rounding.
"""

from __future__ import annotations

import dataclasses
import itertools
import math
from fractions import Fraction
from typing import Iterable

from .ir import Box


class TilingError(Exception):
    """A region cannot be covered exactly. Always fatal, never a fallback."""


@dataclasses.dataclass(frozen=True)
class CubeLimits:
    """The primitive: an axis-aligned cube with a side in ``[min_side, max_side]``, in model units."""

    min_side: float
    max_side: float

    def __post_init__(self) -> None:
        if not 0 < self.min_side <= self.max_side:
            raise ValueError(f"cube limits need 0 < min_side <= max_side, got {self}")


@dataclasses.dataclass(frozen=True)
class Cube:
    """An axis-aligned cube: its minimum corner and its side, in model units."""

    x: float
    y: float
    z: float
    side: float

    def as_box(self) -> Box:
        """The cube as a box. The far corner is added exactly, not in floats: 6.02 + 1.02 in
        floats is 7.039999..., which leaves a gap before a neighbour starting at 7.04."""
        side = Fraction(str(self.side))
        far = [_number(Fraction(str(v)) + side) for v in (self.x, self.y, self.z)]
        return Box(self.x, self.y, self.z, *far)


def tile(regions: Iterable[Box], limits: CubeLimits) -> tuple[Cube, ...]:
    """The fewest cubes per region that cover ``regions`` exactly. Sorted, deterministic."""
    out: list[Cube] = []
    for region in sorted(regions, key=Box.as_tuple):
        out.extend(_tile_region(region, limits))
    return tuple(sorted(out, key=lambda c: (c.x, c.y, c.z, c.side)))


def count(region: Box, limits: CubeLimits) -> int:
    """How many cubes :func:`tile` uses for ``region`` -- the minimum for that region."""
    side = _side(region, limits)
    return math.prod(_runs(lo, hi, side) for lo, hi in _edges(region))


# --- one region ------------------------------------------------------------------------


def _edges(region: Box) -> list[tuple[Fraction, Fraction]]:
    t = [Fraction(str(v)) for v in region.as_tuple()]
    return [(t[a], t[a + 3]) for a in range(3)]


def _side(region: Box, limits: CubeLimits) -> Fraction:
    edges = _edges(region)
    shortest = min(hi - lo for lo, hi in edges)
    if shortest <= 0:
        raise TilingError(f"region {region.as_tuple()} has no volume, so no cube covers it")
    low, high = Fraction(str(limits.min_side)), Fraction(str(limits.max_side))
    if shortest < low:
        raise TilingError(
            f"region {region.as_tuple()} is {float(shortest)} thick, under the smallest cube "
            f"({limits.min_side}); no exact cover exists"
        )
    return min(shortest, high)


def _runs(lo: Fraction, hi: Fraction, side: Fraction) -> int:
    return math.ceil((hi - lo) / side)


def _starts(lo: Fraction, hi: Fraction, side: Fraction) -> list[Fraction]:
    """Cube positions along one edge: packed from ``lo``, the last one flush with ``hi``."""
    n = _runs(lo, hi, side)
    return [lo + i * side for i in range(n - 1)] + [hi - side]


def _number(v: Fraction) -> float:
    return int(v) if v.denominator == 1 else float(v)


def _tile_region(region: Box, limits: CubeLimits) -> list[Cube]:
    side = _side(region, limits)
    edges = _edges(region)
    axes = [_starts(lo, hi, side) for lo, hi in edges]

    # The invariant, per axis: the runs start at the region's start, end at its end, leave
    # no gap and stay inside. A product of exact 1D covers is an exact 3D cover.
    for (lo, hi), starts in zip(edges, axes):
        reach = lo
        for start in starts:
            if start < lo or start + side > hi or start > reach:
                raise TilingError(
                    f"cubes of side {side} do not cover {float(lo)}..{float(hi)} exactly "
                    f"in region {region.as_tuple()}: {[float(s) for s in starts]}"
                )
            reach = max(reach, start + side)
        if reach != hi:
            raise TilingError(f"cubes stop at {float(reach)} short of {float(hi)} in {region.as_tuple()}")

    return [Cube(_number(x), _number(y), _number(z), _number(side))
            for x, y, z in itertools.product(*axes)]


__all__ = ["Cube", "CubeLimits", "TilingError", "count", "tile"]
