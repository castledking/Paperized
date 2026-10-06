"""The compiled artifact: the contract a backend reads.

Three things this file holds the artifact to, each of which is a decision rather than an
implementation detail:

1. **Geometry is per state.** Not per block. FD's stuffed pumpkin is decided two different
   ways, and a ``block -> collision`` shape cannot say so.
2. **Nothing backend-specific is in it.** No shulker, no furniture, no carrier, no
   CraftEngine. Collision is cubes and a count; what a runtime hangs off a cube is that
   runtime's business, and it is the only reason one package can feed three backends.
3. **Nothing is dropped silently.** A state that could not compile is present, with a
   machine-readable reason.
"""

from __future__ import annotations

import ast
import json
import pathlib

import pytest

from paperized.artifact import (
    COMPILED,
    FORMAT,
    NO_GEOMETRY,
    VERSION,
    ArtifactError,
    cube_json,
    definitions_json,
    read_package,
    write_package,
)
from paperized.collision import Policy
from paperized.compile import PolicyTable, compile_block, compile_mod
from paperized.tile import Cube, CubeLimits

CMB = pathlib.Path(
    "/mnt/storage/repos/Cinchs_Missing_Blocks_Paperized/server/plugins/CraftEngine"
    "/resources/cinchsmissingblocks/resourcepack/assets/cinchsmissingblocks"
)
FD = pathlib.Path("/mnt/storage/devops/FarmersDelight")
VANILLA = pathlib.Path("/tmp/opencode/assets/minecraft/models")
SHULKER = CubeLimits(1, 256)
ROOTS = [CMB / "models/block", CMB / "models", VANILLA]
ROOTS_FD = [FD / "src/main/resources/assets/farmersdelight",
            FD / "src/generated/resources/assets/farmersdelight"]
REPO = pathlib.Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(
    not (CMB.exists() and VANILLA.exists()), reason="the real CMB pack is not present"
)

TABLE = PolicyTable(rules=(({"max_thickness": 1}, "none", "0"), ({}, "visual", "1")))

_MOD: list = []


def cmb_definitions():
    if not _MOD:
        _MOD.extend(compile_mod(CMB / "blockstates", ROOTS, VANILLA, TABLE, SHULKER,
                                materialise_cubes=True))
    return definitions_json(_MOD, "cinchsmissingblocks")


# --- the envelope -------------------------------------------------------------


def test_the_artifact_is_versioned_and_names_itself():
    document = cmb_definitions()
    assert document["format"] == FORMAT
    assert document["version"] == VERSION
    assert isinstance(document["version"], int), "a version a backend cannot compare is useless"


def test_a_backend_reading_an_unknown_version_is_refused(tmp_path, monkeypatch):
    write_package(tmp_path, _MOD, "cinchsmissingblocks")
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["version"] = VERSION + 1
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ArtifactError, match="version"):
        read_package(tmp_path)


def test_a_backend_refuses_a_package_that_is_not_ours(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"format": "something-else", "version": 1}))
    with pytest.raises(ArtifactError, match="not a paperized package"):
        read_package(tmp_path)


def test_the_package_is_definitions_and_assets(tmp_path):
    written = write_package(tmp_path, _MOD, "cinchsmissingblocks", asset_dirs=[CMB / "models"])
    assert (tmp_path / "manifest.json").is_file()
    assert (tmp_path / "definitions.json").is_file()
    assert written["asset_files"] > 0
    assert read_package(tmp_path)["manifest"]["format"] == FORMAT


# --- geometry is per state ----------------------------------------------------


def test_geometry_lives_on_states_not_blocks():
    document = cmb_definitions()
    for block in document["blocks"].values():
        assert "states" in block
        assert "visual" not in block and "collision" not in block, (
            "block-level geometry cannot represent a block decided two ways"
        )


def test_a_mixed_block_keeps_both_policies_in_its_states():
    """The stuffed pumpkin, in the artifact rather than in a report line.

    Per-state collision is what makes this representable at all: 12 flat states compile as
    ``none`` and 8 taller ones as ``visual``, and a consumer reading only the derived
    summary would think it had one answer.
    """
    document = definitions_json(
        compile_mod(ROOTS_FD[1] / "blockstates", ROOTS_FD, VANILLA, TABLE, SHULKER,
                    materialise_cubes=True),
        "farmersdelight")
    block = document["blocks"]["farmersdelight:stuffed_pumpkin_block"]
    policies = {s["collision"]["policy"] for s in block["states"] if "collision" in s}
    assert policies == {"none", "visual"}
    assert block["derived"]["mixed"] is True
    assert block["derived"]["cubes_worst"] > 0, "mixed must not read as free"


def test_derived_is_derived_and_says_so():
    block = cmb_definitions()["blocks"]["cinchsmissingblocks:andesite_brick_stairs"]
    assert set(block["derived"]) >= {"policies", "mixed", "cubes_worst", "state_count"}
    # every derived figure must be recomputable from states, or it is not derived
    assert block["derived"]["state_count"] == len(block["states"])
    assert block["derived"]["compiled"] == sum(1 for s in block["states"]
                                               if s["status"] == COMPILED)


def test_states_record_visual_and_collision_separately():
    document = cmb_definitions()
    state = document["blocks"]["cinchsmissingblocks:andesite_brick_pillar"]["states"][0]
    assert state["status"] == COMPILED
    assert state["visual"]["boxes"], "visual geometry is what the model draws"
    assert state["collision"]["cubes"], "collision is what was chosen"
    assert state["visual"] is not state["collision"]


# --- nothing backend-specific -------------------------------------------------


BANNED = {"shulker", "furniture", "craftengine", "bukkit", "paper", "carrier",
          "note_block", "minecraft", "entity", "modrinth", "hitbox"}


def banned_in(text: str) -> set:
    """Which banned words appear, on word boundaries.

    Plain substring matching reports "paper" inside "paperized", which is this project's own
    name and appears in its format field -- so the test would fail on every artifact it was
    written to protect.
    """
    import re

    return {b for b in BANNED if re.search(rf"\b{re.escape(b)}\b", text, re.I)}


def test_the_artifact_names_no_runtime_implementation():
    """Read as a stream of JSON values, so strings *and* keys are checked."""
    document = cmb_definitions()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from walk(value)
        elif isinstance(node, list):
            for value in node:
                yield from walk(value)
        elif isinstance(node, str):
            yield node

    offenders = {b for text in walk(document) for b in banned_in(text)}
    assert not offenders, f"backend vocabulary leaked into the artifact: {offenders}"


def test_the_module_names_no_runtime_implementation():
    """The AST test catches vocabulary in logic; the walk above catches it in output.

    Prose that *disclaims* a word is why this is two tests: scanning raw text would fail on
    this module's own docstring for saying it does not mention shulkers.
    """
    source = (REPO / "src/paperized/artifact.py").read_text()
    tree = ast.parse(source)
    doc = ast.get_docstring(tree) or ""
    offenders = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            offenders |= banned_in(node.id)
        elif isinstance(node, ast.Attribute):
            offenders |= banned_in(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.strip() == doc.strip():
                continue
            offenders |= banned_in(node.value)
    assert not offenders, f"backend vocabulary in the artifact module: {offenders}"


def test_collision_is_cubes_and_not_a_primitive_count():
    """The artifact says cubes, so a runtime places them however it likes.

    A count is the tempting cheap thing to emit and it is exactly wrong: four shulkers,
    four AABBs and four server-native shapes are four different placements.
    """
    document = cmb_definitions()
    state = document["blocks"]["cinchsmissingblocks:andesite_brick_stairs"]["states"][0]
    cubes = state["collision"]["cubes"]
    assert len(cubes) == state["collision"].get("cube_count", len(cubes))
    assert all(set(c) == {"min", "max"} for c in cubes)
    assert all(len(c["min"]) == 3 and len(c["max"]) == 3 for c in cubes)


# --- nothing dropped silently --------------------------------------------------


def test_a_state_with_no_geometry_is_present_with_a_reason():
    """FD's 68 canvas signs. A package that omitted them would look like one that never saw
    them."""
    document = definitions_json(
        compile_mod(ROOTS_FD[1] / "blockstates", ROOTS_FD, VANILLA, TABLE, SHULKER),
        "farmersdelight")
    gaps = [(name, s) for name, b in document["blocks"].items() for s in b["states"]
            if s["status"] != COMPILED]
    assert len(gaps) == 68
    for _, state in gaps:
        assert state["reason"] in {NO_GEOMETRY, "no-part-applies", "too-thin",
                                   "model-chain-broken", "not-decided", "unrepresentable"}
        assert state["note"], "a reason code for a machine and prose for a human"
        assert "collision" not in state


def test_a_refused_state_is_not_silently_dropped():
    """CMB's walls have states that genuinely draw nothing -- post is ``when up: true``."""
    document = cmb_definitions()
    refused = [s for b in document["blocks"].values() for s in b["states"]
               if s["status"] != COMPILED]
    assert refused, "CMB has wall states that apply no part"
    assert all(s["reason"] == "no-part-applies" for s in refused)
    assert all("<unmentioned>" in str(s["state"]) or s["state"] for s in refused)


def test_an_undecided_state_is_distinguishable_from_one_without_geometry():
    """Different failures need different responses, so they must not share a status."""
    empty = PolicyTable(rules=(({"box_count": 99}, "visual", "0"),))
    plan = compile_block("andesite_brick_wall", json.loads(
        (CMB / "blockstates/andesite_brick_wall.json").read_text()),
        ROOTS, VANILLA, empty, SHULKER)
    document = definitions_json((plan,), "cinchsmissingblocks")
    statuses = {s["status"] for b in document["blocks"].values() for s in b["states"]}
    assert "undecided" in statuses


# --- cube serialisation ---------------------------------------------------------


def test_a_cube_serialises_with_exact_arithmetic():
    """The tiler's float bug, not repeated on the far side of the boundary.

    6.02 + 1.02 in floats is 7.039999..., so a package carrying the side and letting the
    backend add it would move the gap to the reader.
    """
    serialised = cube_json(Cube(6.02, 0.0, 0.0, 1.02))
    assert serialised["max"][0] == 7.04


def test_a_cube_round_trips_through_json():
    document = cmb_definitions()
    state = document["blocks"]["cinchsmissingblocks:andesite_brick_pillar"]["states"][0]
    for cube in state["collision"]["cubes"]:
        assert all(isinstance(v, (int, float)) for v in cube["min"] + cube["max"])


def test_the_cube_count_in_the_package_is_what_was_tiled():
    """Not the price: the tiles. A package cannot claim a count it did not produce."""
    document = cmb_definitions()
    for block in document["blocks"].values():
        for state in block["states"]:
            if state["status"] != COMPILED:
                continue
            assert len(state["collision"]["cubes"]) == state["collision"].get("cube_count",
                                                                           len(state["collision"]["cubes"]))