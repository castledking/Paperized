"""Blockstate + state -> the models that apply, and how each is turned. One question.

    blockstate JSON, state  ->  BlockstateResolver  ->  placements

**Which models does this blockstate draw for this state, and with what rotation?**

Nothing about geometry. A :class:`Placement` is a model reference and its ``x``/``y``
rotation; resolving the model and turning its boxes are other stages
(:mod:`paperized.decompose`, :mod:`paperized.compose`). This module reads JSON and
evaluates conditions, and imports nothing from the rest of the package.

Both blockstate forms are one question here:

* ``variants`` -- exactly one variant key matches a state. A key lists some properties
  (``"facing=east,half=bottom"``) or none (``""``); properties it does not list are not
  constrained. No match, or two, is an error: picking one would draw a shape the game
  would not.
* ``multipart`` -- every part whose ``when`` holds applies, all at once. That is the whole
  difference: a variant is *one* model, a multipart state is the *union* of several.

## Conditions, as the format defines them

A ``when`` is a map of property to value, all of which must hold; ``"a|b"`` holds for
either value; a leading ``!`` negates. ``{"OR": [...]}`` and ``{"AND": [...]}`` nest. No
``when`` at all always holds. JSON booleans are read as the strings the game compares
(``true`` -> ``"true"``).

A condition naming a property the state does not have raises, rather than reading as
false: a missing property is a caller's mistake, and treating it as "not connected" draws a
plausible, wrong shape.

## Random alternatives

An ``apply`` (or variant) that is a *list* is a weighted random choice of one model. The
game picks per position, so there is no single answer; :attr:`Placement.alternatives`
carries every choice and the caller decides whether they agree.

## State spaces

A blockstate names property *values* only where a condition mentions them; the full value
set is declared in the mod's code. A wall's ``north`` is ``none|low|tall``, and ``none``
never appears in its multipart. :func:`condition_classes` therefore returns the values the
conditions mention plus :data:`UNMENTIONED`, which stands for every value no condition
names -- all of which draw identically. Enumerating those classes reaches every distinct
drawing the blockstate can make. A property whose conditions name exactly ``true`` and
``false`` is a boolean and gets no UNMENTIONED class, because it has no other value.

It is a superset of what the game reaches, not the declared state space. Which
combinations are reachable is block *behaviour*, not blockstate data: a vanilla wall drops
its post only on a straight run, so a post-less corner is enumerated here and never drawn
in game. Nothing in the JSON says so, and this module does not guess.
"""

from __future__ import annotations

import dataclasses
import itertools
from typing import Any, Iterator, Mapping

#: The class of every value no condition names. Not a real property value.
UNMENTIONED = "<unmentioned>"

#: A property named with exactly these values is a boolean, and has no others.
BOOLEAN = frozenset({"true", "false"})


class BlockstateError(Exception):
    """A blockstate cannot be resolved for a state. Always fatal, never a fallback."""


@dataclasses.dataclass(frozen=True)
class Model:
    """One model reference with the blockstate's rotation for it."""

    ref: str
    x: int = 0
    y: int = 0
    weight: int = 1


@dataclasses.dataclass(frozen=True)
class Placement:
    """One applied entry: a model, or a weighted random choice between several."""

    alternatives: tuple[Model, ...]

    @property
    def model(self) -> Model:
        """The single model, when there is no random choice."""
        if len(self.alternatives) != 1:
            raise BlockstateError(
                f"a random choice of {len(self.alternatives)} models has no single model: "
                f"{[m.ref for m in self.alternatives]}"
            )
        return self.alternatives[0]


def is_multipart(blockstate: Mapping[str, Any]) -> bool:
    return "multipart" in blockstate


def placements(blockstate: Mapping[str, Any], state: Mapping[str, str]) -> tuple[Placement, ...]:
    """Everything this blockstate draws for ``state``, in the blockstate's own order."""
    state = {k: _text(v) for k, v in state.items()}
    if "multipart" in blockstate:
        return tuple(
            _placement(part.get("apply"))
            for part in blockstate["multipart"]
            if _holds(part.get("when"), state)
        )
    variants = blockstate.get("variants")
    if not isinstance(variants, Mapping) or not variants:
        raise BlockstateError("blockstate has neither variants nor multipart")
    matching = [key for key in variants if _key_matches(key, state)]
    if len(matching) != 1:
        raise BlockstateError(
            f"state {state} matches {len(matching)} variant keys "
            f"({matching or 'none'}); exactly one is how the format draws a block"
        )
    return (_placement(variants[matching[0]]),)


def condition_classes(blockstate: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    """Per property, the values its conditions or variant keys name, plus UNMENTIONED.

    For a variants blockstate the keys name every value that draws something, so no
    UNMENTIONED class is added: a state outside the keys matches no variant.
    """
    named: dict[str, set[str]] = {}
    if "multipart" in blockstate:
        for part in blockstate["multipart"]:
            _collect(part.get("when"), named)
        return {p: tuple(sorted(v)) if v == BOOLEAN else (*sorted(v), UNMENTIONED)
                for p, v in sorted(named.items())}
    for key in blockstate.get("variants") or {}:
        for prop, value in _key_pairs(key):
            named.setdefault(prop, set()).add(value)
    return {p: tuple(sorted(v)) for p, v in sorted(named.items())}


def states(blockstate: Mapping[str, Any]) -> Iterator[dict[str, str]]:
    """Every combination of :func:`condition_classes`, in a fixed order.

    For a variants blockstate, combinations no key matches are skipped: a key listing two
    properties says nothing about pairs it does not list.
    """
    classes = condition_classes(blockstate)
    names = list(classes)
    for values in itertools.product(*(classes[n] for n in names)):
        state = dict(zip(names, values))
        if "multipart" not in blockstate:
            if sum(_key_matches(k, state) for k in blockstate.get("variants") or {}) != 1:
                continue
        yield state


# --- conditions ----------------------------------------------------------------------


def _text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _holds(when: Any, state: Mapping[str, str]) -> bool:
    if when is None:
        return True
    if not isinstance(when, Mapping):
        raise BlockstateError(f"a when must be an object, got {when!r}")
    if "OR" in when or "AND" in when:
        if len(when) != 1:
            raise BlockstateError(f"OR/AND must be the only key of its object: {dict(when)}")
        op, terms = next(iter(when.items()))
        results = [_holds(t, state) for t in terms]
        return any(results) if op == "OR" else all(results)
    return all(_value_holds(prop, _text(expected), state) for prop, expected in when.items())


def _value_holds(prop: str, expected: str, state: Mapping[str, str]) -> bool:
    if prop not in state:
        raise BlockstateError(
            f"a condition names property {prop!r}, which the state {dict(state)} does not have"
        )
    negate = expected.startswith("!")
    allowed = set((expected[1:] if negate else expected).split("|"))
    return (state[prop] in allowed) != negate


def _collect(when: Any, named: dict[str, set[str]]) -> None:
    if not isinstance(when, Mapping):
        return
    for key, value in when.items():
        if key in ("OR", "AND"):
            for term in value:
                _collect(term, named)
            continue
        text = _text(value)
        named.setdefault(key, set()).update(text.lstrip("!").split("|"))


def _key_pairs(key: str) -> list[tuple[str, str]]:
    pairs = []
    for part in key.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise BlockstateError(f"variant key {key!r} has a term without '=': {part!r}")
        prop, value = part.split("=", 1)
        pairs.append((prop.strip(), value.strip()))
    return pairs


def _key_matches(key: str, state: Mapping[str, str]) -> bool:
    for prop, value in _key_pairs(key):
        if prop not in state:
            raise BlockstateError(
                f"variant key {key!r} names property {prop!r}, which the state "
                f"{dict(state)} does not have"
            )
        if state[prop] != value:
            return False
    return True


# --- applied models ----------------------------------------------------------------


def _placement(apply: Any) -> Placement:
    entries = apply if isinstance(apply, list) else [apply]
    if not entries:
        raise BlockstateError("an apply with no models")
    return Placement(tuple(_model(e) for e in entries))


def _model(entry: Any) -> Model:
    if not isinstance(entry, Mapping) or not entry.get("model"):
        raise BlockstateError(f"an applied entry needs a model: {entry!r}")
    x, y = int(entry.get("x", 0) or 0), int(entry.get("y", 0) or 0)
    for axis, angle in (("x", x), ("y", y)):
        if angle % 90:
            raise BlockstateError(f"{entry['model']}: {axis} rotation {angle} is not a right angle")
    return Model(str(entry["model"]), x % 360, y % 360, int(entry.get("weight", 1) or 1))


__all__ = [
    "BlockstateError",
    "Model",
    "Placement",
    "UNMENTIONED",
    "condition_classes",
    "is_multipart",
    "placements",
    "states",
]
