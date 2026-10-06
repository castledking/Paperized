"""BlockstateResolver: which models a blockstate draws for a state, and how each is turned."""

from __future__ import annotations

import ast
import pathlib

import pytest

from paperized.blockstate import (
    UNMENTIONED,
    BlockstateError,
    Model,
    condition_classes,
    placements,
    states,
)


def refs(blockstate, state):
    return [p.model.ref for p in placements(blockstate, state)]


# --- variants ------------------------------------------------------------------------

STAIRS = {"variants": {
    "facing=east,half=bottom": {"model": "m:stairs"},
    "facing=south,half=bottom": {"model": "m:stairs", "y": 90},
    "facing=east,half=top": {"model": "m:stairs", "x": 180},
}}


def test_exactly_one_variant_key_matches():
    (placement,) = placements(STAIRS, {"facing": "south", "half": "bottom"})
    assert placement.model == Model("m:stairs", 0, 90)


def test_a_property_the_key_does_not_list_is_unconstrained():
    assert refs(STAIRS, {"facing": "east", "half": "top", "waterlogged": "true"}) == ["m:stairs"]


def test_the_empty_key_matches_every_state():
    assert refs({"variants": {"": {"model": "m:cube"}}}, {}) == ["m:cube"]


def test_no_matching_variant_raises():
    with pytest.raises(BlockstateError, match="matches 0"):
        placements(STAIRS, {"facing": "north", "half": "bottom"})


def test_two_matching_variants_raise_rather_than_pick():
    ambiguous = {"variants": {"a=1": {"model": "m:one"}, "b=2": {"model": "m:two"}}}
    with pytest.raises(BlockstateError, match="matches 2"):
        placements(ambiguous, {"a": "1", "b": "2"})


def test_a_variant_key_naming_a_missing_property_raises():
    with pytest.raises(BlockstateError, match="does not have"):
        placements(STAIRS, {"facing": "east"})


# --- multipart -----------------------------------------------------------------------

WALL = {"multipart": [
    {"when": {"up": "true"}, "apply": {"model": "m:post"}},
    {"when": {"north": "low"}, "apply": {"model": "m:side", "uvlock": True}},
    {"when": {"east": "low"}, "apply": {"model": "m:side", "y": 90, "uvlock": True}},
    {"when": {"north": "tall"}, "apply": {"model": "m:side_tall"}},
    {"when": {"east": "tall"}, "apply": {"model": "m:side_tall", "y": 90}},
]}


def test_every_part_whose_condition_holds_applies_together():
    got = placements(WALL, {"up": "true", "north": "low", "east": "tall"})
    assert [p.model for p in got] == [
        Model("m:post"), Model("m:side"), Model("m:side_tall", 0, 90)]


def test_a_part_without_a_condition_always_applies():
    always = {"multipart": [{"apply": {"model": "m:base"}},
                            {"when": {"lit": "true"}, "apply": {"model": "m:flame"}}]}
    assert refs(always, {"lit": "false"}) == ["m:base"]


def test_a_state_drawing_nothing_is_an_empty_answer_not_an_error():
    """Resolving is not composing: "no part applies" is a fact here, and composition is
    the stage that refuses to call it a shape."""
    assert placements(WALL, {"up": "false", "north": "none", "east": "none"}) == ()


def test_pipe_negation_or_and_json_booleans():
    blockstate = {"multipart": [
        {"when": {"facing": "north|south"}, "apply": {"model": "m:pipe"}},
        {"when": {"facing": "!north"}, "apply": {"model": "m:negated"}},
        {"when": {"OR": [{"a": "1"}, {"b": "1"}]}, "apply": {"model": "m:or"}},
        {"when": {"AND": [{"a": "1"}, {"b": "1"}]}, "apply": {"model": "m:and"}},
        {"when": {"lit": True}, "apply": {"model": "m:bool"}},
    ]}
    assert refs(blockstate, {"facing": "south", "a": "1", "b": "0", "lit": "true"}) == [
        "m:pipe", "m:negated", "m:or", "m:bool"]
    assert refs(blockstate, {"facing": "north", "a": "1", "b": "1", "lit": False}) == [
        "m:pipe", "m:or", "m:and"]


def test_a_condition_on_a_missing_property_raises_rather_than_reading_false():
    """Reading a missing property as false draws "not connected" -- plausible and wrong."""
    with pytest.raises(BlockstateError, match="'east'"):
        placements(WALL, {"up": "true", "north": "low"})


def test_a_random_choice_keeps_every_alternative():
    random = {"variants": {"": [{"model": "m:a"}, {"model": "m:a", "y": 90, "weight": 3}]}}
    (placement,) = placements(random, {})
    assert placement.alternatives == (Model("m:a"), Model("m:a", 0, 90, 3))
    with pytest.raises(BlockstateError, match="no single model"):
        placement.model


def test_a_rotation_that_is_not_a_right_angle_raises():
    with pytest.raises(BlockstateError, match="right angle"):
        placements({"variants": {"": {"model": "m:a", "y": 45}}}, {})


# --- state spaces ----------------------------------------------------------------------


def test_unmentioned_values_are_one_class():
    """A wall's `none` never appears in its multipart; it is the UNMENTIONED class."""
    classes = condition_classes(WALL)
    assert classes["north"] == ("low", "tall", UNMENTIONED)


def test_a_property_named_only_true_and_false_is_a_boolean():
    pane = {"multipart": [{"when": {"north": "true"}, "apply": {"model": "m:side"}},
                          {"when": {"north": "false"}, "apply": {"model": "m:noside"}}]}
    assert condition_classes(pane) == {"north": ("false", "true")}


def test_a_boolean_named_only_true_keeps_its_unmentioned_class():
    """`up: true` alone does not prove a boolean; the class stands for `false` here."""
    assert condition_classes(WALL)["up"] == ("true", UNMENTIONED)


def test_every_combination_of_classes_is_enumerated():
    assert len(list(states(WALL))) == 2 * 3 * 3


def test_variant_states_are_the_ones_a_key_matches():
    assert list(states(STAIRS)) == [
        {"facing": "east", "half": "bottom"},
        {"facing": "east", "half": "top"},
        {"facing": "south", "half": "bottom"},
    ]


def test_the_resolver_imports_nothing_from_the_package():
    import paperized.blockstate as b

    tree = ast.parse(pathlib.Path(b.__file__).read_text())
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level], (
        "the resolver reads JSON; geometry is other stages' business"
    )
