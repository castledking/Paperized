"""The manifest is a public contract, so its shape is tested like one.

These tests are about the contract, not the generator: if a consumer switches on a reason
or reads a field, a change here breaks them.
"""

from __future__ import annotations

import dataclasses

import pytest

from paperized.manifest import Deferred, Family, Manifest, Reason


def make_manifest(**overrides) -> Manifest:
    defaults = dict(
        schema=1,
        mc_version="26.3",
        blocks_served=74,
        internal_states_used=275,
        internal_states_max=5120,
        families=(Family("cube", 400, 120, 120, 74),),
        deferred=(Deferred("cmb:andesite_brick_wall", Reason.MULTIPART_UNSAFE, "multipart"),),
        externally_claimed={},
    )
    return Manifest(**{**defaults, **overrides})


def test_reason_values_are_stable_identifiers():
    """Consumers may switch on these. Renaming one silently breaks them."""
    assert Reason.NO_SAFE_CARRIER.value == "no_safe_carrier"
    assert Reason.MULTIPART_UNSAFE.value == "multipart_unsafe"
    assert Reason.CLAIMED_ELSEWHERE.value == "claimed_elsewhere"


def test_states_free_never_goes_negative():
    """Over budget must read as zero, not as a negative that looks like headroom."""
    m = make_manifest(internal_states_used=6000, internal_states_max=5120)
    assert m.states_free == 0


def test_family_free_states_and_exhaustion():
    f = Family("slab", candidates=60, safe_carriers=5, capacity_states=15, assigned_states=15)
    assert f.free_states == 0
    assert f.exhausted is True


def test_family_reports_headroom():
    f = Family("cube", candidates=400, safe_carriers=120, capacity_states=120, assigned_states=74)
    assert f.free_states == 46
    assert f.exhausted is False


def test_deferrals_filterable_by_reason():
    """A consumer must be able to separate 'impossible' from 'someone else got it'."""
    m = make_manifest(
        deferred=(
            Deferred("cmb:a", Reason.MULTIPART_UNSAFE, "multipart"),
            Deferred("cmb:b", Reason.CLAIMED_ELSEWHERE, "other pack"),
        )
    )
    assert [d.block for d in m.deferrals(Reason.MULTIPART_UNSAFE)] == ["cmb:a"]
    assert len(m.deferrals(Reason.MULTIPART_UNSAFE)) == 1


def test_unknown_reason_is_empty_not_an_error():
    m = make_manifest()
    assert m.deferrals(Reason.CAPACITY_EXHAUSTED) == ()


def test_to_json_is_serialisable_and_reports_free_states():
    import json

    data = make_manifest().to_json()
    json.dumps(data)  # must not raise
    assert data["internal_states"]["free"] == 5120 - 275
    assert data["families"][0]["name"] == "cube"


def test_write_creates_parent_directories(tmp_path):
    m = make_manifest()
    out = tmp_path / "nested" / "deeper" / "manifest.json"
    m.write(out)
    assert out.is_file()


def test_manifest_is_frozen():
    """Immutable so a consumer cannot mutate a build's record of what happened."""
    m = make_manifest()
    with pytest.raises(dataclasses.FrozenInstanceError):
        m.blocks_served = 0  # type: ignore[misc]
