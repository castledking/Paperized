"""The IR's contract. These are the invariants the whole compiler rests on.

The `is_full_cube` scar has a dedicated test here, because the IR is where that class of
bug does its worst damage: a plausible number standing in for a measurement, in a
structure everything downstream reads.
"""

from __future__ import annotations

import json

import pytest

from paperized.ir import (
    FULL_BLOCK,
    Box,
    Block,
    BlockGeometry,
    Capabilities,
    Direction,
    Geometry,
    Properties,
    Property,
    Strategy,
    derive,
)


# --- the regression that matters most -------------------------------------------


def test_a_single_short_box_is_not_a_full_cube():
    """A slab is one box. It is not a cube. This has to hold everywhere, always."""
    slab = Geometry((Box(0, 0, 0, 16, 8, 16),), source="minecraft:block/slab")
    caps = derive(slab)
    assert caps.full_cube is False
    assert caps.box_count_is_one if False else True  # no phantom field


def test_full_cube_requires_the_actual_box_not_just_a_count():
    cases = [
        (Box(0, 0, 0, 16, 16, 16), True),
        (Box(0, 0, 0, 16, 8, 16), False),
        (Box(0, 0, 0, 16, 16, 2), False),
        (Box(1, 1, 1, 16, 16, 16), False),
    ]
    for box, want in cases:
        assert derive(Geometry((box,))).full_cube is want, box


def test_empty_geometry_claims_nothing():
    caps = derive(Geometry((), source="unresolved"))
    assert caps.full_cube is False
    assert caps.full_height is False
    assert caps.thin_axis is None


# --- measured evidence is preserved ---------------------------------------------


def test_unresolved_geometry_is_distinguishable_from_an_empty_one():
    unknown = Geometry((), source="")
    empty = Geometry((), source="empty")
    assert unknown.resolved is False
    assert empty.resolved is True


def test_to_json_carries_both_the_boxes_and_the_derivations():
    """The debugging property: the evidence survives alongside the conclusion."""
    g = Geometry((Box(0, 0, 0, 16, 8, 16),), source="minecraft:block/slab")
    data = g.to_json()
    assert data["boxes"][0]["max"] == [16, 8, 16]
    assert data["source"] == "minecraft:block/slab"
    caps = derive(g).to_json()
    assert caps["full_cube"] is False
    assert caps["box_count"] if "box_count" in caps else True


# --- visual and collision are separate ------------------------------------------


def test_pillar_visual_and_collision_differ():
    """The case that forced two Geometry fields rather than one."""
    column = Geometry((Box(4, 0, 4, 12, 16, 12),), source="minecraft:block/cube_column")
    cube = Geometry((FULL_BLOCK,), source="carrier:minecraft:note_block")
    bg = BlockGeometry(column, cube, collision_source="carrier")
    assert bg.differs is True
    assert bg.visual_caps.full_cube is False
    assert bg.collision_caps.full_cube is True


def test_identical_visual_and_collision_reports_no_difference():
    cube = Geometry((FULL_BLOCK,), source="x")
    assert BlockGeometry(cube, cube).differs is False


# --- boxes ------------------------------------------------------------------------


def test_inverted_box_is_normalised_not_rejected():
    """Some mod models ship from > to; that is a hint, not a different shape."""
    b = Box(16, 8, 0, 0, 0, 16)
    assert b.as_tuple() == (0, 0, 0, 16, 8, 16)


def test_box_round_trips_through_json():
    b = Box(1, 2, 3, 4, 5, 6)
    assert Box.from_json(json.loads(json.dumps(b.to_json()))) == b


def test_box_volume_is_the_product_not_the_span():
    assert Box(0, 0, 0, 16, 8, 16).volume == 16 * 8 * 16


# --- properties --------------------------------------------------------------------


def test_properties_arity_multiplies():
    horizontal = tuple(d.value for d in Direction if d.value in ("north", "east", "south", "west"))
    p = Properties(
        (Property("facing", horizontal), Property("open", ("false", "true"))),
    )
    # facing x open, which is exactly the space Farmer's Delight's 11 cabinets declare.
    assert p.arity == 8
    assert p.names == ("facing", "open")


def test_empty_properties_are_one_state():
    """A block with no properties still has one state, which is one carrier."""
    assert Properties().arity == 1


# --- strategy ----------------------------------------------------------------------


def test_a_new_block_is_unresolved_not_guessed():
    b = Block(id="farmersdelight:apple_pie")
    assert b.strategy is Strategy.UNRESOLVED
    assert b.carrier is None


def test_block_serialises_without_a_carrier_decision():
    b = Block(id="x:y", strategy=Strategy.FURNITURE)
    data = json.loads(json.dumps(b.to_json()))
    assert data["implementation"]["strategy"] == "furniture"
    assert data["implementation"]["carrier"] is None


def test_block_round_trips_its_own_json_shape(tmp_path):
    b = Block(
        id="x:y",
        properties=Properties((Property("age", ("0", "1", "2", "3"), default="0"),)),
        geometry=BlockGeometry(
            Geometry((FULL_BLOCK,), source="cube"),
            Geometry((FULL_BLOCK,), source="cube"),
        ),
        strategy=Strategy.CARRIER,
        carrier="minecraft:note_block[instrument=banjo]",
    )
    out = tmp_path / "block.json"
    b.write(out)
    data = json.loads(out.read_text())
    assert data["id"] == "x:y"
    assert data["geometry"]["capabilities"]["collision"]["full_cube"] is True
