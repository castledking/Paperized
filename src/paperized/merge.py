"""Boxes -> fewer boxes, same space. One question, asked once.

    VisualGeometry.boxes  ->  BoxMerger  ->  region set

**Can these boxes be represented as fewer axis-aligned boxes without changing the space
they occupy?**

That is the entire contract. Input is boxes, output is boxes, and nothing else crosses
the boundary:

* no family vocabulary -- it does not know what a slab, wall, pane or stair is. A wall's
  post-and-arm shape comes out of the geometry, not out of a name
* no runtime -- nothing about entities, hitboxes, CraftEngine, carriers or Paper. Cutting
  regions into whatever a runtime can place is the tiler's job, a later stage
* no collision semantics -- the boxes mean whatever the caller's boxes meant

## The invariant

**Occupancy is preserved exactly, and the output is a partition.** The union of the output
boxes is the union of the input boxes -- not one point more, not one point less -- and no
two output boxes share interior. So the output's summed volume *is* the occupied volume.

"Fewer boxes" is never allowed to buy a different shape. Two boxes touching only along a
step, ``[0,0,0 -> 8,8,16]`` and ``[8,8,0 -> 16,16,16]``, stay two: their bounding box would
fill two empty octants, and an occupied region that was not in the model is the kind of
error that turns into a wall nobody can walk past once a later stage gives it collision.

Why a partition rather than any cover: overlap makes "same occupied volume" uncheckable by
summing, and it hands the next stage space it would fill twice.

The invariant is checked on every call, not only in tests. A merger that ever returned a
different shape would be wrong *quietly* -- every downstream number would still look
plausible -- so a violation raises :class:`MergeError` instead of being returned.

## Fewer, not minimal

Partitioning a 3D rectilinear shape into the fewest boxes is NP-hard in general, so this
does not claim a minimum. It tries a small, fixed set of deterministic strategies and keeps
the one with the fewest boxes:

1. **carving the input as authored** -- the boxes are taken largest first, and each keeps
   only the space no earlier box claimed. A wall's post stays whole and each arm loses the
   part inside it, which is how the shape was authored. On an input that is already a
   partition nothing is carved, so this is the input itself. Preferred on a tie, so
   authored cut lines survive whenever re-cutting buys nothing.
2. **greedy re-partition**, once per axis order -- the occupied space is rebuilt from the
   input's own coordinates as a grid, and each box grows from its first uncovered cell along
   one axis, then the next, then the last. Six orders, six candidates.

Every candidate is then **face merged**: two boxes sharing one whole face become one,
repeated until no two do.

So when the input is a partition, the output never has more boxes than the input. When the
input overlaps itself, it can: a plus sign authored as two crossing bars is three boxes as a
partition, and saying so is the honest answer.

## What it keeps and collapses

Identical and contained boxes collapse, because the space they describe is already
described. :mod:`paperized.decompose` keeps duplicate elements deliberately so that this is
the one visible place where "two shapes that coincide" becomes "one shape".

Boxes with no volume -- a flat plane, a line -- are **kept verbatim and never merged**.
Occupancy cannot account for them, and dropping one would delete a visible plane while
every volume check still passed. They are returned after the solid regions, sorted,
exactly as given.

Coordinates are never computed, only compared: every output coordinate is one of the input's
own, so fractional coordinates stay exactly what they were.
"""

from __future__ import annotations

import itertools
from typing import Iterable, Sequence

from .ir import Box

Cell = tuple[int, int, int]
Grid = tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]

#: The order greedy re-partition grows a box in, as axis indices: first, second, last.
AXIS_ORDERS: tuple[tuple[int, int, int], ...] = tuple(itertools.permutations(range(3)))


class MergeError(Exception):
    """The merge would change the occupied space. Always a bug here, never a fallback."""


def merge(boxes: Iterable[Box]) -> tuple[Box, ...]:
    """The fewest boxes found that occupy exactly the space ``boxes`` occupies.

    Deterministic, and independent of input order: the same set of boxes always yields
    the same tuple, solid regions sorted, followed by any zero-volume boxes sorted.
    """
    given = list(boxes)
    flat = sorted((b for b in given if b.volume == 0), key=Box.as_tuple)
    solid = sorted((b for b in given if b.volume > 0), key=Box.as_tuple)
    if not solid:
        return tuple(flat)

    grid = _grid(solid)
    cells = _cells(solid, grid)

    candidates: list[list[Box]] = [_face_merge(_carve(solid, grid))]
    for order in AXIS_ORDERS:
        candidates.append(_face_merge(_greedy(cells, grid, order)))

    # min() keeps the first of equals, so the authored candidate wins a tie.
    best = sorted(min(candidates, key=len), key=Box.as_tuple)

    if _cells(best, grid) != cells or not _disjoint(best, grid):
        raise MergeError(
            f"merging {len(solid)} boxes produced {len(best)} that do not occupy the same "
            f"space as a partition: {[b.as_tuple() for b in best]}"
        )
    return tuple(best) + tuple(flat)


# --- the grid ----------------------------------------------------------------------


def _grid(boxes: Sequence[Box]) -> Grid:
    """Every coordinate the boxes use, per axis, sorted. Cell i spans grid[i]..grid[i+1]."""
    axes: list[tuple[float, ...]] = []
    for lo, hi in ((0, 3), (1, 4), (2, 5)):
        values = {b.as_tuple()[lo] for b in boxes} | {b.as_tuple()[hi] for b in boxes}
        axes.append(tuple(sorted(values)))
    return axes[0], axes[1], axes[2]


def _span(box: Box, grid: Grid) -> tuple[range, range, range]:
    t = box.as_tuple()
    return tuple(  # type: ignore[return-value]
        range(grid[a].index(t[a]), grid[a].index(t[a + 3])) for a in range(3)
    )


def _cells(boxes: Iterable[Box], grid: Grid) -> set[Cell]:
    occupied: set[Cell] = set()
    for box in boxes:
        occupied.update(itertools.product(*_span(box, grid)))
    return occupied


def _disjoint(boxes: Sequence[Box], grid: Grid) -> bool:
    """No two boxes share interior, i.e. no grid cell is covered twice."""
    seen: set[Cell] = set()
    for box in boxes:
        cells = set(itertools.product(*_span(box, grid)))
        if cells & seen:
            return False
        seen |= cells
    return True


def _box(lo: Cell, hi: Cell, grid: Grid) -> Box:
    """The box covering cells lo..hi inclusive, in the grid's own coordinates."""
    return Box(
        grid[0][lo[0]], grid[1][lo[1]], grid[2][lo[2]],
        grid[0][hi[0] + 1], grid[1][hi[1] + 1], grid[2][hi[2] + 1],
    )


# --- strategies ----------------------------------------------------------------------


def _carve(boxes: Sequence[Box], grid: Grid) -> list[Box]:
    """Each box, largest first, keeps only the cells no earlier box claimed.

    A box with nothing taken from it comes out as itself. One that was carved has its
    remaining cells re-partitioned on their own, with whichever axis order needs fewest.
    """
    claimed: set[Cell] = set()
    out: list[Box] = []
    for box in sorted(boxes, key=lambda b: (-b.volume, b.as_tuple())):
        mine = set(itertools.product(*_span(box, grid))) - claimed
        if not mine:
            continue
        claimed |= mine
        out.extend(min((_greedy(mine, grid, order) for order in AXIS_ORDERS), key=len))
    return out


def _greedy(cells: set[Cell], grid: Grid, order: tuple[int, int, int]) -> list[Box]:
    """Re-partition the occupied cells, growing each box along ``order``.

    Cells are visited with the *last* axis of ``order`` varying slowest, so a box starts at
    the first free cell and grows along the first axis, then the second, then the last. Each
    growth step takes a whole row (or slab) or nothing, so a box only ever covers occupied
    cells nobody else has.
    """
    first, second, last = order
    free = set(cells)
    out: list[Box] = []

    def key(c: Cell) -> tuple[int, int, int]:
        return (c[last], c[second], c[first])

    for start in sorted(cells, key=key):
        if start not in free:
            continue
        hi = list(start)

        def block(axis: int, at: int) -> list[Cell]:
            """The cells one step past ``hi`` along ``axis``, across the box's other extents."""
            ranges = [range(start[a], hi[a] + 1) for a in range(3)]
            ranges[axis] = range(at, at + 1)
            return list(itertools.product(*ranges))

        for axis in order:
            while hi[axis] + 1 < len(grid[axis]) - 1:
                step = block(axis, hi[axis] + 1)
                if not all(c in free for c in step):
                    break
                hi[axis] += 1

        lo_cell: Cell = start
        hi_cell: Cell = (hi[0], hi[1], hi[2])
        free.difference_update(itertools.product(
            *(range(lo_cell[a], hi_cell[a] + 1) for a in range(3))))
        out.append(_box(lo_cell, hi_cell, grid))
    return out


def _face_merge(boxes: Iterable[Box]) -> list[Box]:
    """Join any two boxes that share one whole face, until no two do.

    Two boxes share a whole face when they agree exactly on two axes and meet end to end on
    the third; their union is then exactly a box. Nothing else is joined. Sorted at every
    pass so the result does not depend on input order.
    """
    current = sorted(boxes, key=Box.as_tuple)
    changed = True
    while changed:
        changed = False
        for i, j in itertools.combinations(range(len(current)), 2):
            joined = _join(current[i], current[j])
            if joined is not None:
                rest = [b for k, b in enumerate(current) if k not in (i, j)]
                current = sorted([*rest, joined], key=Box.as_tuple)
                changed = True
                break
    return current


def _join(a: Box, b: Box) -> Box | None:
    ta, tb = a.as_tuple(), b.as_tuple()
    for axis in range(3):
        others = [o for o in range(3) if o != axis]
        if any(ta[o] != tb[o] or ta[o + 3] != tb[o + 3] for o in others):
            continue
        if ta[axis + 3] == tb[axis] or tb[axis + 3] == ta[axis]:
            lo = [min(ta[k], tb[k]) for k in range(3)]
            hi = [max(ta[k + 3], tb[k + 3]) for k in range(3)]
            return Box(*lo, *hi)
    return None


__all__ = ["MergeError", "merge"]
