"""Classify a block's geometry, so a carrier family can be chosen honestly.

Why this is its own module and not a helper inside the allocator: deciding *what shape a
block is* and deciding *what to do about it* are different jobs with different failure
modes. Getting the first wrong silently produces a block with the wrong hitbox, and that
is the single worst failure in this project -- it looks fine until someone walks into it.

The measurement is deliberately blunt: follow the parent chain until something defines
``elements``, then ask whether those elements fill the whole 0..16 cube. No heuristics on
names, because mod naming is not reliable -- ``black_canvas_sign`` has nothing to do with
the shape of a sign as far as a carrier is concerned.

A model with no ``elements`` inherits its geometry from a vanilla parent, which is the one
case where "full cube" is a real answer rather than an absence of information.
"""

from __future__ import annotations

import dataclasses
import enum
import json
import pathlib


class Shape(enum.Enum):
    """What a block's collision geometry actually is."""

    FULL_CUBE = "full_cube"
    """Fills 0..16 on all three axes. Competes for the scarce cube pool."""

    PARTIAL = "partial"
    """Some real geometry, not a cube. Needs a carrier of the same shape, or furniture."""

    INHERITS = "inherits"
    """No elements of its own; geometry comes from a vanilla parent. Usually a cube."""

    UNKNOWN = "unknown"
    """Chain could not be resolved. Must not be silently treated as a cube."""


@dataclasses.dataclass(frozen=True)
class Geometry:
    block: str
    shape: Shape
    model: str | None
    elements: tuple[dict, ...]
    chain: tuple[str, ...]
    """Parent chain walked, in order. Kept for the error message when resolution fails."""

    @property
    def resolved(self) -> bool:
        return self.shape is not Shape.UNKNOWN

    @property
    def is_cube(self) -> bool:
        return self.shape in (Shape.FULL_CUBE, Shape.INHERITS)


_MAX_DEPTH = 16


def _load(path: pathlib.Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _is_full_cube(elements: list) -> bool:
    return all(
        tuple(e.get("from", (0, 0, 0))) == (0, 0, 0)
        and tuple(e.get("to", (0, 0, 0))) == (16, 16, 16)
        for e in elements
    )


def classify(
    block: str,
    first_model: str | None,
    mod_models: pathlib.Path | list[pathlib.Path],
    vanilla_models: pathlib.Path | None = None,
    vanilla_block_dir: str = "block",
) -> Geometry:
    """Measure one block's geometry.

    ``first_model`` is the model the block's own first blockstate variant points at, so
    the caller decides which variant is representative rather than this function guessing.

    ``mod_models`` is the mod's ``models/block/``, or a **list** of such directories.

    The list is the normal case, not a convenience. Mods routinely split assets across
    ``src/main/resources`` and ``src/generated/resources``, and a model in one can parent
    to a model in the other. Farmer's Delight's 68 canvas signs all parent to
    ``block/canvas_sign``, which lives in ``main/resources``, while the signs themselves
    are generated. Searching one root resolves none of them, and a resolver that silently
    returns "unknown" for 68 blocks is indistinguishable from one that is simply broken.

    ``vanilla_models`` points at the vanilla ``models/`` root -- *not* at ``models/block/``
    -- and ``vanilla_block_dir`` names the subdirectory inside it. Both roots are searched
    because a mod model commonly parents to something like ``minecraft:block/orientable``,
    and that answer lives in the vanilla jar, not the mod.
    """
    if not first_model:
        return Geometry(block, Shape.UNKNOWN, None, (), ())

    # A mod model sits at models/block/<name>.json; a vanilla one at
    # models/block/<name>.json too, but under the *vanilla* root, whose layout differs.
    if isinstance(mod_models, pathlib.Path):
        mod_roots = [mod_models]
    else:
        mod_roots = list(mod_models)
    roots = [(r, "") for r in mod_roots]
    if vanilla_models is not None:
        roots.append((vanilla_models / vanilla_block_dir, ""))

    current = first_model
    chain: list[str] = []

    for _ in range(_MAX_DEPTH):
        chain.append(current)
        # Strip the namespace, then any leading directory: a vanilla reference is
        # `minecraft:block/orientable`, and the roots are already scoped to
        # `models/block`, so keeping the directory would look for block/block/.
        name = current.split(":")[-1].split("/")[-1]
        data = None
        for root, prefix in roots:
            candidate = root / f"{prefix}{name}.json"
            if candidate.is_file():
                data = _load(candidate)
                if data is not None:
                    break
        if data is None:
            return Geometry(block, Shape.UNKNOWN, first_model, (), tuple(chain))

        if "elements" in data:
            elements = tuple(data["elements"] or ())
            shape = Shape.FULL_CUBE if _is_full_cube(list(elements)) else Shape.PARTIAL
            return Geometry(block, shape, first_model, elements, tuple(chain))

        parent = data.get("parent")
        if not parent:
            # A model with neither elements nor a parent defines no geometry of its own.
            return Geometry(block, Shape.INHERITS, first_model, (), tuple(chain))
        current = str(parent)

    return Geometry(block, Shape.UNKNOWN, first_model, (), tuple(chain))


def first_model(blockstate: dict) -> str | None:
    """The model a blockstate names, or None if it names none.

    Exists because picking the representative variant is a *caller* decision -- the
    first variant is a fine representative for geometry, but a caller that cares about
    a specific state should pick it itself.

    Handles the three shapes a blockstate entry takes in practice:

    * ``variants: {key: {model: ...}}`` -- the ordinary form
    * ``variants: {key: [{model: ...}, ...]}`` -- a value that is a *list*, which
      Farmer's Delight uses for anything randomly rotated (``organic_compost`` lists
      the same model four times with different ``y``). Missing this silently reports 4 of
      FD's blocks as having no model at all.
    * ``multipart: [{apply: {model: ...}}]`` -- no ``variants`` key

    Multipart returns the first entry's model so a caller can still measure *something*,
    but a multipart blockstate is never a safe carrier (see docs/carrier-safety.md), so
    treat the measurement as informative only.
    """
    variants = blockstate.get("variants") or {}
    for value in variants.values():
        if isinstance(value, dict):
            model = value.get("model")
            if model:
                return str(model)
        elif isinstance(value, list):
            for entry in value:
                if isinstance(entry, dict) and entry.get("model"):
                    return str(entry["model"])
    for part in blockstate.get("multipart") or []:
        model = (part.get("apply") or {}).get("model")
        if model:
            return str(model)
    return None
