# CollisionPolicy

`src/paperized/collision.py`.

```
visual geometry  ->  CollisionPolicy  ->  collision geometry  ->  BoxMerger  ->  HitboxTiler
```

One question: **what could this block's collision geometry be, and what does each choice
cost?**

## Why this stage exists at all

Tiling the visual model exactly is cheap for a block and ruinous for anything thin — a
pressure plate is **196 cubes**, because it is drawn as a plate a pixel thick. The game
gives it no collision whatsoever.

```
polished_deepslate_pressure_plate
  source collision   none
  visual collision   196 cubes
  thickened to 2     refused -- as drawn it is thinner than the smallest cube
```

So collision cannot be *derived* from the visual model. A stage that did would have to
either invent the answer or quietly spend 196 entities per plate. The game agreeing that a
pressure plate does not collide is the evidence that these are different things, and asking
is the only honest response.

## It reports; it does not choose

`options()` builds every option the inputs allow and prices each one. `choose()` returns
the one the caller names. There is **no default and no "cheapest"** — deciding that a
196-cube plate is acceptable, or that a rug may be walked through, is the caller's call per
block, exactly like selecting which states to compile. A compiler that quietly picked the
cheapest option would make the entity cost of a server invisible until it was already too
late.

| policy | collision geometry | supplied by |
| --- | --- | --- |
| `NONE` | nothing | — |
| `SOURCE` | the source game's own shape | the caller |
| `VISUAL` | the visual model's boxes, as drawn | the visual geometry |
| `THICKENED` | the visual boxes, each thin edge grown to `min_thickness` | the visual geometry |
| `EXPLICIT` | an override | the caller |

`SOURCE` is supplied rather than read because the game's own collision shape lives in its
**code**, not its assets — so "the source has no collision" is an *empty geometry*, not a
missing one, and only the caller can say which.

`EXPLICIT` means the caller wrote the geometry down. It never means this module knows what
some particular block should do; that is the family taxonomy in disguise.

## Cost, and the cut it is priced on

An option's cost is the cubes the tiler needs for it. The tiler covers each region on its
own, so the count depends on how the space is cut, and **two exact cuts are always
available**: the merger's partition, and the boxes as given (cubes may overlap, so
overlapping boxes are a valid cover). Neither wins everywhere:

```
WALL_CROSSING, as drawn          post + 4 full overlapping arms   26 cubes
WALL_CROSSING, merged            post + 4 short stubs              34 cubes
across CMB, worst state per wall merged 43                         as given 26
```

Each option is priced on the cheaper of the two and **carries those regions**, with
`Option.cut` naming which. Picking between exact covers of the same space changes the
representation and never the geometry, so it is not a policy decision — and carrying the
regions means what was priced is what gets tiled.

## Thickening

Grows each thin edge to `min_thickness`, rounded **up to whole units**, placed on whole
units as near centred as the original allows. So a thickened box always contains the
original, and thickening never introduces a cut finer than a unit.

Growing about the centre alone put edges on half units, and the merger's partition of the
overlapping result then held half-unit slivers that **no cube could cover** — geometry with
no thin part, refused as too thin. Rounding to whole units is what stops thickening from
producing something the tiler must reject.

Growth is clamped back into the cell rather than clipped, so a floor plate `y 0..1`
thickened to 2 becomes `y 0..2`, not `-1..1`. Nothing ever shrinks.

## Parts with no axis-aligned volume

A rotated box or a zero-thickness plane has no axis-aligned volume to collide with. Such
parts are **left out and counted** in `Option.left_out`, so the loss is on the record
rather than silent — the same rule as the decomposer's `exact` flag.

## The ordering this forces

```
visual model ──▶ VisualGeometry ──────────────────▶ resource-pack rendering
                     │
                     ▼
               CollisionPolicy
                     │
                     ▼
              CollisionGeometry ──▶ merge ──▶ tile ──▶ runtime hitboxes
```

`BoxMerger` and `HitboxTiler` are **collision** operations, not visual-model operations.
That is only true because collision geometry was separated first; had it been derived from
the model, the whole geometry pipeline would have been visually scoped and this ordering
could not have been expressed.

## What it must not know

Asserted against the module's AST, in `test_policy_knows_geometry_not_blocks_or_runtimes`:
no shulker, CraftEngine, entity, Paper, furniture or Minecraft vocabulary as identifiers.
A policy stage that named a block would be making per-block decisions, which is the thing
the caller owns.

## Where the compiler ends

Everything from a model to `Cube[]` in model space is compiler work and knows nothing about
Paper. The first code that knows Paper exists is the translation of a `Cube` into a hitbox
the runtime can place — and the exact-coverage invariant is what such a port would have to
preserve. Keeping the compiler in Python until then means that boundary is an interface
with a test on it, rather than two implementations of the same idea that happen to agree
today.