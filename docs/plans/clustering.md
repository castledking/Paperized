# Clustering — how many geometry families actually exist?

Measured across **both** mods now, with the same normaliser
(`paperized/analysis/geometry.py`) so the two datasets are comparable.

## Granularity comparison (FD)

| granularity | distinct | verdict |
|---|---|---|
| property spaces | 17 | too coarse — CMB's wall/fence/pane collide |
| raw box fingerprints | 23 | too fine — every bespoke block its own cluster |
| capability signatures | 22 | long tail is genuine |

## CMB, measured the same way

296 served blocks, 381 blockstates, all resolved. Family × geometry:

| family | n | measured geometry |
|---|---|---|
| cube | 61 | `full_cube` |
| pillar | 13 | `full_cube` |
| stairs | 64 | 3 boxes |
| slab | 61 | single box |
| wall | 75 | **multipart** |
| fence | 5 | **multipart** |
| pane | 1 | **multipart** |
| button | 1 | thin on z |
| pressure_plate | 1 | single box |

Two results worth having:

**The multipart rejection is rediscovered independently.** Geometry alone flags all 81
wall/fence/pane blocks as multipart — which is exactly the set
`tools/carrier_eligibility.py` rejects for carriers. Two unrelated methods agreeing on the
same 81 blocks is much stronger than either alone, and it means the eligibility gate could
in principle be derived from geometry rather than reimplemented.

**Pillars measure as `full_cube`.** A pillar is a cube ridden through a rotation
property, so its collision genuinely is a full cube — the column is narrower than a block
but the hitbox is not. Worth stating because it looks wrong until you remember a pillar
must occupy a whole block cell.

## Combined

| | FD | CMB |
|---|---|---|
| blocks | 132 | 296 |
| full cube | 92 | 74 |
| single short box | 5 | 62 |
| multi-box | 35 | 64 |
| thin | — | 1 |
| multipart (never a carrier) | 2 | 81 |

**The shapes agree, the totals differ, and that is the point.** CMB is dominated by two
families (slabs and stairs) that happen to be geometrically simple; FD is 70% cubes and
then a long bespoke tail. Neither is representative, which is the argument for running both.

## The shape is a power law

```
 FD:  92 of 132 blocks are ONE geometry.
      The other 40 are 21 geometries, 17 of them singletons.
 CMB: 74 of 296 are one geometry; the other 222 are mostly 1- and 3-box.
```

A family list would need ~22 entries for FD alone and every entry after the first two
would cover exactly one block. That is a lookup table wearing a taxonomy's clothes.

## Design consequence: geometry is data, family is interpretation

```
mod block ──▶ collision: boxes: [...]      ← the primitive, measured
              properties: {...}
              capabilities: {...}           ← derived from boxes
                    │
                    ▼
              runtime strategy              ← furniture + scaled shulkers
```

`wall`, `fence`, `pane`, `bespoke` are **profiles over boxes**, not the thing the compiler
depends on. Corroborated by CMB's own generator: `vanilla_carriers.py` gives wall, fence
and pane *identical* `used_properties` (`east/north/south/west`, all boolean). Nothing in
the declared state space separates them — only geometry does.

The user's refinement is the right vocabulary, and worth adopting explicitly:

> The 17 singleton geometries are **classified geometrically, not taxonomically**.

`apple_pie` has a box list. That is a complete description. It is not "unclassified" and
needs no `ApplePieFamily`; `taxonomy: bespoke` is a complete and honest answer. There is no
failure mode here, and calling it unclassified implies one that does not exist.

## What is next, and what is deliberately not

Next: **box decomposition** — `boxes → merge into N regions → tile with scaled shulkers`.
CMB already does this, but hand-authored per family (wall = 3, fence = 2, vertical slab =
4 tiled). Generalising it is:

```
resolve inheritance → resolve transforms → extract cuboids → normalise
    → merge compatible adjacent cuboids → box set → hitbox tiler
```

Correctness before entity count: "can these 17 boxes become 4 shulkers instead of 7" is an
optimisation, not the first question. `BoxDecomposer`, `BoxMerger` and `HitboxTiler` as
separate stages.

**Glass panes are the permanent regression fixture.** Not because panes are special, but
because a pane proves the architecture is not secretly cube + stairs + slab + wall + fence.
If Paperized can take a pane's geometry and independently produce visual, collision,
placement and runtime representation, it can translate arbitrary geometry rather than a
fixed vocabulary. That is the capability worth demonstrating.

## Honesty note

FD's numbers are measured. CMB's are measured for the **served** set (296 of 381
blockstates; the rest are deferred). The two columns are not the same scope, so the
"combined" row is indicative rather than a strict union.
