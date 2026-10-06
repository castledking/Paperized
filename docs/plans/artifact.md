# The compiled artifact

`src/paperized/artifact.py`.

```
Paperized compiler ──▶ paperized package ──▶ any backend
```

A backend that can read JSON can consume Paperized's output. That is the whole reason the
package is the contract rather than the Python API: CraftEngine, a Paper plugin and a
future Paperized Server all have to read it, and none should have to import this compiler.

```
paperized package <mod> --policy <table> --out <dir>
```

```
manifest.json      what this is, what version, what is in it
definitions.json   blocks, their states, geometry, collision
assets/            the payload -- models, textures, sounds
```

The JSON says what exists and how it behaves; the asset directory holds the bytes. A
backend that only wants collision reads the definitions and never touches a texture.

## Geometry is per state

```
block -> states[] -> { visual, collision }
```

Not `block -> collision`. FD's stuffed pumpkin is 12 flat states and 8 taller ones, so one
block compiles under two policies, and the compiler once reported it as `none` at 36 cubes
— a row that read as free while eight states cost 36 entities each.

Block-level figures exist under `derived` and are explicitly reported rather than stored:
`policies`, `mixed`, `cubes_worst`, `state_count`, `compiled`. A backend reads `states`.

## Nothing backend-specific

```
collision: { policy: visual, cubes: [ {min: [0,0,0], max: [8,8,8]}, ... ] }
```

Never `shulkers: 4`. Never "this uses a note block carrier". What a runtime hangs off a
cube is that runtime's business, and that is precisely what lets one package feed three
backends that place collision differently. A count would be the tempting cheap emission and
it is exactly wrong: four shulkers, four AABBs and four server-native shapes are four
different placements.

Checked twice — the emitted JSON is walked as strings *and* keys, and the module is walked
as an AST. Prose that disclaims a word is why it takes two: scanning raw text would fail on
this module's docstring for saying it does not mention shulkers.

Both use word boundaries, because plain substring matching reports `paper` inside
`paperized` — the project's own name, which appears in its format field.

## Nothing is dropped silently

| status | meaning |
| --- | --- |
| `compiled` | has `visual` and `collision` |
| `no-geometry` | the source model describes no geometry — FD's 68 canvas signs |
| `undecided` | the policy table did not decide this state |
| `refused` | a policy was chosen and cannot be represented |

Each carries a machine-readable `reason` **and** a human `note`, because a backend must tell
"this state draws nothing" from "this state cannot be represented" without parsing English,
and the raw refusal embeds the block name and the whole state dict in front of the reason.

`no-geometry` and `undecided` are separate statuses on purpose. They are different failures
and need different responses; one number for both hides which one you are looking at.

## What serialisation would have got wrong

CMB's 108 refused states are wall states where **no multipart part applies** — the post is
`when up: true`, so a wall with no base and no connections genuinely draws nothing. That is
correct, and it is a state-level fact the block-level report could not show.

The reason is machine-readable because the prose was not:

```
refused | reason: no-part-applies | note: nothing to compose: no part applies
```

Stripping the prefix needed `rpartition("}: ")`, not `partition(": ")` — the state dict is
full of colons, so splitting on the first one landed inside `{'east': '<unmentioned>'…}`.

## Cubes serialise as min/max, not side

`Cube` is a min corner plus a side, and `as_box()` adds them **exactly**. The artifact
carries the computed corners rather than the side, because 6.02 + 1.02 in floats is
7.039999…, leaving a gap before a neighbour at 7.04. A package that carried the side and
let the backend add it would move that bug to the far side of the boundary.

## Versioning

`format: "paperized"`, `version: 1`, and `read_package` **refuses** a version it does not
know. A version that changed the meaning of a field would otherwise produce a backend that
loads happily and then places things wrongly.

## What is not in here yet

Items, recipes, translations and loot. The schema has room for them and this commit does not
pretend they exist.
