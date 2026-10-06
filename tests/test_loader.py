"""The measurement path's model lookup."""

from __future__ import annotations

import json

from paperized.analysis.geometry import _loader


def test_a_root_holding_a_block_directory_is_searched_inside_it(tmp_path):
    """A resource root (`.../models`) keeps its models in `block/`. The lookup searched the
    root itself, and found nothing unless the caller happened to pass `models/block`."""
    (tmp_path / "block").mkdir()
    (tmp_path / "block" / "post.json").write_text(json.dumps({"elements": []}))
    assert _loader([tmp_path], None)("mod:block/post") == {"elements": []}
