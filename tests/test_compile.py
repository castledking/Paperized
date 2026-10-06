"""CMB end to end: assets -> cubes, under a policy the caller wrote.

Every stage before this was testable alone, which is how each got checked. This runs the
chain and checks the properties that only exist once it is whole -- that the price in the
report is the count the tiler produces, and that a block the table does not decide stays
undecided instead of quietly costing something.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from paperized.collision import Policy
from paperized.compile import (
    CompileError,
    PolicyTable,
    compile_block,
    compile_mod,
    cube_count,
    report,
)
from paperized.cli import asset_roots, main
from paperized.tile import CubeLimits

CMB = pathlib.Path(
    "/mnt/storage/repos/Cinchs_Missing_Blocks_Paperized/server/plugins/CraftEngine"
    "/resources/cinchsmissingblocks/resourcepack/assets/cinchsmissingblocks"
)
VANILLA = pathlib.Path("/tmp/opencode/assets/minecraft/models")
SHULKER = CubeLimits(1, 256)
ROOTS = [CMB / "models/block", CMB / "models", VANILLA]
REPO = pathlib.Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(
    not (CMB.exists() and VANILLA.exists()), reason="the real CMB pack is not present"
)


def table(**overrides) -> PolicyTable:
    return PolicyTable(**overrides)


def write(tmp_path, document) -> pathlib.Path:
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def blockstate(name: str) -> dict:
    return json.loads((CMB / "blockstates" / f"{name}.json").read_text())


#: Compiling all 381 blocks takes about half a minute, and three tests want the same
#: result. The tables are the only variable, so cache on it: without this the suite went
#: from 16 seconds to nearly two minutes, which is long enough that people stop running it.
_MOD_CACHE: dict = {}


def compile_cmb(blockstates: PolicyTable):
    # The rules hold dicts, so the key is their repr: sorting by json.dumps keeps two
    # tables that differ only in rule order distinct, which they must, since order is
    # what decides which rule wins.
    key = json.dumps([blockstates.rules, blockstates.blocks, blockstates.min_thickness],
                     sort_keys=True, default=str)
    if key not in _MOD_CACHE:
        _MOD_CACHE[key] = compile_mod(CMB / "blockstates", ROOTS, VANILLA, blockstates, SHULKER)
    return _MOD_CACHE[key]


# --- the table is data, and it is strict -------------------------------------


def test_the_table_refuses_a_key_it_does_not_know(tmp_path):
    path = write(tmp_path, {"rules": [], "nonsense": 1})
    with pytest.raises(CompileError, match="nonsense"):
        PolicyTable.load(path)


def test_the_table_refuses_matching_on_a_family_name(tmp_path):
    """A rule may match measured geometry or a block id. Nothing in between.

    Matching on "is it a wall" is the taxonomy this project removed, arriving through the
    policy table instead of through the decomposer.
    """
    path = write(tmp_path, {"rules": [{"when": {"family": "wall"}, "policy": "none"}]})
    with pytest.raises(CompileError, match="family"):
        PolicyTable.load(path)


def test_the_table_refuses_a_policy_it_does_not_know(tmp_path):
    path = write(tmp_path, {"rules": [{"when": {}, "policy": "vibes"}]})
    with pytest.raises(CompileError, match="no known policy"):
        PolicyTable.load(path)


def test_a_block_nobody_decided_is_undecided_not_defaulted():
    """The whole reason this stage reports rather than chooses.

    A cube count of zero for an undecided block would be a claim that it needs no hitboxes,
    which is different from not having an answer.
    """
    # A table that decides nothing at all raises instead, so undecidedness needs a table
    # that has opinions -- just none about this block.
    unrelated = table(rules=(({"box_count": 99}, "visual", "0"),))
    plan = compile_block("andesite_brick_stairs", blockstate("andesite_brick_stairs"),
                         ROOTS, VANILLA, unrelated, SHULKER)
    assert plan.undecided
    assert plan.policy is None
    assert plan.cubes is None
    assert plan.worst is None


def test_an_empty_table_is_refused_outright(tmp_path):
    """Every block undecided would be a successful run that compiled nothing."""
    with pytest.raises(CompileError, match="decides nothing"):
        compile_block("andesite_bricks", blockstate("andesite_bricks"),
                      ROOTS, VANILLA, table(), SHULKER)


# --- the chain ---------------------------------------------------------------


def test_a_cube_geometry_block_compiles_to_one_cube():
    plan = compile_block("andesite_bricks", blockstate("andesite_bricks"), ROOTS, VANILLA,
                         table(rules=(({}, "visual", "0"),)), SHULKER)
    assert plan.policy is Policy.VISUAL
    assert plan.cubes == 1
    assert plan.matched == "rule:0 visual"


def test_a_pressure_plate_is_a_pixel_thick_and_can_be_given_no_collision():
    """The 196-cube case, and the reason a geometric rule beats a name.

    The rule says "one unit thick gets no collision". It matches the plate without knowing
    what a pressure plate is, and it would match anything else drawn that thin.
    """
    offered = table(rules=(({"max_thickness": 1}, "none", "0"), ({}, "visual", "1")))
    plan = compile_block("polished_deepslate_pressure_plate",
                         blockstate("polished_deepslate_pressure_plate"),
                         ROOTS, VANILLA, offered, SHULKER)
    assert plan.policy is Policy.NONE
    assert plan.cubes == 0

    # and with only the visual rule, the same block is ruinous
    visual_only = compile_block("polished_deepslate_pressure_plate",
                                blockstate("polished_deepslate_pressure_plate"),
                                ROOTS, VANILLA, table(rules=(({}, "visual", "0"),)), SHULKER)
    assert visual_only.cubes is not None and visual_only.cubes > 100


def test_a_multipart_block_is_composed_not_refused():
    """Walls, fences and panes are multipart. Refusing them would drop 114 of CMB's blocks.

    measure_state composes each placed model and unions them, so the compilation sees the
    whole shape rather than whichever part happened to be first.
    """
    plan = compile_block("andesite_brick_wall", blockstate("andesite_brick_wall"),
                         ROOTS, VANILLA, table(rules=(({}, "visual", "0"),)), SHULKER)
    assert plan.note is None, "a multipart block must not be refused for being multipart"
    assert plan.cubes and plan.cubes > 1


def test_a_named_block_beats_a_rule():
    offered = table(rules=(({}, "visual", "0"),),
                    blocks={"andesite_bricks": "none"})
    plan = compile_block("andesite_bricks", blockstate("andesite_bricks"),
                         ROOTS, VANILLA, offered, SHULKER)
    assert plan.policy is Policy.NONE
    assert plan.matched == "block:andesite_bricks"


def test_the_first_matching_rule_wins():
    offered = table(rules=(({"full_cube": True}, "none", "0"), ({}, "visual", "1")))
    plan = compile_block("andesite_bricks", blockstate("andesite_bricks"),
                         ROOTS, VANILLA, offered, SHULKER)
    assert plan.matched == "rule:0 none"


def test_the_price_is_what_the_tiler_produces():
    """Re-derived, not read back. A pricing bug and a tiling bug cannot agree by accident."""
    plan = compile_block("andesite_brick_stairs", blockstate("andesite_brick_stairs"),
                         ROOTS, VANILLA, table(rules=(({}, "visual", "0"),)), SHULKER)
    for state in plan.states:
        count, cubes = cube_count(plan, state, SHULKER)
        assert count == state.cubes == len(cubes)


def test_a_walls_worst_state_prices_at_the_expected_cube_count():
    """Pins the figure the cut choice was made on.

    A wall crossing is 34 cubes merged and 26 as drawn; across CMB every wall's worst state
    lands on the same 26. If a change in the merger or the tiler moves this, the number the
    collision stage reports moves with it, and this says so.
    """
    plan = compile_block("andesite_brick_wall", blockstate("andesite_brick_wall"),
                         ROOTS, VANILLA, table(rules=(({}, "visual", "0"),)), SHULKER)
    assert plan.cubes == 26


# --- the whole mod -----------------------------------------------------------


def test_every_cmb_block_compiles_and_its_price_is_real():
    plans = compile_cmb(PolicyTable(rules=(({"max_thickness": 1}, "none", "0"),
                                            ({}, "visual", "1"))))
    assert len(plans) == 381
    assert not [p for p in plans if p.undecided], "every block was decided by the table"
    for plan in plans:
        worst = plan.worst
        if worst is None:
            continue
        count, cubes = cube_count(plan, worst, SHULKER)
        assert count == worst.cubes
        if plan.policy is Policy.NONE:
            # No collision is a decision, not a failure to compile. The pressure plate is
            # the case: the table gives it none, so it rightly produces no cubes.
            assert not cubes
        else:
            assert cubes, "a compiled block must actually produce cubes"


def test_the_report_says_how_many_blocks_it_compiled():
    plans = compile_cmb(PolicyTable(rules=(({}, "visual", "0"),)))
    text = report(plans, "cinchsmissingblocks")
    assert "381 blocks in cinchsmissingblocks: 381 compiled, 0 undecided, 0 refused" in text
    assert "worst single state" in text


def test_the_cli_compiles_a_built_pack_by_its_assets_path():
    """A server has .../assets/cinchsmissingblocks, not a mod checkout.

    Pointing at that directory used to report "no assets found" while the directory plainly
    held 381 blockstates, because the lookup only understood a mod's source layout.
    """
    assert asset_roots(CMB) == [CMB]
    assert main(["compile", str(CMB), "--policy", str(REPO / "examples/cmb-policy.json"),
                 "--vanilla-models", str(VANILLA)]) == 0


def test_the_shipped_example_table_is_valid_and_decides_something():
    shipped = PolicyTable.load(REPO / "examples/cmb-policy.json")
    plans = compile_cmb(shipped)
    assert len(plans) == 381
    assert all(p.cubes is not None for p in plans)


# --- what it must not know ---------------------------------------------------


def test_the_compiler_names_no_blocks_or_runtimes():
    """The policy table is data; the module holding it is not a second copy of it."""
    import ast

    source = (REPO / "src/paperized/compile.py").read_text()
    tree = ast.parse(source)
    doc = ast.get_docstring(tree) or ""
    banned = {"craftengine", "shulker", "paper", "minecraft", "entity", "modrinth", "paper"}
    offenders = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            offenders |= {b for b in banned if b in node.id.lower()}
        elif isinstance(node, ast.Attribute):
            offenders |= {b for b in banned if b in node.attr.lower()}
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.strip() == doc.strip():
                continue
            offenders |= {b for b in banned if b in node.value.lower()}
    assert not offenders, f"runtime vocabulary leaked into the compiler: {offenders}"