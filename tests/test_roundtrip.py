"""The invariant the whole compiler rests on:

        measured geometry  ==  IR visual geometry

Not byte-for-byte serialization. Semantic identity, checked against **real** files from
both mods rather than hand-written ones, because a hand-written fixture cannot prove the
model chain was walked correctly.

If this fails, every downstream stage is reasoning about geometry that measurement never
saw. That is the failure the duplicate-`Box` bug actually caused, which is why it is a
test and not a convention.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from paperized.analysis.geometry import (
    measure_blockstate,
    properties_from,
    collision_from,
)
from paperized.ir import Block, BlockGeometry, Geometry, Strategy, derive

CMB = pathlib.Path(
    "/mnt/storage/repos/Cinchs_Missing_Blocks_Paperized/server/plugins/CraftEngine"
    "/resources/cinchsmissingblocks/resourcepack/assets/cinchsmissingblocks"
)
FD = pathlib.Path("/mnt/storage/devops/FarmersDelight")
FD_ROOTS = [
    FD / "src/main/resources/assets/farmersdelight",
    FD / "src/generated/resources/assets/farmersdelight",
]
VANILLA = pathlib.Path("/tmp/opencode/assets/minecraft/models")

pytestmark = pytest.mark.skipif(
    not (CMB.exists() and FD.exists() and VANILLA.exists()),
    reason="real mod sources not present",
)


def cmb_measure(name: str):
    state = json.loads((CMB / "blockstates" / f"{name}.json").read_text())
    roots = [CMB / "models/block", CMB / "models", VANILLA]
    return measure_blockstate(name, state, roots, VANILLA)


def fd_measure(name: str):
    state = json.loads((FD_ROOTS[1] / "blockstates" / f"{name}.json").read_text())
    return measure_blockstate(name, state, FD_ROOTS, VANILLA)


# --- the invariant ------------------------------------------------------------


def test_measured_geometry_reaches_the_ir_unchanged_cmb():
    """CMB slab: a 16x8x16 box must survive measurement, and must never read as a cube.

    The single most valuable regression in this file. The slab is the case that reported
    itself as a full cube before, and a full cube silently becomes a carrier that cannot
    hold the slab's shape.
    """
    visual, props, multipart = cmb_measure("andesite_brick_slab")

    block = Block(
        id="cinchsmissingblocks:andesite_brick_slab",
        properties=props,
        geometry=BlockGeometry(visual=visual, collision=visual, collision_source="visual"),
        strategy=Strategy.FURNITURE,
    )

    # round-trip: what measurement produced is what the IR carries
    assert block.geometry.visual.boxes == visual.boxes
    assert block.geometry.visual.boxes != ()

    # and the boxes are the ones we expect, not merely self-consistent
    assert block.geometry.visual.boxes[0].as_tuple() == (0, 0, 0, 16, 8, 16)
    assert not block.geometry.visual_caps.full_cube
    assert not multipart


def test_pillar_visual_and_collision_are_independent():
    """Both are full cubes; they must still be independent fields.

    The pillar's model resolves to a full cube (cube_column inherits cube) and its
    collision comes from a note_block carrier -- also a full cube. Equal *values* here are
    the trap: a pipeline that collapsed the two fields would pass a weaker test here while
    failing on every block where they differ.

    The slab above is that case, which is why both assertions live in this file.
    """
    visual, props, _ = cmb_measure("andesite_brick_pillar")

    collision, source = collision_from(visual, carrier="minecraft:note_block[instrument=banjo]")
    geometry = BlockGeometry(visual=visual, collision=collision, collision_source=source)

    assert geometry.visual_caps.full_cube
    assert geometry.collision_caps.full_cube
    assert not geometry.differs, "both are full cubes, so differs must be False"

    # independent objects: mutating one's source cannot reach the other
    assert geometry.visual is not geometry.collision
    assert geometry.visual.source != geometry.collision.source


def test_multipart_geometry_survives_the_roundtrip_cmb():
    """Wall, fence, and pane: multipart sources, never carriers.

    If multipart were lost in transit, these would measure as empty and look merely
    unresolved rather than actively unsafe to carry.
    """
    # No skipping. A guard that quietly `continue`s when a fixture is missing turns a
    # multipart test into one that asserts almost nothing and still passes -- the same
    # "green but vacuous" trap as the silent UNKNOWN above.
    expected = {
        "andesite_brick_wall",
        "red_nether_brick_fence",
        "tinted_glass_pane",
    }
    for name in sorted(expected):
        assert (CMB / "blockstates" / f"{name}.json").is_file(), f"missing fixture {name}"
        visual, props, multipart = cmb_measure(name)
        assert multipart, f"{name} must be recognised as multipart"
        assert visual.boxes != (), f"{name} must resolve to real geometry"
        assert derive(visual, multipart).multi_part


def test_bespoke_box_lists_survive_without_a_family():
    """FD apple_pie and cooking_pot: a box list is a complete description.

    Nothing in the IR names these. That is the test: the geometry is preserved and the
    representation invents no category to put them in.
    """
    for name in ("apple_pie", "cooking_pot"):
        visual, props, _ = fd_measure(name)

        assert visual.boxes != (), f"{name} must resolve to real geometry"
        assert visual.resolved

        block = Block(
            id=f"farmersdelight:{name}",
            properties=props,
            geometry=BlockGeometry(visual=visual, collision=visual, collision_source="visual"),
            strategy=Strategy.UNRESOLVED,
        )
        assert block.geometry.visual.boxes == visual.boxes
        assert not visual_caps_is_cube(visual), f"{name} is not a cube"


def visual_caps_is_cube(geometry: Geometry) -> bool:
    return derive(geometry).full_cube


# --- properties ---------------------------------------------------------------


def test_blockstate_yields_names_but_not_values():
    """The asymmetry is load-bearing, and must not be papered over.

    Names are in the variant keys. Value sets live in the mod's Java registration. So
    arity is None -- unknown -- and never 0, because 0 states would read as "needs no
    carrier", the exact inverse of the truth.
    """
    props = properties_from({"variants": {"facing=north,open=true": {"model": "mod:block/a"}}})

    assert props.names == ("facing", "open")
    assert not props.measured
    assert props.arity is None


# --- the boundary that must not have appeared yet ----------------------------


def test_measurement_does_not_decide_carriers_or_families():
    """Measurement stops at geometry. No carrier choice, no family, no CraftEngine.

    `collision_from` takes a carrier *given to it*; it does not choose one. Keeping the
    choice out of here is what stops the compiler becoming a family lookup table, and it is
    what leaves BoxDecomposer with a single job.
    """
    import paperized.analysis.geometry as g

    source = (g.__doc__ or "") + pathlib.Path(g.__file__).read_text()
    for banned in ("craftengine", "shulker", "CarrierEligibility", "vanilla_carriers"):
        assert banned.lower() not in source.lower(), f"{banned} must not appear in measurement"
