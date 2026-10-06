"""HitboxTiler: regions -> cubes that cover exactly the same space.

Exactness goes through tests/oracle.py, which shares no code with the tiler. Optimality is
checked with witness points: points no single allowed cube can hold two of, so their count
is a lower bound for *any* cover -- computed here, not taken from the tiler's own formula.
"""

from __future__ import annotations

import ast
import itertools
import json
import math
import pathlib
import random
from fractions import Fraction

import pytest

from paperized.analysis.geometry import measure_state
from paperized.blockstate import states
from paperized.decompose import GeometryError
from paperized.ir import FULL_BLOCK, Box
from paperized.merge import merge
from paperized.tile import Cube, CubeLimits, TilingError, tile

from oracle import assert_covers

#: The range of a scaled shulker, in model units (scale 0.0625..16 blocks). Named here,
#: in the tests, because the tiler itself must not know what a cube becomes.
SHULKER = CubeLimits(1, 256)


def boxes(cubes):
    return [c.as_box() for c in cubes]


def witnesses(region: Box, largest: Fraction) -> list[tuple[Fraction, ...]]:
    """Points inside ``region``, neighbours more than ``largest`` apart on some axis.

    No cube of side at most ``largest`` holds two of them, so any cover of the region by
    such cubes needs one cube per point.
    """
    axes = []
    for a in range(3):
        lo, hi = Fraction(str(region.as_tuple()[a])), Fraction(str(region.as_tuple()[a + 3]))
        n = 1
        while (hi - lo) / n > largest:  # fewest points whose spacing still exceeds `largest`
            n += 1
        axes.append([lo] if n == 1 else [lo + (hi - lo) * i / (n - 1) for i in range(n)])
    points = list(itertools.product(*axes))
    for p, q in itertools.combinations(points, 2):
        assert any(abs(p[a] - q[a]) > largest for a in range(3)) or len(points) == 1
    return points


def assert_optimal(region: Box, cubes, limits=SHULKER):
    largest = min(min(region.width, region.height, region.depth), limits.max_side)
    assert len(cubes) == len(witnesses(region, Fraction(str(largest)))), (
        f"{region}: {len(cubes)} cubes, but the witness bound is "
        f"{len(witnesses(region, Fraction(str(largest))))}"
    )


# --- the invariant ---------------------------------------------------------------------


def test_a_full_block_is_one_cube():
    assert tile([FULL_BLOCK], SHULKER) == (Cube(0, 0, 0, 16),)


@pytest.mark.parametrize("region, cubes", [
    pytest.param(Box(0, 0, 8, 16, 16, 16), 4, id="vertical slab: four 8-cubes, as CMB places it"),
    pytest.param(Box(4, 0, 4, 12, 24, 12), 3, id="wall collision column: three 8-cubes, as CMB stacks"),
    pytest.param(Box(0, 0, 0, 16, 8, 16), 4, id="slab"),
    pytest.param(Box(7, 0, 7, 9, 16, 9), 8, id="pane post: exact costs eight"),
    pytest.param(Box(5, 0, 0, 11, 14, 4), 8, id="wall arm stub: flush rows overlap"),
])
def test_single_regions(region, cubes):
    got = tile([region], SHULKER)
    assert len(got) == cubes
    assert_covers([region], boxes(got))
    assert_optimal(region, got)


def test_horizontal_stairs_are_six_cubes_like_cmb():
    """CMB's horizontal stair: three quarter-columns, two 8-cube layers each."""
    regions = merge([Box(0, 0, 0, 16, 16, 8), Box(8, 0, 8, 16, 16, 16)])
    got = tile(regions, SHULKER)
    assert len(got) == 6
    assert_covers(regions, boxes(got))


def test_rows_end_flush_and_overlap_rather_than_overhang():
    (region,) = [Box(0, 0, 0, 6, 6, 16)]
    zs = sorted(c.z for c in tile([region], SHULKER))
    assert zs == [0, 6, 10], "the last cube sits flush with the end, overlapping its neighbour"


def test_fractional_edges_stay_exact():
    region = Box(0.5, 0, 0, 16, 15.5, 16)
    got = tile([region], SHULKER)
    assert {c.side for c in got} == {15.5}
    assert_covers([region], boxes(got))


def test_the_largest_cube_caps_the_side():
    got = tile([FULL_BLOCK], CubeLimits(1, 8))
    assert len(got) == 8
    assert_optimal(FULL_BLOCK, got, CubeLimits(1, 8))


def test_a_region_thinner_than_the_smallest_cube_is_refused():
    """CMB's pressed pressure plate is half a pixel thick. Thickening it would be a choice
    about what geometry to represent, made silently; that choice belongs upstream."""
    with pytest.raises(TilingError, match="0.5 thick"):
        tile([Box(1, 0, 1, 15, 0.5, 15)], SHULKER)


def test_a_region_with_no_volume_is_refused():
    with pytest.raises(TilingError, match="no volume"):
        tile([Box(8, 0, 0, 8, 16, 16)], SHULKER)


def test_nothing_in_is_nothing_out():
    assert tile([], SHULKER) == ()


# --- two-sided: the checks can fail ----------------------------------------------------


def test_the_oracle_sees_a_cube_that_sticks_out():
    with pytest.raises(AssertionError, match="different space"):
        assert_covers([Box(0, 0, 0, 16, 8, 16)], [FULL_BLOCK.__class__(0, 0, 0, 16, 9, 16)])


def test_a_gap_raises_instead_of_being_returned(monkeypatch):
    import paperized.tile as t

    monkeypatch.setattr(t, "_starts", lambda lo, hi, side: [lo])
    with pytest.raises(TilingError):
        t.tile([Box(0, 0, 0, 16, 8, 16)], SHULKER)


def test_the_witness_bound_is_not_vacuous():
    """Fewer cubes than witnesses must fail the optimality check."""
    region = Box(0, 0, 0, 16, 8, 16)
    with pytest.raises(AssertionError, match="witness bound"):
        assert_optimal(region, [Cube(0, 0, 0, 8)])


# --- properties over random regions ----------------------------------------------------


def _region(rng: random.Random) -> Box:
    lo = [rng.randrange(0, 15) for _ in range(3)]
    return Box(*lo, *(rng.randrange(l + 1, 17) for l in lo))


@pytest.mark.parametrize("seed", range(200))
def test_random_regions_are_covered_exactly_and_optimally(seed):
    rng = random.Random(seed)
    region = _region(rng)
    limits = CubeLimits(1, rng.choice([2, 4, 8, 16, 256]))
    got = tile([region], limits)
    assert_covers([region], boxes(got))
    assert all(limits.min_side <= c.side <= limits.max_side for c in got)
    assert all(_inside(c.as_box(), region) for c in got), "a cube left its region"
    assert_optimal(region, got, limits)


def _inside(inner: Box, outer: Box) -> bool:
    i, o = inner.as_tuple(), outer.as_tuple()
    return all(o[a] <= i[a] and i[a + 3] <= o[a + 3] for a in range(3))


@pytest.mark.parametrize("seed", range(20))
def test_order_does_not_matter(seed):
    rng = random.Random(seed)
    regions = [_region(rng) for _ in range(4)]
    expected = tile(regions, SHULKER)
    rng.shuffle(regions)
    assert tile(regions, SHULKER) == expected


# --- every shape both mods draw ----------------------------------------------------------

VANILLA = pathlib.Path("/tmp/opencode/assets/minecraft/models")
CMB = pathlib.Path(
    "/mnt/storage/repos/Cinchs_Missing_Blocks_Paperized/server/plugins/CraftEngine"
    "/resources/cinchsmissingblocks/resourcepack/assets/cinchsmissingblocks"
)
FD = pathlib.Path("/mnt/storage/devops/FarmersDelight")


@pytest.mark.skipif(not (CMB.exists() and FD.exists() and VANILLA.exists()),
                    reason="real mod sources not present")
def test_every_shape_of_both_mods_tiles_exactly_or_is_refused_as_too_thin():
    """Every distinct composed shape of every state of both mods, merged, then each region tiled.

    Zero-volume planes are dropped first: they are visual only, and refusing them is
    tested above. The only other refusal allowed is a region thinner than a cube.
    """
    sources = [
        (CMB / "blockstates", [CMB / "models/block", CMB / "models", VANILLA]),
        (FD / "src/generated/resources/assets/farmersdelight/blockstates",
         [FD / "src/main/resources/assets/farmersdelight",
          FD / "src/generated/resources/assets/farmersdelight"]),
    ]
    shapes: set[tuple[Box, ...]] = set()
    for blockstates, roots in sources:
        for path in sorted(blockstates.glob("*.json")):
            blockstate = json.loads(path.read_text())
            for state in states(blockstate):
                try:
                    geometry = measure_state(path.stem, blockstate, state, roots, VANILLA)
                except GeometryError:
                    continue
                shapes.add(tuple(b for b in geometry.boxes if b.volume > 0))
    # Every shape is the union of its regions, and the tiler covers each region on its own,
    # so checking each distinct region once checks every shape. 108 walls share regions.
    regions: set[Box] = set()
    for solid in shapes:
        if solid:
            regions.update(merge(solid))
    thin = []
    for region in sorted(regions, key=Box.as_tuple):
        try:
            cubes = tile([region], SHULKER)
        except TilingError as exc:
            assert "thick" in str(exc), exc
            thin.append(region)
            continue
        assert_covers([region], boxes(cubes))
    assert len(shapes) > 350 and len(regions) > 500
    assert thin == [Box(1, 0, 1, 15, 0.5, 15)], (
        "only CMB's pressed pressure plate is thinner than a pixel"
    )


# --- what it must not know ---------------------------------------------------------------


def test_tiler_knows_nothing_about_the_runtime_or_where_geometry_came_from():
    import paperized.tile as t

    tree = ast.parse(pathlib.Path(t.__file__).read_text())
    local = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level}
    assert local == {"ir"}
    docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))
                  and ast.get_docstring(n) is not None}
    banned = {"shulker", "craftengine", "entity", "paper", "furniture", "carrier", "state",
              "wall", "fence", "pane", "slab", "stair", "minecraft", "reachab"}
    offenders = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            offenders |= {w for w in banned if w in node.id.lower()}
        elif isinstance(node, ast.Attribute):
            offenders |= {w for w in banned if w in node.attr.lower()}
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            offenders |= {w for w in banned if w in node.value.lower()}
    assert not offenders, f"the tiler knows more than geometry: {offenders}"
