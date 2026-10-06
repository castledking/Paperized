"""BoxDecomposer: resolved model -> IR geometry. One question, asked correctly.

The interesting tests here are the ones that fail. Each corresponds to a real shape in
Farmer's Delight or a real trap in the model format, and each of the first four was caught
by cross-checking the decomposer against the old measurement path over every block of both
mods -- not by writing a test and watching it pass.
"""

from __future__ import annotations

import pathlib

import pytest

from paperized.decompose import (
    GeometryError,
    decompose,
    decompose_ref,
    resolve,
)
from paperized.ir import FULL_BLOCK, Box


def loader(*models: tuple[str, dict]):
    table = dict(models)
    return lambda ref: table.get(ref)


# --- resolution --------------------------------------------------------------


def test_empty_elements_continue_to_the_parent():
    """Empty-element models are pure indirection, and FD uses them as such."""
    g = decompose_ref(
        "mod:block/leaf",
        loader(
            ("mod:block/leaf", {"elements": [], "parent": "mod:block/real"}),
            ("mod:block/real", {"elements": [{"from": [0, 0, 0], "to": [4, 4, 4]}]}),
        ),
    )
    assert g.boxes == (Box(0, 0, 0, 4, 4, 4),)


def test_parent_chain_walks_to_the_element_bearing_model():
    g = decompose_ref(
        "mod:block/a",
        loader(
            ("mod:block/a", {"parent": "mod:block/b"}),
            ("mod:block/b", {"parent": "mod:block/c"}),
            ("mod:block/c", {"elements": [{"from": [0, 0, 0], "to": [8, 8, 8]}]}),
        ),
    )
    assert g.boxes == (Box(0, 0, 0, 8, 8, 8),)
    assert g.source.count("->") == 2, "the whole chain is recorded for diagnostics"


def test_missing_model_raises_and_names_the_chain():
    with pytest.raises(GeometryError) as exc:
        decompose_ref("mod:block/gone", loader())
    assert "mod:block/gone" in str(exc.value)


def test_bare_model_that_is_not_the_vanilla_cube_raises():
    """A model with neither elements nor parent defines nothing. That is not a cube.

    The failure this prevents is large: Farmer's Delight's `canvas_sign` is exactly this --
    textures only -- and treating it as a cube fabricated a full block for 68 signs.
    """
    with pytest.raises(GeometryError, match="not minecraft:block/cube"):
        decompose_ref("mod:block/canvas_sign", loader(("mod:block/canvas_sign", {"textures": {}})))


def test_the_vanilla_cube_is_inheritable_and_is_a_full_block():
    """The one model with no elements and no parent that *does* mean a full cube.

    A format fact rather than an assumption: `minecraft:block/cube` is what every vanilla
    cube's geometry resolves to.
    """
    g = decompose_ref(
        "mod:block/crate",
        loader(
            ("mod:block/crate", {"parent": "minecraft:block/cube"}),
            ("minecraft:block/cube", {"textures": {"all": "block/stone"}}),
        ),
    )
    assert g.boxes == (FULL_BLOCK,)


def test_parent_cycle_is_reported_not_looped_forever():
    with pytest.raises(GeometryError, match="exceeded"):
        decompose_ref(
            "mod:block/a",
            loader(
                ("mod:block/a", {"parent": "mod:block/b"}),
                ("mod:block/b", {"parent": "mod:block/a"}),
            ),
        )


# --- rotation ----------------------------------------------------------------


def test_right_angle_rotation_is_an_exact_integer_permutation():
    """90 degrees about y moves a 4-wide plate to the far side, with no float involved."""
    g = decompose_ref(
        "mod:block/rot",
        loader(
            (
                "mod:block/rot",
                {"elements": [
                    {"from": [0, 0, 0], "to": [4, 16, 16],
                     "rotation": {"angle": 90, "axis": "y", "origin": [8, 8, 8]}}
                ]},
            )
        ),
    )
    assert g.boxes == (Box(0, 0, 12, 16, 16, 16),)
    assert g.exact, "a right angle on integral coordinates stays exact"


def test_rotation_is_applied_not_ignored():
    """The decomposer's predecessor ignored `rotation` and reported unrotated boxes.

    FD has 35 elements rotated by +-22.5 or +-45 degrees. Reading from/to and stopping
    yields a different shape under the right name, with no error anywhere.
    """
    unrotated = decompose_ref(
        "mod:block/p", loader(("mod:block/p", {"elements": [{"from": [0, 0, 0], "to": [4, 16, 16]}]}))
    )
    rotated = decompose_ref(
        "mod:block/p",
        loader(
            ("mod:block/p", {"elements": [
                {"from": [0, 0, 0], "to": [4, 16, 16],
                 "rotation": {"angle": 90, "axis": "y", "origin": [8, 8, 8]}}
            ]})
        ),
    )
    assert unrotated.boxes != rotated.boxes


def test_rescale_rotates_about_the_element_centre_not_the_origin():
    """`rescale: true` means "pivot on my own middle", and it moves the element if ignored.

    Vanilla implements it by translating the element so its midpoint sits on the origin and
    then rotating. Honouring the origin literally instead shifts the box whenever the origin
    is not already its centre -- which is the normal case, and silent.

    Asserted via the centroid, because that is what rescale actually guarantees. A 90-degree
    turn of an 8x4 footprint legitimately changes the footprint to 4x8; what must not change
    is where the element sits.
    """
    element = {
        "from": [4, 4, 0], "to": [12, 12, 4],
        "rotation": {"angle": 90, "axis": "y", "origin": [8, 8, 0], "rescale": True},
    }
    rescaled = decompose_ref("mod:block/r", loader(("mod:block/r", {"elements": [element]})))
    without = dict(element)
    without["rotation"] = dict(element["rotation"], rescale=False)
    literal = decompose_ref("mod:block/r", loader(("mod:block/r", {"elements": [without]})))

    def centre(box: Box) -> tuple[float, ...]:
        x0, y0, z0, x1, y1, z1 = box.as_tuple()
        return ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)

    assert centre(rescaled.boxes[0]) == centre(Box(4, 4, 0, 12, 12, 4)), (
        "rescaled rotation must leave the element's centroid where it was"
    )
    assert centre(literal.boxes[0]) != centre(Box(4, 4, 0, 12, 12, 4)), (
        "ignoring rescale should displace the element -- if it did not, this fixture would "
        "not be testing rescale at all"
    )
    assert literal.boxes[0] != rescaled.boxes[0]


def test_non_right_angle_rotation_is_kept_oriented_r_than_projected():
    """A 45-degree plane is not an axis-aligned box, so it must not be reported as one.

    FD's `cabbages` is two thin planes crossed at 45 degrees. Projected to axis-aligned
    bounds, both collapse to the same 10x16x10 box -- reporting a nearly solid block where
    the truth is two flat sheets. Two oriented boxes survive that.
    """
    g = decompose_ref(
        "mod:block/cabbages",
        loader(
            (
                "mod:block/cabbages",
                {"elements": [
                    {"from": [0.8, -1, 8], "to": [15.2, 15, 8],
                     "rotation": {"angle": 45, "axis": "y", "origin": [8, 8, 8], "rescale": True}},
                    {"from": [8, -1, 0.8], "to": [8, 15, 15.2],
                     "rotation": {"angle": 45, "axis": "y", "origin": [8, 8, 8], "rescale": True}},
                ]},
            )
        ),
    )
    assert g.boxes == (), "a rotated plane has no axis-aligned box"
    assert len(g.oriented) == 2, "both planes survive distinctly"
    assert len({o.bounds for o in g.oriented}) == 1, (
        "their bounds do coincide -- which is exactly why projecting them would lose one"
    )
    assert not g.exact


def test_fractional_coordinates_flag_the_geometry_inexact():
    g = decompose_ref(
        "mod:block/f",
        loader(("mod:block/f", {"elements": [{"from": [0.5, 0, 0], "to": [15.5, 16, 16]}]})),
    )
    assert not g.exact
    assert g.resolved


# --- non-merging -------------------------------------------------------------


def test_duplicate_boxes_are_both_kept():
    """Two authored elements stay two, even when their geometry is identical.

    De-duplicating looks free and is not: it destroys the difference between "one shape
    here" and "two shapes that happen to coincide", which no later stage could recover.
    """
    element = {"from": [0, 0, 0], "to": [4, 4, 4]}
    g = decompose_ref("mod:block/d", loader(("mod:block/d", {"elements": [element, dict(element)]})))
    assert len(g.boxes) == 2


def test_boxes_are_sorted_for_determinism():
    a = {"from": [8, 0, 8], "to": [12, 4, 12]}
    b = {"from": [0, 0, 0], "to": [4, 4, 4]}
    g = decompose_ref("mod:block/s", loader(("mod:block/s", {"elements": [a, b]})))
    assert g.boxes == (Box(0, 0, 0, 4, 4, 4), Box(8, 0, 8, 12, 4, 12))


def test_decompose_is_deterministic():
    model = {"elements": [
        {"from": [0, 0, 0], "to": [4, 4, 4]},
        {"from": [4, 4, 0], "to": [8, 8, 4], "rotation": {"angle": 90, "axis": "z", "origin": [8, 8, 4]}},
    ]}
    load = loader(("mod:block/det", model))
    runs = {decompose_ref("mod:block/det", load) for _ in range(25)}
    assert len(runs) == 1


# --- what it must not do -----------------------------------------------------


def test_display_transforms_are_not_applied():
    """`display` positions a model in a GUI or in hand, not in the world."""
    g = decompose_ref(
        "mod:block/d",
        loader(
            (
                "mod:block/d",
                {
                    "display": {"gui": {"rotation": [45, 45, 0], "scale": [2, 2, 2]}},
                    "elements": [{"from": [0, 0, 0], "to": [4, 4, 4]}],
                },
            )
        ),
    )
    assert g.boxes == (Box(0, 0, 0, 4, 4, 4),)


def test_decomposer_knows_nothing_about_families_carriers_or_runtime():
    """The boundary, asserted against the code rather than the prose.

    Words like "carrier" appear in the module docstring precisely to disclaim them, so
    scanning raw text would fail on its own documentation. This inspects identifiers and
    non-docstring string literals instead, so it catches vocabulary that has leaked into
    logic while ignoring vocabulary used to say what the module does not do.

    A decomposer that knows what a slab or a note_block is stops answering one question and
    starts encoding a lookup table -- which is exactly what the clustering analysis showed
    would need an entry per singleton.
    """
    import ast
    import paperized.decompose as d

    tree = ast.parse(pathlib.Path(d.__file__).read_text())
    module_doc = ast.get_docstring(tree) or ""

    banned = {"craftengine", "shulker", "carrier", "villar", "slab", "pillar", "pane",
              "fence", "blockstate", "collision"}

    offenders: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            offenders |= {w for w in banned if w in node.id.lower()}
        elif isinstance(node, ast.Attribute):
            offenders |= {w for w in banned if w in node.attr.lower()}
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.strip() == module_doc.strip():
                continue
            offenders |= {w for w in banned if w in node.value.lower()}

    # "collision" is legitimately named in the GeometryError messages, which is how we
    # *refuse* that responsibility. Everything else must be absent.
    hard = banned - {"collision"}
    assert not (offenders & hard), f"runtime vocabulary leaked into the decomposer: {offenders & hard}"

    assert "no collision semantics" in (d.__doc__ or "").lower()
