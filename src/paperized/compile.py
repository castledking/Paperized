"""Mod assets -> Cube[]. The whole compiler, in one call.

    blockstates + model roots + a caller's policy table
        -> visual geometry
        -> collision options
        -> the one the caller named
        -> merged regions
        -> cubes

Everything before this module was a stage that could be wrong in isolation. This one runs
the chain and reports the total, so a block that costs 196 cubes is a number in a table
rather than something discovered on a server.

## The policy table belongs to the caller

There is **no default policy**, and that is the design rather than an omission. A block the
table does not decide comes out :attr:`BlockPlan.undecided`, and this module does not guess
what to do with it. Guessing is how a compiler ends up spending 196 entities per pressure
plate because nobody wrote the rule, and how "cheap" becomes an accident.

The table may match on two things:

* ``blocks`` -- a block id, named explicitly.
* ``rules`` -- **measured geometry**, never a family name. ``full_cube``, ``thin_axis``,
  ``max_thickness``, ``box_count``. This is the same rule the rest of the project follows:
  a wall and a bespoke cross that happen to have the same shape get the same treatment,
  because nothing here knows what either of them is called.

Rules are tried in order, first match wins, blocks beat rules. So a table can say "thin and
flat things get no collision" and still name a single block differently.

## What a state costs, and what a block costs

States are enumerated, never invented -- reachability is the game's business and is not in
this pipeline. Each enumerated state is compiled, and a block's cost is the **worst** of its
states, because a server pays that cost on every tick it is placed.

The cube count is the tiler's, over the regions the collision option carries, so the report
is the number a runtime would actually pay rather than an estimate of it.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
from typing import Any, Iterable, Mapping

from .analysis.geometry import measure_state
from .blockstate import states
from .collision import CollisionError, Option, Policy, choose, options
from .decompose import GeometryError
from .ir import Capabilities, Geometry, derive
from .tile import Cube, CubeLimits, TilingError, count, tile

#: A matched rule, kept so the report can say *why* a block was decided.
_RULE_KEYS = frozenset({"full_cube", "thin_axis", "max_thickness", "box_count", "multi_part"})


class CompileError(Exception):
    """The caller's inputs cannot be compiled. Always fatal."""


@dataclasses.dataclass(frozen=True)
class StatePlan:
    """One enumerated state, compiled."""

    state: tuple[tuple[str, str], ...]
    geometry: Geometry
    caps: Capabilities
    offered: tuple[Option, ...]
    chosen: Option | None
    refusal: str | None = None
    tiled: tuple = ()
    """The tiled cubes themselves, when the caller asked for them.

    Named ``tiled`` rather than ``cubes`` because :attr:`cubes` is already the count, and a
    compiled artifact needs the boxes, not the number. Empty when only a price was wanted:
    re-tiling at serialisation time would let a package disagree with the run that produced
    it.
    """

    @property
    def cubes(self) -> int | None:
        return None if self.chosen is None else self.chosen.cubes

    @property
    def regions(self) -> tuple:
        return () if self.chosen is None else self.chosen.regions

    @property
    def decided(self) -> bool:
        return self.chosen is not None


@dataclasses.dataclass(frozen=True)
class BlockPlan:
    """One block, compiled across every state its blockstate enumerates."""

    id: str
    states: tuple[StatePlan, ...]
    policy: Policy | None
    matched: str | None
    """How the table decided: a block id, a rule's index, ``"default"``, or None."""
    note: str | None = None
    """Why nothing was compiled: multipart, no geometry, undecided, or a refusal."""

    @property
    def policies(self) -> tuple[Policy, ...]:
        """Every policy its states actually used, in enum order.

        A block can be decided differently per state, because the rules match on measured
        geometry and geometry varies with the state: FD's stuffed pumpkin is 12 flat states
        and 8 taller ones, so a thin-things-get-no-collision rule catches half of it.

        Reporting one policy for the whole block, as the last state to be compiled used to,
        said ``none`` for that block while 8 of its 20 states compiled as ``visual`` at 36
        cubes -- a report that read as free and cost 36 entities. Hence the set.
        """
        # key=lambda p: p.value, not key=Policy.value -- sorted() calls the key with the
        # element, so passing the descriptor hands it a Policy where it wants self.
        return tuple(sorted({s.chosen.policy for s in self.states if s.chosen is not None},
                            key=lambda p: p.value))

    @property
    def mixed(self) -> bool:
        """Whether the states of this block were decided differently."""
        return len(self.policies) > 1

    @property
    def undecided(self) -> bool:
        return self.note == "undecided"

    @property
    def usable(self) -> bool:
        return any(s.decided for s in self.states)

    @property
    def worst(self) -> StatePlan | None:
        """The state that costs the most. A server pays this whenever the block is placed."""
        decided = [s for s in self.states if s.decided]
        return max(decided, key=lambda s: (s.cubes, s.state)) if decided else None

    @property
    def cubes(self) -> int | None:
        worst = self.worst
        return None if worst is None else worst.cubes

    def totals(self) -> dict[str, int]:
        """Cube cost summed over states, and the worst single state."""
        decided = [s for s in self.states if s.decided]
        return {
            "states": len(self.states),
            "compiled": len(decided),
            "cubes_total": sum(s.cubes for s in decided),
            "cubes_worst": max((s.cubes for s in decided), default=0),
        }


@dataclasses.dataclass(frozen=True)
class PolicyTable:
    """The caller's collision decisions. Data, not policy the compiler holds."""

    rules: tuple[tuple[Mapping[str, Any], str, str], ...] = ()
    blocks: Mapping[str, str] = dataclasses.field(default_factory=dict)
    min_thickness: float | None = None
    source: Mapping[str, Any] = dataclasses.field(default_factory=dict)
    explicit: Mapping[str, Any] = dataclasses.field(default_factory=dict)

    @classmethod
    def load(cls, path: pathlib.Path) -> "PolicyTable":
        document = json.loads(path.read_text(encoding="utf-8"))
        unknown = set(document) - {"rules", "blocks", "min_thickness", "source", "explicit",
                                   "_comment"}
        if unknown:
            raise CompileError(f"unknown key(s) in policy table: {', '.join(sorted(unknown))}")
        rules = []
        for index, rule in enumerate(document.get("rules") or ()):
            when = rule.get("when") or {}
            bad = set(when) - _RULE_KEYS
            if bad:
                raise CompileError(
                    f"rule {index} matches on {', '.join(sorted(bad))}; only "
                    f"measured geometry is allowed ({', '.join(sorted(_RULE_KEYS))})"
                )
            if rule.get("policy") not in {p.value for p in Policy}:
                raise CompileError(f"rule {index} names no known policy: {rule.get('policy')!r}")
            # The policy is kept, not just the index: dropping it here is what made every
            # rule match resolve to no policy at all, and every block report undecided.
            rules.append((when, str(rule["policy"]), str(index)))
        return cls(
            rules=tuple(rules),
            blocks=dict(document.get("blocks") or {}),
            min_thickness=document.get("min_thickness"),
            source=dict(document.get("source") or {}),
            explicit=dict(document.get("explicit") or {}),
        )

    def decide(self, block: str, caps: Capabilities, max_thickness: float | None):
        """The policy for a *state*'s geometry, and how the table decided.

        Per state, not per block: rules match measured geometry, and a block's geometry
        changes with its state, so a table can legitimately decide one block both ways.
        """
        named = self.blocks.get(block)
        if named is not None:
            return _policy(named), f"block:{block}"
        for when, policy, index in self.rules:
            if _matches(when, caps, max_thickness):
                return _policy(policy), f"rule:{index} {policy}"
        return None, None


def _policy(name: str) -> Policy | None:
    for policy in Policy:
        if policy.value == name:
            return policy
    return None


def _matches(when: Mapping[str, Any], caps: Capabilities, max_thickness: float | None) -> bool:
    if "full_cube" in when and bool(when["full_cube"]) is not caps.full_cube:
        return False
    if "thin_axis" in when and when["thin_axis"] != caps.thin_axis:
        return False
    if "multi_part" in when and bool(when["multi_part"]) is not caps.multi_part:
        return False
    if "box_count" in when and int(when["box_count"]) != caps.box_count:
        return False
    if "max_thickness" in when:
        if max_thickness is None or max_thickness > float(when["max_thickness"]):
            return False
    return True


def _geometry_map(spec: Mapping[str, Any]) -> Geometry:
    """A geometry the caller wrote down, from {boxes: [[x0,y0,z0,x1,y1,z1], ...]}."""
    boxes = tuple(tuple(int(c) for c in b) for b in spec.get("boxes") or ())
    return Geometry(boxes, source=str(spec.get("source") or "explicit"))


def compile_block(
    block: str,
    blockstate: Mapping[str, Any],
    roots: list[pathlib.Path],
    vanilla: pathlib.Path | None,
    table: PolicyTable,
    limits: CubeLimits,
    materialise_cubes: bool = False,
) -> BlockPlan:
    """Compile one block across every state its blockstate enumerates.

    ``materialise_cubes`` tiles as well as prices. Off by default because a report only needs
    the number, and tiling 21,880 states is not free.
    """
    if not table.blocks and not table.rules:
        raise CompileError("policy table decides nothing; every block would be undecided")

    plans: list[StatePlan] = []
    decided_policy: Policy | None = None
    matched: str | None = None
    for state in states(blockstate):
        try:
            geometry = measure_state(block, blockstate, dict(state), roots, vanilla)
        except GeometryError as exc:
            plans.append(StatePlan(tuple(sorted(state.items())), Geometry(), derive(Geometry()), (), None,
                                  refusal=str(exc)))
            continue
        caps = derive(geometry)
        thickness = min((min(b.as_tuple()[a + 3] - b.as_tuple()[a] for a in range(3))
                         for b in geometry.boxes), default=None)
        offered = options(
            geometry,
            limits,
            source=_geometry_map(table.source[block]) if block in table.source else None,
            explicit=_geometry_map(table.explicit[block]) if block in table.explicit else None,
            min_thickness=table.min_thickness,
        )
        policy, how = table.decide(block, caps, thickness)
        if policy is None:
            plans.append(StatePlan(tuple(sorted(state.items())), geometry, caps, offered, None))
            continue
        decided_policy, matched = policy, how
        try:
            chosen = choose(offered, policy)
        except CollisionError as exc:
            plans.append(StatePlan(tuple(sorted(state.items())), geometry, caps, offered, None,
                                  refusal=str(exc)))
            continue
        tiled: tuple = ()
        if materialise_cubes:
            try:
                tiled = tuple(tile(chosen.regions, limits))
            except TilingError as exc:
                plans.append(StatePlan(tuple(sorted(state.items())), geometry, caps, offered,
                                      None, refusal=f"priced at {chosen.cubes} but will "
                                                    f"not tile: {exc}"))
                continue
            if len(tiled) != chosen.cubes:
                raise CompileError(
                    f"priced at {chosen.cubes}, tiler produced {len(cubes)}")
        plans.append(StatePlan(tuple(sorted(state.items())), geometry, caps, offered, chosen,
                              None, tiled))

    if not plans:
        return BlockPlan(block, (), None, None, "no states")
    if decided_policy is None:
        note = "no geometry" if all(s.refusal for s in plans) else "undecided"
        return BlockPlan(block, tuple(plans), None, None, note)
    return BlockPlan(block, tuple(plans), decided_policy, matched, None)


def compile_mod(
    blockstates: pathlib.Path,
    roots: list[pathlib.Path],
    vanilla: pathlib.Path | None,
    table: PolicyTable,
    limits: CubeLimits,
    materialise_cubes: bool = False,
) -> tuple[BlockPlan, ...]:
    """Compile every blockstate in a directory, in name order."""
    plans: list[BlockPlan] = []
    for path in sorted(blockstates.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        plans.append(compile_block(path.stem, document, roots, vanilla, table, limits,
                                  materialise_cubes))
    return tuple(plans)


def cube_count(plan: BlockPlan, state: StatePlan, limits: CubeLimits) -> tuple[int, tuple[Cube, ...]]:
    """Tile the chosen regions and check the tiler agrees with the price.

    The count is re-derived rather than read off the option, so a pricing bug and a tiling
    bug cannot agree by accident.
    """
    try:
        cubes = tile(state.regions, limits)
    except TilingError as exc:
        raise CompileError(f"priced at {state.cubes} but will not tile: {exc}") from exc
    if len(cubes) != state.cubes:
        raise CompileError(f"priced at {state.cubes}, tiler produced {len(cubes)}")
    return len(cubes), tuple(cubes)


def report(plans: Iterable[BlockPlan], namespace: str) -> str:
    """A table a person can read and argue with."""
    plans = list(plans)
    width = max((len(p.id.split(":")[-1]) for p in plans), default=10)
    rows = [
        f"{'BLOCK'.ljust(width)}  {'POLICY':9}  {'STATES':>6}  {'REGIONS':>7}  {'CUBES':>6}  HOW",
        "-" * (width + 46),
    ]
    for plan in sorted(plans, key=lambda p: (-(p.cubes or 0), p.id)):
        worst = plan.worst
        if plan.mixed:
            policy = "+".join(p.value for p in plan.policies)
        elif plan.policy:
            policy = plan.policy.value
        else:
            policy = plan.note or "-"
        rows.append(
            f"{plan.id.split(':')[-1].ljust(width)}  {policy:9}  "
            f"{len(plan.states):6}  {len(worst.regions) if worst else 0:7}  "
            f"{plan.cubes if plan.cubes is not None else 0:6}  {plan.matched or '-'}"
        )
    decided = [p for p in plans if p.usable]
    mixed = [p for p in plans if p.mixed]
    undecided = [p for p in plans if p.undecided]
    refused = [p for p in plans if not p.usable and not p.undecided]
    total = sum(p.cubes or 0 for p in decided)
    worst_overall = max((p.cubes or 0 for p in decided), default=0)
    rows.append("-" * (width + 46))
    rows.append(
        f"{len(plans)} blocks in {namespace}: {len(decided)} compiled, "
        f"{len(undecided)} undecided, {len(refused)} refused"
    )
    rows.append(
        f"worst single state {worst_overall} cubes; "
        f"{total} cubes summed over every block's worst state"
    )
    if mixed:
        rows.append(
            f"{len(mixed)} block(s) decided differently per state, shown as policy+policy"
        )
    return "\n".join(rows)


__all__ = [
    "BlockPlan",
    "CompileError",
    "PolicyTable",
    "StatePlan",
    "compile_block",
    "compile_mod",
    "cube_count",
    "report",
]