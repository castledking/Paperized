"""Geometry classification, tested against the traps that were actually hit.

Every test here corresponds to a bug found while measuring a real mod (Farmer's
Delight). None are hypothetical: each one silently produced "unknown" for dozens of
blocks and would have reported a port as unplaceable.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from paperized.analysis.shape import Shape, classify, first_model


@pytest.fixture
def roots(tmp_path):
    """A mod with models split across two roots, plus a vanilla root."""
    main = tmp_path / "main" / "models" / "block"
    gen = tmp_path / "generated" / "models" / "block"
    vanilla = tmp_path / "vanilla" / "models"
    for d in (main, gen, vanilla / "block"):
        d.mkdir(parents=True)
    return main, gen, vanilla


def write(path: pathlib.Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_vanilla_parent_is_resolved_through_the_namespace(tmp_path, roots):
    """`minecraft:block/cube` must not look for block/block/cube.json."""
    main, _, vanilla = roots
    write(main / "widget.json", {"parent": "minecraft:block/cube"})
    write(vanilla / "block" / "cube.json", {
        "parent": "block/block",
        "elements": [{"from": [0, 0, 0], "to": [16, 16, 16]}],
    })
    g = classify("widget", "mod:block/widget", [main], vanilla)
    assert g.shape is Shape.FULL_CUBE


def test_models_split_across_two_roots_are_both_searched(tmp_path, roots):
    """68 of Farmer's Delight's signs parent into main/resources while living in generated."""
    main, gen, vanilla = roots
    write(gen / "sign.json", {"parent": "farmersdelight:block/canvas_sign"})
    write(main / "canvas_sign.json", {
        "parent": "minecraft:block/cube",
    })
    write(vanilla / "block" / "cube.json", {
        "parent": "block/block",
        "elements": [{"from": [0, 0, 0], "to": [16, 16, 16]}],
    })
    g = classify("sign", "mod:block/sign", [main, gen], vanilla)
    assert g.shape is Shape.FULL_CUBE


def test_partial_geometry_is_not_called_a_cube(tmp_path, roots):
    """The single worst failure: a block that looks fine until someone walks into it."""
    main, _, vanilla = roots
    write(main / "slab.json", {
        "parent": "minecraft:block/block",
        "elements": [{"from": [0, 0, 0], "to": [16, 16, 8]}],
    })
    g = classify("slab", "mod:block/slab", [main], vanilla)
    assert g.shape is Shape.PARTIAL
    assert not g.is_cube


def test_unresolved_stays_unknown_and_never_falls_back_to_cube(tmp_path, roots):
    """Guessing 'cube' when the chain is missing is how wrong hitboxes get shipped."""
    main, _, vanilla = roots
    g = classify("ghost", "mod:block/ghost", [main], vanilla)
    assert g.shape is Shape.UNKNOWN
    assert not g.is_cube
    assert not g.resolved


def test_model_with_no_elements_and_no_parent_inherits(tmp_path, roots):
    main, _, vanilla = roots
    write(main / "plain.json", {"textures": {"all": "mod:block/x"}})
    g = classify("plain", "mod:block/plain", [main], vanilla)
    assert g.shape is Shape.INHERITS
    assert g.is_cube


def test_missing_model_reference_is_unknown(tmp_path, roots):
    main, _, vanilla = roots
    g = classify("nothing", None, [main], vanilla)
    assert g.shape is Shape.UNKNOWN
    assert g.chain == ()


def test_variant_value_that_is_a_list(tmp_path, roots):
    """FD's organic_compost lists one model four times with different y rotations."""
    main, _, vanilla = roots
    data = {"variants": {"composting=0": [{"model": "mod:block/stage0", "y": 90}]}}
    assert first_model(data) == "mod:block/stage0"


def test_multipart_yields_its_first_model(tmp_path, roots):
    main, _, vanilla = roots
    data = {"multipart": [{"apply": {"model": "mod:block/post"}}]}
    assert first_model(data) == "mod:block/post"


def test_first_model_prefers_variants_over_multipart():
    data = {
        "variants": {"facing=north": {"model": "mod:block/a"}},
        "multipart": [{"apply": {"model": "mod:block/b"}}],
    }
    assert first_model(data) == "mod:block/a"


def test_parent_cycle_terminates(tmp_path, roots):
    """A cycle must return, not hang."""
    main, _, vanilla = roots
    write(main / "a.json", {"parent": "mod:block/b"})
    write(main / "b.json", {"parent": "mod:block/a"})
    g = classify("a", "mod:block/a", [main], vanilla)
    assert g.shape is Shape.UNKNOWN
    assert len(g.chain) <= 17
