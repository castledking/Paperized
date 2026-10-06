# The IR

`src/paperized/ir.py`. What Paperized knows about a block, and — just as important — what
it refuses to know.

## Shape

```
Block
  id                    farmersdelight:apple_pie
  properties            Properties(...)         arity 8
  geometry              BlockGeometry(visual, collision)
  strategy              CARRIER | FURNITURE | UNRESOLVED
  carrier               str | None              diagnostic only
```

```
BlockGeometry
  visual      Geometry      measured from the model chain
  collision   Geometry      measured from the carrier, or declared
  collision_source   'carrier' | 'furniture' | 'declared'
  differs     bool          whether the two disagree, on purpose or not
```

## Three decisions, and the evidence for each

### 1. Measured geometry is kept beside what is derived from it

Every `Geometry` serialises its own boxes *and* its `Capabilities`. The debugging property
is the point: when a classifier makes a bad decision, the evidence it was given is still
there, rather than having been replaced by the answer.

This is not a style preference. `Capabilities.is_full_cube` once compared `box_count == 1`
against a constant without reading the box, so all 61 of a mod's slabs measured as full
cubes. Nothing crashed; the output looked reasonable. It was wrong in exactly the way this
project exists to prevent. `tests/test_ir.py` has a dedicated regression for it.

### 2. Visual and collision are separate types

Not one optional geometry field. They differ in practice:

| block | visual | collision | why |
|---|---|---|---|
| pillar | parents `cube_column` → `cube` | note_block carrier, full cube | the column is a *texture*, not geometry |
| glass pane | multipart parts | pane-specific collision | composed rendering, single collision |

A pillar is the proof case: its model chain genuinely resolves to a full box, because
`minecraft:block/cube_column` inherits from `cube`. The narrow column is 10/16 across in
the texture and full-size in the model. One field would have to lie about one of the two.

`differs` is surfaced rather than normalised away, because a block whose collision is
deliberately larger than its visual is a design decision and the IR should be able to say
so.

### 3. Nothing names a family

No `wall`, `fence`, `pane`, `stairs`. Clustering both mods showed why: 92 of FD's 132 blocks
are one geometry, and 17 of the remaining 40 are singletons. A taxonomy here would be a
lookup table with an entry per singleton.

Families become **profiles over boxes**, applied by the implementation planner.
`taxonomy: bespoke` is a complete answer, not a failure to classify — `apple_pie` has a
box list, and that is the whole description.

## Capabilities are derived, and only from boxes

| capability | definition | note |
|---|---|---|
| `full_cube` | exactly one box `0,0,0 → 16,16,16` | reads the box, never the count |
| `full_height` | some box spans y 0..16 | |
| `full_footprint` | spans 16 on x or z | |
| `thin_axis` | `x`, `z`, or None | relative to the shape's own span |
| `grounded` | touches y=0 | |
| `multi_part` | the *source blockstate* is multipart | distinct from multi-box |

`thin_axis` being relative rather than absolute matters: a 14-wide cabinet is not a pane,
and a 16-by-2 plate is.

`full_cube` is the field that was wrong, and it is the only one whose failure was
plausible rather than obviously broken. Hence a dedicated test.

## Pipeline position

```
Mod assets
   │
   ▼
Source IR          properties, models, blockstates, recipes, loot, translations
   │
   ▼
Normalized Block IR ──── this file
   │                   visual + collision + capabilities, measured
   │
   ├── BoxDecomposer     model data → CollisionGeometry    ← next
   ├── BoxMerger         boxes → minimal region set
   ▼
Implementation Planning
   │                   carrier | furniture | hitbox strategy | interaction strategy
   ▼
Paperized output
```

`HitboxTiler` is deliberately not built yet. It has one question the IR must settle first:
whether the box list describes visual geometry, collision geometry, or both. The evidence
says they cannot be conflated, which is why `BlockGeometry` has two fields.

## Box is defined once

There were briefly two `Box` types — one in `ir.py`, one in `analysis/geometry.py` — and
the symptom was silent: a measured visual geometry never compared equal to a derived
collision one, so `differs` was `True` for *every* block including ones whose two
geometries were identical. `analysis/geometry.py` now re-exports the IR's `Box`.

Duplicate value types break equality quietly, and the only symptom is a field that is
always wrong.

## Regression fixtures

Before any tiler, these five categories, from both mods:

| fixture | from | what it proves |
|---|---|---|
| slab | CMB | one box, 16×8×16, **not** a cube |
| pillar | CMB | visual and collision from different sources |
| wall / fence / pane | CMB | multipart, never a carrier |
| apple_pie | FD | bespoke multi-box, no family |
| cooking_pot / skillet | FD | partial geometry, thin on one axis |

Glass panes stay the permanent one: a pane proves the architecture is not secretly
cube + stairs + slab + wall + fence.
