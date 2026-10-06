"""GeometryComposer: rotate placed geometries, then take their union as a list.

Rotation is checked against shapes the game itself draws, and composition against the one
rule that keeps it honest: it never merges. The end-to-end tests run the whole pipeline --
blockstate, decompose, rotate, compose, merge -- over vanilla's own wall and over every
multipart state of both mods.
"""

from __future__ import annotations

import ast
import collections
import json
import pathlib

import pytest

from paperized.analysis.geometry import measure_state
from paperized.blockstate import UNMENTIONED, is_multipart, states
from paperized.compose import CompositionError, compose, rotate
from paperized.decompose import GeometryError
from paperized.ir import Box, Geometry, OrientedBox
from paperized.merge import merge

from oracle import assert_same_space


def geo(*boxes, source="t"):
    return Geometry(tuple(boxes), source=source)


# --- rotation, against shapes the game draws -------------------------------------------


def test_y_90_takes_north_to_east():
    """A wall side is authored on the north; `y: 90` is the east side, touching x = 16."""
    (east,) = rotate(geo(Box(5, 0, 0, 11, 14, 8)), y=90).boxes
    assert east == Box(8, 0, 5, 16, 14, 11)


def test_stairs_facing_south_is_y_90():
    """Vanilla's stair model faces east (step at x 8..16); facing=south is `y: 90`, and a
    stair facing south has its step on the south half."""
    stairs = geo(Box(0, 0, 0, 16, 8, 16), Box(8, 8, 0, 16, 16, 16))
    assert rotate(stairs, y=90).boxes == (Box(0, 0, 0, 16, 8, 16), Box(0, 8, 8, 16, 16, 16))


def test_x_90_hangs_a_floor_button_where_a_north_facing_button_is():
    """The game's own shape for a wall button facing north is 5,6,14 -> 11,10,16, and its
    blockstate is the floor button model with `x: 90`."""
    (button,) = rotate(geo(Box(5, 0, 6, 11, 2, 10)), x=90).boxes
    assert button == Box(5, 6, 14, 11, 10, 16)


def test_x_turns_before_y():
    """The format turns x first. Turning y first lands this box somewhere else."""
    step = Box(0, 0, 0, 4, 2, 6)
    both = rotate(geo(step), x=90, y=90).boxes
    assert both == rotate(rotate(geo(step), x=90), y=90).boxes
    assert both != rotate(rotate(geo(step), y=90), x=90).boxes


def test_four_quarter_turns_are_the_identity_and_counts_never_change():
    shape = geo(Box(0, 0, 0, 16, 8, 16), Box(8, 8, 0, 16, 16, 16), Box(8, 8, 0, 16, 16, 16))
    turned = shape
    for _ in range(4):
        turned = rotate(turned, y=90)
        assert len(turned.boxes) == 3, "rotation never merges, drops or clips"
    assert turned.boxes == shape.boxes


def test_oriented_boxes_turn_with_the_rest():
    plane = OrientedBox(((0.0, 0.0, 8.0), (16.0, 0.0, 8.0), (0.0, 16.0, 8.0), (16.0, 16.0, 8.0)),
                        exact=False)
    turned = rotate(Geometry((), source="t", oriented=(plane,), exact=False), y=90)
    assert {c[0] for c in turned.oriented[0].corners} == {8.0}
    assert not turned.exact


def test_a_rotation_that_is_not_a_right_angle_raises():
    with pytest.raises(CompositionError):
        rotate(geo(Box(0, 0, 0, 1, 1, 1)), y=45)


# --- composition is union, not optimisation ---------------------------------------------


def test_composition_keeps_every_box_of_every_part():
    """Coincident and overlapping boxes survive composition; merging is the merger's job."""
    post = geo(Box(7, 0, 7, 9, 16, 9))
    noside = geo(Box(7, 0, 7, 9, 16, 9))
    arm = geo(Box(7, 0, 0, 9, 16, 8))
    composed = compose([post, noside, arm])
    assert collections.Counter(composed.boxes) == collections.Counter(
        [*post.boxes, *noside.boxes, *arm.boxes])


def test_composition_never_has_fewer_boxes_than_its_parts():
    parts = [geo(Box(0, 0, 0, 8, 16, 16)), geo(Box(8, 0, 0, 16, 16, 16))]
    assert len(compose(parts).boxes) == 2, "two halves of a cube stay two halves here"
    assert len(merge(compose(parts).boxes)) == 1, "...and become one in the merger"


def test_nothing_to_compose_raises():
    """An empty union looks exactly like a shape that occupies nothing."""
    with pytest.raises(CompositionError, match="no part applies"):
        compose([])


def test_a_part_without_geometry_raises():
    with pytest.raises(CompositionError, match="no geometry"):
        compose([geo(Box(0, 0, 0, 1, 1, 1)), Geometry((), source="unmeasured")])


def test_exactness_is_inherited():
    exact = geo(Box(0, 0, 0, 1, 1, 1))
    rounded = Geometry((Box(1, 1, 1, 2, 2, 2),), source="r", exact=False)
    assert not compose([exact, rounded]).exact


def test_composer_imports_only_the_ir_and_knows_no_blockstates():
    import paperized.compose as c

    tree = ast.parse(pathlib.Path(c.__file__).read_text())
    local = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level}
    assert local == {"ir"}
    docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))
                  and ast.get_docstring(n) is not None}
    banned = {"merge", "multipart", "variant", "when", "craftengine", "shulker", "carrier",
              "wall", "pane", "fence", "slab", "stair"}
    offenders = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            offenders |= {w for w in banned if w in node.id.lower()}
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            offenders |= {w for w in banned if w in node.value.lower()}
    assert not offenders, f"the composer knows more than geometry: {offenders}"


# --- the whole pipeline, on models written to disk --------------------------------------


def write(root: pathlib.Path, models: dict[str, dict]) -> list[pathlib.Path]:
    (root / "block").mkdir(parents=True)
    for name, model in models.items():
        (root / "block" / f"{name}.json").write_text(json.dumps(model))
    return [root]


def test_a_random_choice_of_rotated_cubes_is_one_shape(tmp_path):
    roots = write(tmp_path, {"cube": {"elements": [{"from": [0, 0, 0], "to": [16, 16, 16]}]}})
    blockstate = {"variants": {"": [{"model": "m:block/cube"}, {"model": "m:block/cube", "y": 90}]}}
    assert measure_state("b", blockstate, {}, roots).boxes == (Box(0, 0, 0, 16, 16, 16),)


def test_a_random_choice_between_different_shapes_raises(tmp_path):
    roots = write(tmp_path, {
        "low": {"elements": [{"from": [0, 0, 0], "to": [16, 8, 16]}]},
        "high": {"elements": [{"from": [0, 0, 0], "to": [16, 12, 16]}]},
    })
    blockstate = {"variants": {"": [{"model": "m:block/low"}, {"model": "m:block/high"}]}}
    with pytest.raises(GeometryError, match="no single geometry"):
        measure_state("b", blockstate, {}, roots)


def test_a_variant_rotation_is_applied(tmp_path):
    """The old first-model path ignored a variant's own y; composition applies it."""
    roots = write(tmp_path, {"side": {"elements": [{"from": [5, 0, 0], "to": [11, 14, 8]}]}})
    blockstate = {"variants": {"facing=east": {"model": "m:block/side", "y": 90}}}
    assert measure_state("b", blockstate, {"facing": "east"}, roots).boxes == (Box(8, 0, 5, 16, 14, 11),)


def test_a_state_that_draws_nothing_is_refused(tmp_path):
    roots = write(tmp_path, {"post": {"elements": [{"from": [4, 0, 4], "to": [12, 16, 12]}]}})
    blockstate = {"multipart": [{"when": {"up": "true"}, "apply": {"model": "m:block/post"}}]}
    with pytest.raises(GeometryError, match="no part applies"):
        measure_state("b", blockstate, {"up": UNMENTIONED}, roots)


# --- vanilla's wall, composed by the pipeline --------------------------------------------

VANILLA = pathlib.Path("/tmp/opencode/assets/minecraft/models")
CMB = pathlib.Path(
    "/mnt/storage/repos/Cinchs_Missing_Blocks_Paperized/server/plugins/CraftEngine"
    "/resources/cinchsmissingblocks/resourcepack/assets/cinchsmissingblocks"
)
FD = pathlib.Path("/mnt/storage/devops/FarmersDelight")
live = pytest.mark.skipif(not (CMB.exists() and FD.exists() and VANILLA.exists()),
                          reason="real mod sources not present")

FACES = {"north": (2, 0), "east": (0, 16), "south": (2, 16), "west": (0, 0)}


@live
def test_every_wall_arm_reaches_the_face_it_connects_to():
    """External truth: an arm connecting east touches the block's east face, and so on.

    Composed from CMB's real wall blockstate and vanilla's templates, so a wrong rotation
    direction anywhere -- resolver, composer, or the `y` it reads -- puts an arm on the
    wrong face and fails here.
    """
    blockstate = json.loads((CMB / "blockstates/andesite_brick_wall.json").read_text())
    roots = [CMB / "models/block", CMB / "models", VANILLA]
    base = {"up": UNMENTIONED, **{f: UNMENTIONED for f in FACES}}
    for face, (axis, value) in FACES.items():
        for height in ("low", "tall"):
            (arm,) = measure_state("wall", blockstate, {**base, face: height}, roots, VANILLA).boxes
            touches = arm.as_tuple()[axis + 3] if value == 16 else arm.as_tuple()[axis]
            assert touches == value, f"{face} {height} arm {arm} does not reach the {face} face"
            assert arm.height == (14 if height == "low" else 16)


@live
def test_the_pipeline_composes_what_the_hand_composed_fixtures_say():
    """test_merge composes walls by hand. The pipeline must agree, from the real files."""
    blockstate = json.loads((CMB / "blockstates/andesite_brick_wall.json").read_text())
    roots = [CMB / "models/block", CMB / "models", VANILLA]
    crossing = {"up": "true", **{f: "low" for f in FACES}}
    regions = merge(measure_state("wall", blockstate, crossing, roots, VANILLA).boxes)
    assert len(regions) == 5
    assert Box(4, 0, 4, 12, 16, 12) in regions, "the post survives whole"


@live
def test_every_multipart_state_of_both_mods_composes_and_merges():
    """Not a sample: every enumerated state of every multipart blockstate in both mods.

    The only refusal allowed is a state that draws nothing -- which for a wall is exactly
    one enumerated class per block, everything unmentioned, and never reachable in game.
    """
    sources = [
        (CMB / "blockstates", [CMB / "models/block", CMB / "models", VANILLA]),
        (FD / "src/generated/resources/assets/farmersdelight/blockstates",
         [FD / "src/main/resources/assets/farmersdelight",
          FD / "src/generated/resources/assets/farmersdelight"]),
    ]
    composed = empty = blocks = 0
    checked: set[tuple[Box, ...]] = set()
    for blockstates, roots in sources:
        for path in sorted(blockstates.glob("*.json")):
            blockstate = json.loads(path.read_text())
            if not is_multipart(blockstate):
                continue
            blocks += 1
            for state in states(blockstate):
                try:
                    geometry = measure_state(path.stem, blockstate, state, roots, VANILLA)
                except GeometryError as exc:
                    assert "no part applies" in str(exc), exc
                    empty += 1
                    continue
                composed += 1
                # 108 walls share vanilla's templates, so most shapes recur; check each once.
                if geometry.boxes not in checked:
                    checked.add(geometry.boxes)
                    assert_same_space(list(geometry.boxes), list(merge(geometry.boxes)))
    assert blocks == 116, f"expected CMB's 114 and FD's 2 multipart blockstates, got {blocks}"
    assert composed > 10_000
    assert empty == 108, "one empty class per CMB wall, and nothing else draws nothing"
