"""The intermediate representation: what Paperized knows about a block.

Design rule, and the reason for most of what follows — **a plausible derived number must
never become the source of truth.**

That is not a general principle, it is a scar. `Capabilities.is_full_cube` once compared
``box_count == 1`` against a constant without ever reading the box, so all 61 of a mod's
slabs measured as full cubes. Nothing crashed. The output looked reasonable. It was wrong
in precisely the way this project exists to prevent.

So every measurement is kept, immutable, next to whatever is derived from it. When a
classifier makes a bad decision -- and it will -- the evidence it was given is still there
to look at, rather than having been replaced by the answer.

Two further decisions worth stating up front:

**Visual and collision geometry are separate types, not one optional field.** They genuinely
differ, and not only in principle. A pillar's *model* parents to ``minecraft:block/
cube_column``, while its *carrier* is a note block, so its collision is a full cube. Its
visual geometry is a column and its collision is a block. Conflating them would make one of
the two a lie.

**Nothing here names a Minecraft family.** Clustering both mods showed the family set is a
power law -- 92 of one mod's 132 blocks are a single geometry, and 17 of the rest are
singletons. A taxonomy here would be a lookup table wearing a family's clothes. ``wall``,
``fence``, ``pane`` and ``bespoke`` are *profiles over boxes*, applied later, by the
implementation planner -- and "classified geometrically, not taxonomically" is a complete
answer, not a failure to classify.
"""

from __future__ import annotations

import math

import dataclasses
import enum
import json
import pathlib
from typing import Any

# Model space is 0..16 on every axis, matching vanilla and CraftEngine's hitbox placement.
# Coordinates are normalised to this space on the way in so nothing downstream has to know
# where a number came from.
MODEL_MIN = 0
MODEL_MAX = 16


@dataclasses.dataclass(frozen=True)
class Box:
    """One axis-aligned cuboid in model space. Immutable, and the atomic unit of geometry."""

    x0: int
    y0: int
    z0: int
    x1: int
    y1: int
    z1: int

    def __post_init__(self) -> None:
        # Normalise inverted boxes rather than rejecting them. Some mod models ship
        # from > to on a face; that is a rendering hint, not a different shape.
        for a, b, name in (("x0", "x1", "x"), ("y0", "y1", "y"), ("z0", "z1", "z")):
            lo, hi = getattr(self, a), getattr(self, b)
            if lo > hi:
                object.__setattr__(self, a, hi)
                object.__setattr__(self, b, lo)

    @property
    def width(self) -> int:
        return self.x1 - self.x0

    @property
    def height(self) -> int:
        return self.y1 - self.y0

    @property
    def depth(self) -> int:
        return self.z1 - self.z0

    @property
    def volume(self) -> int:
        return self.width * self.height * self.depth

    def as_tuple(self) -> tuple[int, ...]:
        return (self.x0, self.y0, self.z0, self.x1, self.y1, self.z1)

    def to_json(self) -> dict[str, list[int]]:
        return {"min": [self.x0, self.y0, self.z0], "max": [self.x1, self.y1, self.z1]}

    @classmethod
    def from_json(cls, data: dict[str, list[int]]) -> "Box":
        return cls(*data["min"], *data["max"])


FULL_BLOCK = Box(0, 0, 0, 16, 16, 16)


@dataclasses.dataclass(frozen=True)
class OrientedBox:
    """A cuboid that is *not* axis-aligned, kept honestly.

    Added because an axis-aligned box cannot express a rotated one, and the approximation
    is not a rounding error -- it is a different shape. Farmer's Delight's ``cabbages`` is
    two thin planes crossed at 45 degrees; both reduce to the same 10x16x10 axis-aligned
    bounds, so representing them as :class:`Box` reports a nearly solid block where the real
    geometry is two flat sheets.

    Storing the eight corners instead of a centre/angle/pivot keeps this lossless and makes
    determinism trivial: the same input always yields the same corners. Right-angle
    rotations stay integers, because they are exact.

    This is why the decomposer does not "normalise" rotated geometry. A caller that genuinely
    needs an axis-aligned box -- a runtime collision shape, say -- takes the bounds
    explicitly, in a later stage, where that decision is visible.
    """

    corners: tuple[tuple[float, float, float], ...]
    exact: bool = True

    @property
    def bounds(self) -> Box:
        """The axis-aligned box containing this one. A lossy projection, never a substitute."""
        lo = [min(c[i] for c in self.corners) for i in range(3)]
        hi = [max(c[i] for c in self.corners) for i in range(3)]
        return Box(*(math.floor(v + 0.5) if v >= 0 else -math.floor(-v + 0.5)
                     for v in (*lo, *hi)))

    def to_json(self) -> dict[str, Any]:
        return {
            "corners": [list(c) for c in self.corners],
            "exact": self.exact,
        }


@dataclasses.dataclass(frozen=True)
class Geometry:
    """A measured set of cuboids.

    Deliberately knows nothing about what the shapes mean. Every named notion -- full cube,
    pane, wall -- is derived *from* these boxes by :class:`Capabilities`, so a caller can
    disagree with the derivation and still use the boxes.
    """

    boxes: tuple[Box, ...] = ()
    source: str = ""
    """Where this came from: a model chain, a carrier, a declaration. For error messages."""

    oriented: tuple[OrientedBox, ...] = ()
    """Cuboids that are not axis-aligned and therefore cannot live in :attr:`boxes`.

    Present for the geometry that a box list cannot honestly express -- Farmer's Delight's
    crossed 45-degree crop planes. A geometry with both is fully described; one with only
    oriented geometry is a shape made entirely of rotated cuboids, and a consumer that needs
    axis-aligned bounds must project them and accept the loss explicitly.
    """

    exact: bool = True
    """False when the boxes are a quantised approximation of the real geometry.

    Set when a source element was rotated by an angle that is not a multiple of 90, or
    carried fractional coordinates. The rotation is still *applied* -- silently ignoring it
    would report the unrotated box, which is a different shape wearing the right name --
    but the result cannot be represented exactly in integer 0..16 space.

    Nothing reads this yet. It exists because an approximation that is not labelled is an
    approximation that gets trusted, and because the alternative -- a caller comparing two
    geometries box-for-box -- cannot tell "these differ" from "this was rounded".
    """

    @property
    def resolved(self) -> bool:
        """False when geometry is unknown.

        An empty box set is therefore ambiguous between "no geometry" and "could not
        measure it", so :attr:`source` and this flag carry the distinction. Reporting a
        plausible empty as a real shape is the failure mode this exists to prevent.
        """
        return bool(self.boxes) or self.source == "empty"

    @property
    def volume(self) -> int:
        return sum(b.volume for b in self.boxes)

    def to_json(self) -> dict[str, Any]:
        return {
            "boxes": [b.to_json() for b in self.boxes],
            "oriented": [o.to_json() for o in self.oriented],
            "source": self.source,
            "resolved": self.resolved,
            "exact": self.exact,
        }


@dataclasses.dataclass(frozen=True)
class Capabilities:
    """Derived facts about a geometry. Never a source of truth; always recomputable.

    Nothing here is a family name. These are measurements and simple geometric predicates,
    and each is defined *only* in terms of boxes so it cannot drift from them.
    """

    full_cube: bool
    """Exactly one box filling 0..16 on all three axes.

    Note this is derived from the box, not from a box *count*. A single 16x8x16 box is a
    slab and must never report True here.
    """

    full_height: bool
    full_footprint: bool
    """Spans 16 on at least one horizontal axis."""
    thin_axis: str | None
    """'x', 'z', or None. Thin relative to the shape's own span, not an absolute."""
    grounded: bool
    """Touches y=0."""
    multi_part: bool
    """The *source* blockstate is multipart.

    Distinct from multi_box on purpose: multipart means the vanilla rendering is composed
    of separate models, which is a different fact from having several cuboids.
    """

    @property
    def box_count(self) -> int:
        return 0  # replaced per-instance below

    def to_json(self) -> dict[str, Any]:
        return {
            "full_cube": self.full_cube,
            "full_height": self.full_height,
            "full_footprint": self.full_footprint,
            "thin_axis": self.thin_axis,
            "grounded": self.grounded,
            "multi_part": self.multi_part,
        }


@dataclasses.dataclass(frozen=True)
class BlockGeometry:
    """Visual and collision, kept apart.

    They differ in practice, not just in principle. A pillar's model parents to
    ``minecraft:block/cube_column`` while its carrier is a note block: the visual is a
    column, the collision is a full cube. A single optional geometry field would have to
    lie about one of them.
    """

    visual: Geometry
    collision: Geometry
    collision_source: str = ""
    """'carrier', 'furniture', or 'declared'. Carries why the two differ."""

    @property
    def visual_caps(self) -> Capabilities:
        return derive(self.visual, multi_part=False)

    @property
    def collision_caps(self) -> Capabilities:
        return derive(self.collision, multi_part=False)

    @property
    def differs(self) -> bool:
        """Whether visual and collision disagree.

        Worth surfacing rather than normalising away: a block whose collision is
        deliberately larger than its visual is a design decision, and the IR should be
        able to say so.
        """
        return self.visual.boxes != self.collision.boxes

    def to_json(self) -> dict[str, Any]:
        return {
            "visual": self.visual.to_json(),
            "collision": self.collision.to_json(),
            "collision_source": self.collision_source,
            "differs": self.differs,
            "capabilities": {
                "visual": self.visual_caps.to_json(),
                "collision": self.collision_caps.to_json(),
            },
        }


def derive(geometry: Geometry, multi_part: bool = False) -> Capabilities:
    """Derive capabilities from boxes.

    Every field is computed from the geometry in front of it. No field reads another
    field's *name*, and none compares a count against a constant that does not describe
    the boxes actually present.
    """
    boxes = geometry.boxes
    if not boxes:
        return Capabilities(False, False, False, None, False, multi_part)

    full_cube = len(boxes) == 1 and boxes[0].as_tuple() == FULL_BLOCK.as_tuple()

    full_height = any(b.y0 <= MODEL_MIN and b.y1 >= MODEL_MAX for b in boxes)
    grounded = any(b.y0 <= MODEL_MIN for b in boxes)

    span_x = max(b.x1 for b in boxes) - min(b.x0 for b in boxes)
    span_z = max(b.z1 for b in boxes) - min(b.z0 for b in boxes)
    full_footprint = span_x >= MODEL_MAX or span_z >= MODEL_MAX

    # Thin is relative to the shape's own span, so a 14-wide cabinet is not a pane while
    # a 16-by-2 plate is.
    thin_x = span_x <= 4
    thin_z = span_z <= 4
    thin_axis = "x" if thin_x and not thin_z else ("z" if thin_z and not thin_x else None)

    return Capabilities(
        full_cube=full_cube,
        full_height=full_height,
        full_footprint=full_footprint,
        thin_axis=thin_axis,
        grounded=grounded,
        multi_part=multi_part,
    )


@dataclasses.dataclass(frozen=True)
class Property:
    name: str
    values: tuple[str, ...] = ()
    default: str | None = None

    @property
    def measured(self) -> bool:
        """Whether this property's value set is known.

        Empty ``values`` means "not measured", not "no values" -- a property with no values
        would not be a property.
        """
        return bool(self.values)

    @property
    def arity(self) -> int:
        return len(self.values)

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "values": list(self.values), "default": self.default}


@dataclasses.dataclass(frozen=True)
class Properties:
    """The state space a block declares.

    Two different amounts of knowledge, and the difference matters:

    * **names** are recoverable from a blockstate -- they appear in the variant keys.
    * **value sets** are not. They live in the mod's Java registration, so they are
      declared rather than measured.

    :attr:`arity` therefore returns ``None`` whenever any value set is unmeasured, rather
    than guessing. The naive multiplication returns **0** in that case -- because an
    unknown-sized property multiplies the total to nothing -- and 0 states means "this
    block needs no carrier at all", which is precisely backwards: a block with three
    unmeasured properties needs at least as many states as its largest value set.

    A carrier planner must treat ``None`` as "cannot plan yet", not as free.
    """

    properties: tuple[Property, ...] = ()

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(p.name for p in self.properties)

    @property
    def measured(self) -> bool:
        """Whether every declared property has a known value set."""
        return all(p.measured for p in self.properties)

    @property
    def arity(self) -> int | None:
        """Total declared states, or None when any value set is unknown.

        The number a carrier has to supply. ``None`` means unmeasured, never 0.
        """
        if not self.measured:
            return None
        total = 1
        for p in self.properties:
            total *= p.arity
        return total

    def to_json(self) -> dict[str, Any]:
        return {
            "properties": [p.to_json() for p in self.properties],
            "measured": self.measured,
            "arity": self.arity,
        }


class Direction(enum.Enum):
    NORTH = "north"
    EAST = "east"
    SOUTH = "south"
    WEST = "west"
    UP = "up"
    DOWN = "down"


@dataclasses.dataclass(frozen=True)
class Strategy(enum.Enum):
    """How a block will be implemented at runtime.

    Not a family. Two blocks with the same strategy can have unrelated geometry, and the
    same geometry can need different strategies depending on what carriers exist. The
    planner decides this; the IR records it.
    """

    CARRIER = "carrier"
    """Drawn on a vanilla block state. Costs one, and must be provably safe."""

    FURNITURE = "furniture"
    """Display entity plus hitboxes. Costs no vanilla state."""

    UNRESOLVED = "unresolved"
    """Nothing decided yet. A planning stage must replace this before generation."""


@dataclasses.dataclass(frozen=True)
class Block:
    """One block in the IR.

    Deliberately not a family, a shape, or a carrier. It is: an id, what it declares, what
    it looks like, what it collides with, and what has been decided about implementing it.
    Everything else -- which carrier, which profile, whether it is a wall -- belongs to a
    later stage and must be derivable from this.
    """

    id: str
    properties: Properties = dataclasses.field(default_factory=Properties)
    geometry: BlockGeometry = dataclasses.field(
        default_factory=lambda: BlockGeometry(Geometry(), Geometry())
    )
    strategy: Strategy = Strategy.UNRESOLVED
    carrier: str | None = None
    """Vanilla state backing this, when strategy is CARRIER. Diagnostic, never a decision."""

    model: str | None = None
    textures: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "properties": self.properties.to_json(),
            "geometry": self.geometry.to_json(),
            "implementation": {
                "strategy": self.strategy.value,
                "carrier": self.carrier,
            },
            "model": self.model,
            "textures": list(self.textures),
        }

    def write(self, path: pathlib.Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), indent=2) + "\n", encoding="utf-8")
