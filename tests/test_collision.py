"""CollisionPolicy: every collision option a block allows, priced, and none chosen for it."""

from __future__ import annotations

import ast
import json
import math
import pathlib
import random
from fractions import Fraction

import pytest

from paperized.analysis.geometry import measure_state
from paperized.blockstate import states
from paperized.collision import CollisionError, Policy, choose, options, thicken
from paperized.decompose import GeometryError
from paperized.ir import FULL_BLOCK, Box, Geometry, OrientedBox
from paperized.tile import CubeLimits, tile

from oracle import assert_covers

SHULKER = CubeLimits(1, 256)
PLATE = Geometry((Box(1, 0, 1, 15, 1, 15),), source="plate")
PRESSED = Geometry((Box(1, 0, 1, 15, 0.5, 15),), source="pressed plate")


def priced(offered):
    return {o.policy: o.cubes for o in offered}


# --- reporting, not choosing ---------------------------------------------------------------


def test_a_pressure_plate_shows_why_this_stage_exists():
    """196 cubes as drawn; nothing at all as the game has it."""
    offered = options(PLATE, SHULKER, source=Geometry((), source="empty"), min_thickness=4)
    assert priced(offered) == {
        Policy.NONE: 0,
        Policy.SOURCE: 0,
        Policy.VISUAL: 196,
        Policy.THICKENED: 16,
    }


def test_a_full_block_costs_one_cube_whichever_way():
    offered = options(Geometry((FULL_BLOCK,), source="cube"), SHULKER,
                      source=Geometry((FULL_BLOCK,), source="cube"), min_thickness=4)
    assert {o.cubes for o in offered if o.policy is not Policy.NONE} == {1}


def test_choosing_ignores_cost():
    """The caller asked for visual; visual is what they get, 196 cubes and all."""
    chosen = choose(options(PLATE, SHULKER), Policy.VISUAL)
    assert chosen.policy is Policy.VISUAL and chosen.cubes == 196


def test_an_option_that_was_not_offered_is_refused():
    with pytest.raises(CollisionError, match="not offered"):
        choose(options(PLATE, SHULKER), Policy.SOURCE)


def test_an_untileable_option_is_reported_and_then_refused_when_chosen():
    offered = options(PRESSED, SHULKER, min_thickness=1)
    (visual,) = [o for o in offered if o.policy is Policy.VISUAL]
    assert visual.cubes is None and "0.5 thick" in visual.refusal
    with pytest.raises(CollisionError, match="cannot be represented"):
        choose(offered, Policy.VISUAL)
    assert choose(offered, Policy.THICKENED).cubes == 196


def test_source_and_explicit_appear_only_when_supplied():
    assert [o.policy for o in options(PLATE, SHULKER)] == [Policy.NONE, Policy.VISUAL]
    explicit = Geometry((Box(0, 0, 0, 16, 2, 16),), source="override")
    assert [o.policy for o in options(PLATE, SHULKER, explicit=explicit)] == [
        Policy.NONE, Policy.VISUAL, Policy.EXPLICIT]


def test_the_stage_offers_no_way_to_pick_for_the_caller():
    import paperized.collision as c

    assert not {n for n in c.__all__ if any(w in n.lower() for w in ("best", "cheap", "default", "auto"))}


def test_parts_without_axis_aligned_volume_are_counted_not_hidden():
    plane = Box(8, 0, 0, 8, 16, 16)
    turned = OrientedBox(((0.0, 0.0, 8.0),) * 8, exact=False)
    visual = Geometry((FULL_BLOCK, plane), source="v", oriented=(turned,), exact=False)
    (option,) = [o for o in options(visual, SHULKER) if o.policy is Policy.VISUAL]
    assert option.left_out == 2
    assert option.geometry.boxes == (FULL_BLOCK,)


# --- the cut that was priced is the cut that gets tiled -------------------------------------


def turn(box: Box, quarters: int) -> Box:
    for _ in range(quarters):
        x0, y0, z0, x1, y1, z1 = box.as_tuple()
        box = Box(16 - z1, y0, x0, 16 - z0, y1, x1)
    return box


WALL_CROSSING = Geometry(
    (Box(4, 0, 4, 12, 16, 12), *(turn(Box(5, 0, 0, 11, 14, 8), k) for k in range(4))),
    source="wall crossing")


def test_the_cheaper_exact_cut_is_priced_and_carried():
    """Merged, a crossing is a post and four stubs: 34 cubes. As drawn, overlapping: 26."""
    (visual,) = [o for o in options(WALL_CROSSING, SHULKER) if o.policy is Policy.VISUAL]
    assert (visual.cubes, visual.cut) == (26, "as given")
    assert len(tile(visual.regions, SHULKER)) == visual.cubes
    assert_covers(list(WALL_CROSSING.boxes), [c.as_box() for c in tile(visual.regions, SHULKER)])


def test_a_tie_keeps_the_merged_cut():
    stairs = Geometry((Box(0, 0, 0, 16, 8, 16), Box(8, 8, 0, 16, 16, 16)), source="stairs")
    (visual,) = [o for o in options(stairs, SHULKER) if o.policy is Policy.VISUAL]
    assert visual.cut == "merged"


# --- thickening ---------------------------------------------------------------------------


def test_a_floor_plate_thickens_upward_not_into_the_block_below():
    assert thicken(Box(1, 0, 1, 15, 1, 15), 2) == Box(1, 0, 1, 15, 2, 15)


def test_thickening_moves_edges_to_whole_units():
    """Growing about the centre put edges on half units, and the merged partition of two
    such boxes had half-unit slivers no cube covers: geometry with no thin part refused."""
    assert thicken(Box(0, 0, 7, 16, 16, 8), 2) == Box(0, 0, 6, 16, 16, 8)
    pair = Geometry((Box(0, 0, 7, 16, 1, 8), Box(0, 0, 7.5, 16, 1, 8.5)), source="pair")
    (thick,) = [o for o in options(pair, SHULKER, min_thickness=2) if o.policy is Policy.THICKENED]
    assert thick.usable


def test_thick_enough_boxes_are_untouched_and_nothing_shrinks():
    assert thicken(FULL_BLOCK, 4) == FULL_BLOCK
    assert thicken(Box(0, 0, 0, 16, 3, 16), 2) == Box(0, 0, 0, 16, 3, 16)


def test_a_plane_drawn_as_one_face_becomes_a_plate():
    assert thicken(Box(0, 0, 0, 16, 0, 16), 1) == Box(0, 0, 0, 16, 1, 16)


def test_a_box_reaching_out_of_the_cell_is_not_pushed_back():
    """Only a box inside the cell on an axis is kept inside it on that axis."""
    assert thicken(Box(7, 0, 7, 8, 24, 8), 2) == Box(6, 0, 6, 8, 24, 8)
    assert thicken(Box(-1, 0, 0, 0, 16, 16), 2) == Box(-2, 0, 0, 0, 16, 16)


@pytest.mark.parametrize("seed", range(100))
def test_thickening_contains_the_original_and_reaches_the_thickness(seed):
    rng = random.Random(seed)
    lo = [rng.randrange(0, 32) / 2 for _ in range(3)]
    box = Box(*lo, *(min(16, v + rng.randrange(0, 8) / 2) for v in lo))
    t = rng.choice([1, 2, 3, 4])
    grown = thicken(box, t)
    b, g = box.as_tuple(), grown.as_tuple()
    for a in range(3):
        assert g[a] <= b[a] and b[a + 3] <= g[a + 3], "the original must stay inside"
        if b[a + 3] - b[a] < t:
            assert g[a + 3] - g[a] == max(t, math.ceil(b[a + 3]) - math.floor(b[a])), (
                "a thin edge grows to the thickness, on whole units, and no further"
            )
        if b[a + 3] - b[a] < t:
            assert Fraction(str(g[a])).denominator == 1 == Fraction(str(g[a + 3])).denominator


# --- every shape both mods draw -------------------------------------------------------------

VANILLA = pathlib.Path("/tmp/opencode/assets/minecraft/models")
CMB = pathlib.Path(
    "/mnt/storage/repos/Cinchs_Missing_Blocks_Paperized/server/plugins/CraftEngine"
    "/resources/cinchsmissingblocks/resourcepack/assets/cinchsmissingblocks"
)
FD = pathlib.Path("/mnt/storage/devops/FarmersDelight")


@pytest.mark.skipif(not (CMB.exists() and FD.exists() and VANILLA.exists()),
                    reason="real mod sources not present")
def test_every_shape_of_both_mods_prices_honestly():
    """For every distinct composed shape, every usable option's regions cover its geometry
    exactly and tile in exactly the cubes it was priced at. Thickening refuses nothing."""
    sources = [
        (CMB / "blockstates", [CMB / "models/block", CMB / "models", VANILLA]),
        (FD / "src/generated/resources/assets/farmersdelight/blockstates",
         [FD / "src/main/resources/assets/farmersdelight",
          FD / "src/generated/resources/assets/farmersdelight"]),
    ]
    shapes: dict[tuple, Geometry] = {}
    for blockstates, roots in sources:
        for path in sorted(blockstates.glob("*.json")):
            blockstate = json.loads(path.read_text())
            for state in states(blockstate):
                try:
                    geometry = measure_state(path.stem, blockstate, state, roots, VANILLA)
                except GeometryError:
                    continue
                shapes.setdefault((geometry.boxes, geometry.oriented), geometry)
    refused_visual = 0
    for geometry in shapes.values():
        for option in options(geometry, SHULKER, min_thickness=2):
            if option.policy is Policy.NONE:
                continue
            if not option.usable:
                assert option.policy is Policy.VISUAL and "thick" in option.refusal
                refused_visual += 1
                continue
            assert len(tile(option.regions, SHULKER)) == option.cubes
            assert_covers(list(option.geometry.boxes), list(option.regions))
    assert len(shapes) > 350
    assert refused_visual == 1, "only CMB's pressed pressure plate, as drawn"


# --- what it must not know ---------------------------------------------------------------


def test_policy_knows_geometry_not_blocks_or_runtimes():
    import paperized.collision as c

    tree = ast.parse(pathlib.Path(c.__file__).read_text())
    local = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level}
    assert local == {"ir", "merge", "tile"}
    docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))
                  and ast.get_docstring(n) is not None}
    banned = {"shulker", "craftengine", "entity", "paper", "furniture", "minecraft", "wall",
              "fence", "pane", "slab", "stair", "plate", "rug", "cmb", "farmer"}
    offenders = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            offenders |= {w for w in banned if w in node.id.lower()}
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            offenders |= {w for w in banned if w in node.value.lower()}
    assert not offenders, f"the policy knows about particular blocks or runtimes: {offenders}"
