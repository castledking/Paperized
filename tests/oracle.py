"""An occupancy oracle that shares no code with paperized.merge.

It probes a point in every cell of the lattice the boxes are drawn on and asks which boxes
contain it, in exact Fractions, where the merger indexes grid cells. A merger checked by
its own cell arithmetic would agree with itself however wrong it was.
"""

from __future__ import annotations

import itertools
from fractions import Fraction


def _probes(*box_sets):
    """A point inside every cell of the coordinate lattice all the boxes are drawn on."""
    axes = []
    for a in range(3):
        values = sorted({Fraction(str(v)) for boxes in box_sets for b in boxes
                         for v in (b.as_tuple()[a], b.as_tuple()[a + 3])})
        axes.append([((lo + hi) / 2, hi - lo) for lo, hi in zip(values, values[1:])])
    return itertools.product(*axes)


def _inside(point, box):
    t = [Fraction(str(v)) for v in box.as_tuple()]
    return all(t[a] < point[a] < t[a + 3] for a in range(3))


def occupancy(given, merged):
    """(same space, merged is a partition, occupied volume of given, summed volume of merged)."""
    same, partition, occupied = True, True, Fraction(0)
    for probe in _probes(given, merged):
        point = tuple(p for p, _ in probe)
        size = probe[0][1] * probe[1][1] * probe[2][1]
        in_given = any(_inside(point, b) for b in given)
        holders = sum(_inside(point, b) for b in merged)
        same &= in_given == (holders > 0)
        partition &= holders <= 1
        occupied += size if in_given else 0
    summed = sum(Fraction(str(b.width)) * Fraction(str(b.height)) * Fraction(str(b.depth))
                 for b in merged)
    return same, partition, occupied, summed


def assert_same_space(given, merged):
    solid = [b for b in given if b.volume > 0]
    regions = [b for b in merged if b.volume > 0]
    same, partition, occupied, summed = occupancy(solid, regions)
    assert same, f"merged boxes occupy different space: {given} -> {merged}"
    assert partition, f"merged boxes overlap: {merged}"
    assert summed == occupied, "a partition's summed volume must be the occupied volume"
