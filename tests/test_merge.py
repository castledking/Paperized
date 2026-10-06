"""BoxMerger: boxes -> fewer boxes, same occupied space.

The implementation knows geometry; these tests know what the geometry should be. Every
check of "same space" goes through :func:`oracle.occupancy`, an oracle that shares no code with
the merger: it probes points and asks which boxes contain them, where the merger indexes
grid cells. A merger checked by its own cell arithmetic would agree with itself however
wrong it was.

The shape fixtures are vanilla's own template models -- the elements CMB's walls, fences,
stairs and panes inherit -- composed the way their blockstates compose them. The expected
region counts are derived from the shapes here, not read from the merger.
"""

from __future__ import annotations

import ast
import itertools
import json
import pathlib
import random

import pytest

from paperized.decompose import GeometryError, decompose_ref
from paperized.ir import FULL_BLOCK, Box
from paperized.merge import merge

from oracle import assert_same_space


# --- the oracle: tests/oracle.py, which shares no code with the merger -------------


def test_the_oracle_sees_a_bounding_box_and_an_overlap():
    """The oracle has to be able to fail, or every assertion above is decoration."""
    step = [Box(0, 0, 0, 8, 8, 16), Box(8, 8, 0, 16, 16, 16)]
    with pytest.raises(AssertionError, match="different space"):
        assert_same_space(step, [FULL_BLOCK])
    with pytest.raises(AssertionError, match="overlap"):
        assert_same_space([FULL_BLOCK], [FULL_BLOCK, SLAB])


def test_a_wrong_answer_raises_instead_of_being_returned(monkeypatch):
    """The postcondition runs on every call. Break every strategy and it must refuse."""
    import paperized.merge as m

    def bounding(*_args, **_kwargs):
        return [FULL_BLOCK]

    monkeypatch.setattr(m, "_carve", bounding)
    monkeypatch.setattr(m, "_greedy", bounding)
    with pytest.raises(m.MergeError):
        m.merge([Box(0, 0, 0, 8, 8, 16), Box(8, 8, 0, 16, 16, 16)])


# --- composing vanilla's multipart, for fixtures only ---------------------------


def turn(box: Box, quarter_turns: int) -> Box:
    """A blockstate's ``y`` rotation, 90 degrees a step: north goes to east."""
    for _ in range(quarter_turns % 4):
        x0, y0, z0, x1, y1, z1 = box.as_tuple()
        box = Box(16 - z1, y0, x0, 16 - z0, y1, x1)
    return box


# Elements of vanilla's templates (models/block/*.json), as shipped.
WALL_POST = Box(4, 0, 4, 12, 16, 12)            # template_wall_post
WALL_SIDE = Box(5, 0, 0, 11, 14, 8)             # template_wall_side
WALL_SIDE_TALL = Box(5, 0, 0, 11, 16, 8)        # template_wall_side_tall
FENCE_POST = Box(6, 0, 6, 10, 16, 10)           # fence_post
FENCE_SIDE = (Box(7, 12, 0, 9, 15, 9), Box(7, 6, 0, 9, 9, 9))  # fence_side
PANE_POST = Box(7, 0, 7, 9, 16, 9)              # template_glass_pane_post
PANE_SIDE = Box(7, 0, 0, 9, 16, 7)              # template_glass_pane_side
PANE_SIDE_ALT = Box(7, 0, 9, 9, 16, 16)         # template_glass_pane_side_alt
PANE_NOSIDE = Box(7, 0, 7, 9, 16, 9)            # template_glass_pane_noside(_alt)
SLAB = Box(0, 0, 0, 16, 8, 16)
STAIRS = (SLAB, Box(8, 8, 0, 16, 16, 16))
INNER_STAIRS = (SLAB, Box(8, 8, 0, 16, 16, 16), Box(0, 8, 8, 8, 16, 16))
OUTER_STAIRS = (SLAB, Box(8, 8, 8, 16, 16, 16))


def pane(n=False, e=False, s=False, w=False) -> list[Box]:
    """minecraft:glass_pane's multipart: the post, then a side or a noside on each face."""
    sides = {"n": (PANE_SIDE, 0), "e": (PANE_SIDE, 1), "s": (PANE_SIDE_ALT, 0), "w": (PANE_SIDE_ALT, 1)}
    nosides = {"n": 0, "e": 0, "s": 1, "w": 3}
    boxes = [PANE_POST]
    for face, connected in zip("nesw", (n, e, s, w)):
        model, quarter = sides[face]
        boxes.append(turn(model, quarter) if connected else turn(PANE_NOSIDE, nosides[face]))
    return boxes


def wall(sides: str, post: bool = True, tall: str = "") -> list[Box]:
    quarters = {"n": 0, "e": 1, "s": 2, "w": 3}
    return ([WALL_POST] if post else []) + [
        turn(WALL_SIDE_TALL if d in tall else WALL_SIDE, quarters[d]) for d in sides]


def fence(sides: str) -> list[Box]:
    quarters = {"n": 0, "e": 1, "s": 2, "w": 3}
    return [FENCE_POST] + [turn(rail, quarters[d]) for d in sides for rail in FENCE_SIDE]


# --- the central invariant: the space never changes -------------------------------


def test_halves_side_by_side_become_one_block():
    given = [Box(0, 0, 0, 8, 16, 16), Box(8, 0, 0, 16, 16, 16)]
    assert merge(given) == (FULL_BLOCK,)


def test_stacked_halves_become_one_block():
    given = [SLAB, Box(0, 8, 0, 16, 16, 16)]
    assert merge(given) == (FULL_BLOCK,)


def test_a_step_is_never_filled_into_its_bounding_box():
    """Two boxes meeting only along an edge. Their bounds would add two empty octants.

    The failure this guards is the one that matters most downstream: a region the model did
    not have becomes something a player walks into once the tiler gives it collision.
    """
    given = [Box(0, 0, 0, 8, 8, 16), Box(8, 8, 0, 16, 16, 16)]
    merged = merge(given)
    assert merged == tuple(given)
    assert_same_space(given, merged)
    assert Box(0, 0, 0, 16, 16, 16) not in merged


def test_an_l_of_three_does_not_become_its_bounding_square():
    """
        +---+
        |   |
        +---+---+
        |   |   |
        +---+---+
    """
    given = [Box(0, 0, 0, 8, 16, 8), Box(8, 0, 0, 16, 16, 8), Box(0, 0, 8, 8, 16, 16)]
    merged = merge(given)
    assert len(merged) == 2
    assert_same_space(given, merged)


def test_offset_boxes_that_only_share_part_of_a_face_stay_separate():
    """
        +---+
        |   |
        +---+---+
            |   |
            +---+
    """
    given = [Box(0, 0, 0, 8, 16, 8), Box(4, 0, 8, 12, 16, 16)]
    merged = merge(given)
    assert len(merged) == 2
    assert_same_space(given, merged)


def test_overlapping_boxes_whose_union_is_a_box_become_it():
    given = [Box(0, 0, 0, 10, 16, 16), Box(6, 0, 0, 16, 16, 16)]
    assert merge(given) == (FULL_BLOCK,)


def test_duplicates_collapse_here_and_only_here():
    """The decomposer keeps coincident elements so that this is the one place they merge."""
    assert merge([SLAB, SLAB, SLAB]) == (SLAB,)


def test_a_contained_box_collapses_into_its_container():
    assert merge([FULL_BLOCK, Box(4, 4, 4, 12, 12, 12)]) == (FULL_BLOCK,)


def test_disconnected_boxes_are_left_alone():
    given = [Box(0, 0, 0, 4, 4, 4), Box(12, 12, 12, 16, 16, 16)]
    assert merge(given) == tuple(given)


def test_an_overlapping_plus_is_three_regions_not_two():
    """Two crossing bars occupy a plus. As a partition, a plus is three boxes.

    More boxes than went in, and correct: the output never overlaps, so an input that does
    can come back larger. Reporting two overlapping bars would put the centre in two regions.
    """
    given = [Box(0, 0, 6, 16, 4, 10), Box(6, 0, 0, 10, 4, 16)]
    merged = merge(given)
    assert len(merged) == 3
    assert_same_space(given, merged)


def test_an_authored_overlap_costs_regions():
    """Farmer's Delight's open rope fence gate: a hinge authored overlapping its post.

    Three boxes in, five out, and both of the extra regions are the price of the overlap:
    a partition has to cut one of the two around the other. Recorded because the next stage
    pays it in entities, and that should not come as a surprise there.
    """
    given = [Box(0, 0, 7, 2, 14, 9), Box(1, 4, 6, 3, 12, 10), Box(14, 0, 7, 16, 14, 9)]
    merged = merge(given)
    assert len(merged) == 5
    assert Box(1, 4, 6, 3, 12, 10) in merged, "the larger authored box is the one kept whole"
    assert_same_space(given, merged)


def test_fractional_coordinates_are_kept_exactly():
    given = [Box(0.5, 0, 0, 8, 16, 16), Box(8, 0, 0, 15.5, 16, 16)]
    assert merge(given) == (Box(0.5, 0, 0, 15.5, 16, 16),)


def test_zero_volume_boxes_are_kept_verbatim_and_never_merged():
    """A flat plane has no volume, so occupancy cannot see it -- and dropping it would delete
    a visible plane while every volume check still passed."""
    plane = Box(8, 0, 0, 8, 16, 16)
    merged = merge([Box(0, 0, 0, 8, 16, 16), Box(8, 0, 0, 16, 16, 16), plane, plane])
    assert merged == (FULL_BLOCK, plane, plane)


def test_nothing_in_is_nothing_out():
    assert merge([]) == ()


# --- the authored vanilla shapes --------------------------------------------------


@pytest.mark.parametrize("given, regions", [
    pytest.param([SLAB], 1, id="slab"),
    pytest.param(list(STAIRS), 2, id="stairs: an L in section is two"),
    pytest.param(list(OUTER_STAIRS), 2, id="outer stairs"),
    pytest.param(list(INNER_STAIRS), 3, id="inner stairs: a cube less one octant is three"),
])
def test_stairs_and_slabs(given, regions):
    merged = merge(given)
    assert len(merged) == regions
    assert_same_space(given, merged)


@pytest.mark.parametrize("given, regions", [
    pytest.param(pane(), 1, id="post alone: five coincident boxes are one"),
    pytest.param(pane(n=True), 1, id="dead end"),
    pytest.param(pane(n=True, s=True), 1, id="straight: post and both sides are one bar"),
    pytest.param(pane(n=True, e=True), 2, id="corner"),
    pytest.param(pane(n=True, e=True, s=True), 2, id="tee"),
    pytest.param(pane(n=True, e=True, s=True, w=True), 3, id="cross"),
])
def test_glass_pane(given, regions):
    """The permanent regression fixture: a pane is not cube + stair + slab + wall + fence.

    Every connection state is composed from vanilla's own multipart, coincident noside
    boxes included, and the merger has to find the bars without being told it is a pane.
    """
    merged = merge(given)
    assert len(merged) == regions
    assert_same_space(given, merged)


@pytest.mark.parametrize("given, regions", [
    pytest.param(wall(""), 1, id="post"),
    pytest.param(wall("n"), 2, id="post and an arm"),
    pytest.param(wall("ns", post=False), 1, id="straight without a post: one bar"),
    pytest.param(wall("ns"), 3, id="straight with a post: the arms are lower than the post"),
    pytest.param(wall("ns", post=False, tall="ns"), 1, id="tall straight"),
    pytest.param(wall("nesw"), 5, id="crossing: post and four arms"),
])
def test_wall(given, regions):
    merged = merge(given)
    assert len(merged) == regions
    assert_same_space(given, merged)


def test_a_wall_crossing_keeps_its_post_whole():
    """The authored post survives; the arms lose only the part inside it."""
    merged = merge(wall("nesw"))
    assert WALL_POST in merged


@pytest.mark.parametrize("given, regions", [
    pytest.param(fence(""), 1, id="post"),
    pytest.param(fence("n"), 3, id="post and two rails"),
    pytest.param(fence("ns"), 5, id="straight"),
    pytest.param(fence("nesw"), 9, id="crossing"),
])
def test_fence(given, regions):
    """The rails are separated by a gap, so no two rails ever merge across it."""
    merged = merge(given)
    assert len(merged) == regions
    assert_same_space(given, merged)


# --- properties over random shapes ----------------------------------------------------


def _random_boxes(rng: random.Random, count: int, cells: int = 4) -> list[Box]:
    step = 16 // cells
    out = []
    for _ in range(count):
        lo = [rng.randrange(cells) for _ in range(3)]
        hi = [rng.randrange(l + 1, cells + 1) for l in lo]
        out.append(Box(*(v * step for v in lo), *(v * step for v in hi)))
    return out


def _random_partition(rng: random.Random) -> list[Box]:
    """Disjoint boxes: a random box set, carved into unit cells and kept as cells."""
    cells = {c for b in _random_boxes(rng, rng.randrange(1, 4))
             for c in itertools.product(range(b.x0 // 4, b.x1 // 4),
                                        range(b.y0 // 4, b.y1 // 4),
                                        range(b.z0 // 4, b.z1 // 4))}
    return [Box(x * 4, y * 4, z * 4, x * 4 + 4, y * 4 + 4, z * 4 + 4) for x, y, z in sorted(cells)]


@pytest.mark.parametrize("seed", range(150))
def test_random_overlapping_boxes_keep_their_space(seed):
    rng = random.Random(seed)
    given = _random_boxes(rng, rng.randrange(1, 7))
    assert_same_space(given, merge(given))


@pytest.mark.parametrize("seed", range(60))
def test_a_partition_never_comes_back_larger(seed):
    rng = random.Random(seed)
    given = _random_partition(rng)
    merged = merge(given)
    assert len(merged) <= len(given)
    assert_same_space(given, merged)


@pytest.mark.parametrize("seed", range(30))
def test_input_order_does_not_matter(seed):
    rng = random.Random(seed)
    given = _random_boxes(rng, 5)
    expected = merge(given)
    for _ in range(5):
        rng.shuffle(given)
        assert merge(given) == expected


def test_merging_is_idempotent():
    """A merged set has nothing left to merge."""
    rng = random.Random(7)
    for _ in range(40):
        once = merge(_random_boxes(rng, 6))
        assert merge(once) == once


# --- every block of both mods ---------------------------------------------------------

CMB = pathlib.Path(
    "/mnt/storage/repos/Cinchs_Missing_Blocks_Paperized/server/plugins/CraftEngine"
    "/resources/cinchsmissingblocks/resourcepack/assets/cinchsmissingblocks"
)
FD = pathlib.Path("/mnt/storage/devops/FarmersDelight")
VANILLA = pathlib.Path("/tmp/opencode/assets/minecraft/models")


@pytest.mark.skipif(not (CMB.exists() and FD.exists() and VANILLA.exists()),
                    reason="real mod sources not present")
def test_every_model_of_both_mods_keeps_its_space():
    """Not a sample: every model any blockstate of either mod names, multipart parts too.

    Every model, not each blockstate's first: the first variant of a stair is one shape of
    five, and of a wall it is a post with no arms.
    """
    from paperized.analysis.geometry import _loader

    sources = [
        (CMB / "blockstates", [CMB / "models/block", CMB / "models", VANILLA]),
        (FD / "src/generated/resources/assets/farmersdelight/blockstates",
         [FD / "src/main/resources/assets/farmersdelight",
          FD / "src/generated/resources/assets/farmersdelight"]),
    ]
    measured = 0
    for blockstates, roots in sources:
        load = _loader(roots, VANILLA)
        refs: set[str] = set()
        for path in sorted(blockstates.glob("*.json")):
            state = json.loads(path.read_text())
            applied = list((state.get("variants") or {}).values())
            applied += [part["apply"] for part in state.get("multipart") or []]
            for entry in applied:
                refs |= {m["model"] for m in (entry if isinstance(entry, list) else [entry])}
        for ref in sorted(refs):
            try:
                geometry = decompose_ref(ref, load)
            except GeometryError:
                continue
            assert_same_space(list(geometry.boxes), list(merge(geometry.boxes)))
            measured += 1
    assert measured > 1000, f"only {measured} models measured; the sweep is not sweeping"


# --- what it must not know ------------------------------------------------------------


def test_merger_knows_nothing_about_families_carriers_or_runtime():
    """The boundary, asserted against the code rather than the prose (as for the decomposer).

    The module docstring names walls and tilers to disclaim them, so identifiers and
    non-docstring literals are scanned instead of raw text.
    """
    import paperized.merge as m

    tree = ast.parse(pathlib.Path(m.__file__).read_text())
    # The string node that *is* a module, class or function docstring, by identity.
    docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))
                  and ast.get_docstring(n) is not None}
    banned = {"craftengine", "shulker", "carrier", "slab", "stair", "pillar", "pane",
              "fence", "wall", "blockstate", "collision", "hitbox", "entity", "paper",
              "family", "minecraft"}

    offenders: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            offenders |= {w for w in banned if w in node.id.lower()}
        elif isinstance(node, ast.Attribute):
            offenders |= {w for w in banned if w in node.attr.lower()}
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue
            offenders |= {w for w in banned if w in node.value.lower()}
    assert not offenders, f"runtime vocabulary leaked into the merger: {offenders}"


def test_merger_imports_nothing_but_the_ir():
    import paperized.merge as m

    tree = ast.parse(pathlib.Path(m.__file__).read_text())
    local = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level}
    assert local == {"ir"}, f"the merger reaches beyond boxes: {local}"
