"""The CLI: a census has to be able to say what it could not measure, and why.

The refusals are the interesting half. A count of "measured 62 of 132" invites the reader
to assume the other 70 are exotic shapes, when 68 of them are canvas signs whose model
carries textures and nothing else -- a blockstate file that looks complete and describes no
geometry at all. Reporting them as one failure number hides which failure happened.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from paperized.cli import asset_roots, census, main


def build_mod(root: pathlib.Path, blockstates: dict[str, dict], models: dict[str, dict]) -> pathlib.Path:
    """A minimal mod: assets under both source sets, since mods really do use both."""
    for source_set in ("main", "generated"):
        assets = root / f"src/{source_set}/resources/assets/demo"
        (assets / "blockstates").mkdir(parents=True, exist_ok=True)
        (assets / "models/block").mkdir(parents=True, exist_ok=True)
    for name, document in blockstates.items():
        (root / "src/main/resources/assets/demo/blockstates" / f"{name}.json").write_text(
            json.dumps(document)
        )
    for name, document in models.items():
        (root / "src/main/resources/assets/demo/models/block" / f"{name}.json").write_text(
            json.dumps(document)
        )
    return root


CUBE = {"elements": [{"from": [0, 0, 0], "to": [16, 16, 16]}]}
PLATE = {"elements": [{"from": [0, 0, 0], "to": [16, 4, 16]}]}
TEXTS_ONLY = {"textures": {"particle": "demo:something"}}


def test_reports_shape_not_a_family(tmp_path):
    mod = build_mod(
        tmp_path,
        {
            "cube": {"variants": {"": {"model": "demo:block/cube"}}},
            "plate": {"variants": {"": {"model": "demo:block/plate"}}},
        },
        {"cube": CUBE, "plate": PLATE},
    )
    report = census(mod, None)
    assert report["measured"] == 2
    assert report["shapes"]["single full cube"] == 1
    # A slab is "1 box(es)". Nothing in the output calls it a slab.
    assert report["shapes"]["1 box(es)"] == 1
    assert not any("slab" in k for k in report["shapes"])


def test_textures_only_model_is_refused_by_reason(tmp_path):
    """The canvas-sign case: 68 of Farmer's Delight's blocks looked like cubes."""
    mod = build_mod(
        tmp_path,
        {
            "cube": {"variants": {"": {"model": "demo:block/cube"}}},
            "sign": {"variants": {"": {"model": "demo:block/sign"}}},
        },
        {"cube": CUBE, "sign": TEXTS_ONLY},
    )
    report = census(mod, None)
    assert report["measured"] == 1
    refusals = report["refused"]
    assert refusals == {"defines no geometry (textures only, no elements and no parent)": 1}


def test_a_broken_chain_and_a_multipart_are_distinguished(tmp_path):
    mod = build_mod(
        tmp_path,
        {
            "gone": {"variants": {"": {"model": "demo:block/missing"}}},
            "wall": {"multipart": [{"apply": {"model": "demo:block/cube"}}]},
        },
        {"cube": CUBE},
    )
    report = census(mod, None)
    assert report["measured"] == 0
    assert len(report["refused"]) == 2, "two different causes must not be lumped together"
    assert any("model chain broken" in k for k in report["refused"])
    assert any("multipart" in k for k in report["refused"])


def test_both_source_sets_are_searched(tmp_path):
    """A model in one source set parenting to a model in the other is the normal case."""
    mod = build_mod(
        tmp_path,
        {"sign": {"variants": {"": {"model": "demo:block/sign"}}}},
        {"sign": {"parent": "demo:block/template", "elements": []}},
    )
    (mod / "src/generated/resources/assets/demo/models/block/template.json").write_text(
        json.dumps({"elements": [{"from": [0, 0, 0], "to": [8, 16, 16]}]})
    )
    report = census(mod, None)
    assert report["measured"] == 1


def test_missing_assets_is_an_error_not_an_empty_census(tmp_path):
    with pytest.raises(SystemExit) as exc:
        census(tmp_path, None)
    assert "no assets found" in str(exc.value)


def test_json_output_is_parseable(tmp_path, capsys):
    mod = build_mod(
        tmp_path, {"cube": {"variants": {"": {"model": "demo:block/cube"}}}}, {"cube": CUBE}
    )
    assert main(["measure", str(mod), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["measured"] == 1


def test_text_output_mentions_the_refusals(tmp_path, capsys):
    mod = build_mod(
        tmp_path, {"sign": {"variants": {"": {"model": "demo:block/sign"}}}}, {"sign": TEXTS_ONLY}
    )
    main(["measure", str(mod)])
    out = capsys.readouterr().out
    assert "refused, by reason" in out
    assert "defines no geometry" in out
