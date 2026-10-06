"""Visual geometry -> the collision geometry options, each with its cost. One question.

    visual geometry  ->  CollisionPolicy  ->  collision geometry  ->  BoxMerger  ->  HitboxTiler

**What could this block's collision geometry be, and what does each choice cost?**

Visual and collision geometry are different things, and the game agrees: a pressure plate
draws a plate and collides with nothing, a wall draws 16 high and collides at 24. Tiling the
visual model exactly is cheap for a block and ruinous for anything thin -- a pressure plate
is 196 cubes -- so which geometry to represent has to be a decision, made where it is
visible.

This stage **reports, it does not choose.** :func:`options` builds every option the inputs
allow and prices each one; :func:`choose` returns the one the caller names. There is no
default and no "cheapest": deciding that a 196-cube plate is acceptable, or that a rug may
be walked through, is the caller's call per block, exactly like selecting which states to
compile.

## The options

* ``NONE`` -- no collision. Zero cost.
* ``SOURCE`` -- the source game's own collision shape, **supplied by the caller**. It lives
  in the mod's code, not its assets, so this stage cannot read it; "the source has no
  collision" is an empty geometry, not a missing one.
* ``VISUAL`` -- the visual model's boxes, as drawn.
* ``THICKENED`` -- the visual boxes, each edge thinner than ``min_thickness`` grown to it.
* ``EXPLICIT`` -- geometry the caller supplies as an override. Explicit means the caller
  wrote it down, never that this module knows what some particular block should do.

``VISUAL`` and ``THICKENED`` are built from axis-aligned boxes with volume. A rotated box or
a zero-volume plane has no axis-aligned volume to collide with; such parts are left out and
**counted in the option**, so the loss is on the record rather than silent.

## Thickening

Each thin edge grows to ``min_thickness`` rounded up to whole units, placed on whole units
as near centred as the original allows -- so a thickened box always contains the original,
and thickening never introduces a cut finer than a unit. (Growing about the centre alone put edges on half
units, and overlapping thickened boxes then merged into half-unit slivers no cube can
cover: geometry with no thin part, refused as too thin.)

If growing pushes a box out of the block's cell on an axis where it was inside, the box is
shifted back in rather than clipped: a floor plate ``y 0..1`` thickened to 2 becomes
``y 0..2``, not ``-1..1``. Boxes already thick enough are untouched; nothing ever shrinks.
Thickened boxes may overlap -- the merger decides how to represent their union.

## Cost, and the cut it is for

An option's cost is the number of cubes the tiler needs for it. The tiler covers each
region on its own, so the count depends on how the space is cut into regions, and two exact
cuts are always available: the merger's partition, and the boxes as given (cubes may
overlap, so overlapping boxes are a valid cover). Neither wins everywhere. A wall crossing
merged into a post and four short stubs tiles in 34 cubes; the post and four full,
overlapping arms in 26 -- and across CMB, the merged cut puts every wall's worst state at 43
cubes where the boxes as given need 26.

So each option is priced on the cheaper of the two and **carries those regions**, with
:attr:`Option.cut` naming which. Picking between exact covers of the same space changes the
representation, never the geometry, so it is not a policy decision -- and carrying the
regions means what was priced is what gets tiled.

An option that cannot be tiled exactly -- a part thinner than the smallest cube -- is still
reported, with the reason, and :func:`choose` refuses it.
"""

from __future__ import annotations

import dataclasses
import enum
import math
from fractions import Fraction
from typing import Iterable

from .ir import Box, Geometry
from .merge import merge
from .tile import CubeLimits, TilingError, count

#: The block cell, in model units. A box inside it on an axis stays inside when thickened.
CELL = (Fraction(0), Fraction(16))


class Policy(enum.Enum):
    NONE = "none"
    SOURCE = "source"
    VISUAL = "visual"
    THICKENED = "thickened"
    EXPLICIT = "explicit"


class CollisionError(Exception):
    """The chosen collision cannot be used. Always fatal, never a fallback."""


@dataclasses.dataclass(frozen=True)
class Option:
    """One possible collision geometry, priced.

    ``geometry`` is ``None`` only for ``NONE``. ``regions`` is the cut ``cubes`` was priced
    on -- what to hand the tiler -- and ``cut`` says which: ``"merged"`` or ``"as given"``.
    ``cubes`` is ``None`` when no exact cover exists, and ``refusal`` then says why.
    ``left_out`` counts visual parts with no axis-aligned volume (rotated boxes, planes)
    that the option does not include.
    """

    policy: Policy
    geometry: Geometry | None
    cubes: int | None
    regions: tuple[Box, ...] = ()
    cut: str | None = None
    refusal: str | None = None
    left_out: int = 0

    @property
    def usable(self) -> bool:
        return self.cubes is not None


def options(
    visual: Geometry,
    limits: CubeLimits,
    *,
    source: Geometry | None = None,
    explicit: Geometry | None = None,
    min_thickness: float | None = None,
) -> tuple[Option, ...]:
    """Every collision option these inputs allow, each with its cost, in :class:`Policy` order.

    ``SOURCE`` appears only when ``source`` is given, ``THICKENED`` only with
    ``min_thickness``, ``EXPLICIT`` only with ``explicit``. Nothing is chosen.
    """
    solid = tuple(b for b in visual.boxes if b.volume > 0)
    left_out = len(visual.boxes) - len(solid) + len(visual.oriented)

    out = [Option(Policy.NONE, None, 0, cut="none")]
    if source is not None:
        out.append(_priced(Policy.SOURCE, source, limits))
    out.append(_priced(Policy.VISUAL, _geometry(solid, visual, "visual"), limits, left_out))
    if min_thickness is not None:
        thick = Geometry(
            # Planes included: thickening gives a plate drawn as one face its volume.
            tuple(sorted((thicken(b, min_thickness) for b in visual.boxes), key=Box.as_tuple)),
            source=f"{visual.source} thickened to {min_thickness}",
            exact=visual.exact,
        )
        out.append(_priced(Policy.THICKENED, thick, limits, len(visual.oriented)))
    if explicit is not None:
        out.append(_priced(Policy.EXPLICIT, explicit, limits))
    return tuple(out)


def choose(offered: Iterable[Option], policy: Policy) -> Option:
    """The option for ``policy``. Raises if it was not offered or cannot be represented."""
    for option in offered:
        if option.policy is policy:
            if not option.usable:
                raise CollisionError(f"{policy.value} collision cannot be represented: {option.refusal}")
            return option
    raise CollisionError(
        f"{policy.value} collision was not offered; supply its input "
        f"(source, explicit or min_thickness) to options()"
    )


def thicken(box: Box, min_thickness: float) -> Box:
    """``box`` with every edge thinner than ``min_thickness`` grown to it, kept in the cell.

    A zero-volume plane is thickened too: a plate drawn as a single face is still a plate.
    """
    t = Fraction(str(min_thickness))
    if t <= 0:
        raise ValueError(f"min_thickness must be positive, got {min_thickness}")
    coords = [Fraction(str(v)) for v in box.as_tuple()]
    for a in range(3):
        lo, hi = coords[a], coords[a + 3]
        if hi - lo >= t:
            continue
        # Whole units: growing about the centre alone puts edges on half units, and the
        # merger's partition of overlapping thickened boxes then has half-unit slivers no
        # cube can cover -- geometry with no thin part refused as too thin. So the width is
        # the thickness rounded up (or the whole units the box already spans, if more), and
        # the start is the whole unit that keeps the original inside, nearest centred;
        # a tie goes to the lower start.
        width = max(Fraction(math.ceil(t)), Fraction(math.ceil(hi) - math.floor(lo)))
        target = (lo + hi) / 2 - width / 2
        starts = range(math.ceil(hi - width), math.floor(lo) + 1)
        new_lo = Fraction(min(starts, key=lambda start: (abs(start - target), start)))
        new_hi = new_lo + width
        inside = CELL[0] <= lo and hi <= CELL[1]
        if inside and t <= CELL[1] - CELL[0]:
            if new_lo < CELL[0]:
                new_lo, new_hi = CELL[0], CELL[0] + width
            elif new_hi > CELL[1]:
                new_lo, new_hi = CELL[1] - width, CELL[1]
        coords[a], coords[a + 3] = new_lo, new_hi
    return Box(*(_number(v) for v in coords))


# --- internals -------------------------------------------------------------------------


def _number(v: Fraction) -> float:
    return int(v) if v.denominator == 1 else float(v)


def _geometry(boxes: tuple[Box, ...], visual: Geometry, label: str) -> Geometry:
    return Geometry(boxes, source=f"{visual.source} ({label})", exact=visual.exact)


def _priced(policy: Policy, geometry: Geometry, limits: CubeLimits, left_out: int = 0) -> Option:
    solid = tuple(b for b in geometry.boxes if b.volume > 0)
    if len(solid) != len(geometry.boxes):
        return Option(policy, geometry, None,
                      refusal="has zero-volume boxes, which no cube covers", left_out=left_out)
    priced: list[tuple[int, int, str, tuple[Box, ...]]] = []
    refusal = None
    # The merged cut first, so it wins a tie: it is the canonical description of the space.
    for rank, (cut, regions) in enumerate((("merged", merge(solid)), ("as given", solid))):
        try:
            priced.append((sum(count(r, limits) for r in regions), rank, cut, regions))
        except TilingError as exc:
            refusal = refusal or str(exc)
    if not priced:
        return Option(policy, geometry, None, refusal=refusal, left_out=left_out)
    cubes, _, cut, regions = min(priced)
    return Option(policy, geometry, cubes, regions, cut, None, left_out)


__all__ = ["CollisionError", "Option", "Policy", "choose", "options", "thicken"]
