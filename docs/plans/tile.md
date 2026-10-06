# HitboxTiler

`src/paperized/tile.py`.

```
region set  ->  HitboxTiler  ->  cubes
```

One question: **how is this geometry represented with the available primitive** — an
axis-aligned cube whose side lies within `CubeLimits(min_side, max_side)`? The tiler doesn't
know what stands in for a cube at runtime, where the geometry came from, or whether the state
that drew it can occur.

## States: enumerated, reachable, selected

Reachability stays out of the whole geometry pipeline, not just out of the tiler.

| | what it is | who knows it |
| --- | --- | --- |
| **enumerated** | a state the blockstate can describe | `blockstate.states()` |
| **reachable** | a state the source game's behaviour can produce | the game's code, not its JSON |
| **selected** | a state this implementation chooses to support | the caller |

Paperized supplies the first set and compiles whatever the caller selects. It does not
invent the middle set: that would need `if wall: ...`, then `if fence: ...`, then a rule per
mod, which is exactly the family taxonomy this project removed. The 8,208 unreachable wall
states in [`compose.md`](compose.md) show the gap is real.

## The invariant

**The union of the cubes is the union of the regions: no missing space, no extra space.**
It is checked per axis on every call, and a violation raises `TilingError`.

Cubes may **overlap**. The merger forbids overlap because its output describes space, and
overlap would make volume uncheckable. The tiler's output is things to place, and the cost
is how many there are. Two overlapping cubes block exactly their union, so forbidding overlap
would only cost more. CMB already relies on this: its pane stacks three overlapping layers.

## Optimal per region, provably

For a region with shortest edge `m`, the cube side is `s = min(m, max_side)`, with
`ceil(L / s)` cubes along each axis, each row flush to both ends. That is the minimum for any
cover of the region:

- no cube inside the region is bigger than `s`, and a smaller one never needs fewer per axis;
- **lower bound:** put `ceil(L / s)` points along each axis, evenly spaced. Neighbours are
  more than `s` apart, so no allowed cube holds two. The product of the counts is how many
  cubes any cover needs.

The tests compute those witness points independently and require the count to match. This
is optimal **per region**: cubes don't cross regions, so how space was cut changes the count
(see below).

## Refusals

A region with no volume, or one thinner than `min_side`, raises. Making something thick
enough to represent is a choice about *which geometry to represent*. It belongs upstream,
where it is visible.

## How it is checked

- **Exactness:** `tests/oracle.py`, the same point-probe oracle as the merger's, which shares
  no code with the tiler.
- **Optimality:** the witness points above.
- **Two-sided:** a cube that sticks out fails the oracle, a gap raises `TilingError`, and
  fewer cubes than witnesses fails the bound. A mutation run halving the side failed 210
  tests; dropping the flush last cube failed 125.
- **Representation:** `Cube.as_box` adds the far corner exactly. In floats, `6.02 + 1.02` is
  `7.039999…`, which left a 1e-15 gap before a neighbour at `7.04`. The oracle caught it on
  real FD geometry. A runtime adapter doing that addition in floats will make the same gap.

CMB's hand-authored counts are fixtures here, where they belong:

| geometry | cubes | CMB |
| --- | --- | --- |
| vertical slab, 16x16x8 | 4 | 4 |
| wall collision column, 8x24x8 | 3 | 3 |
| horizontal stair, two regions | 6 | 6 |
| vanilla pane post, 2x16x2 | 8 | 3 layers, made thicker than the model |

## What CMB and FD cost, tiled exactly

Using the shulker's range (1..256 units), visual geometry as collision, every state the
blockstates enumerate, and the worst state per block:

```
CMB  381 blocks   median 7 cubes   374 at <= 30   2 over 100
     worst: pressure plate 196 (1 px thick), tinted glass pane 136, fences 84 (2 px rails)
     refused: pressed pressure plate, 0.5 px thick
FD    48 blocks   median 2.5       35 at <= 30   10 over 100
     worst: honey glazed ham 384, skillet 358, roast chicken 290, baskets 280, rug 256
```

**Exact tiling is cheap for blocks and expensive for thin things.** Cost grows with
area ÷ thickness². That isn't a tiler problem; the tiler is optimal for what it is given.
**Collision geometry is a different thing from visual geometry**, and the game agrees:
pressure plates have no collision, a pane's collision is not its model, and a wall's
collision is 24 tall.

### Cut lines change the count

The same shapes, tiled from merged regions and from the authored, overlapping boxes:

```
CMB  merged 5,695 cubes   authored 5,455   (authored fewer on 117 shapes, merged on 54)
FD   merged 27,041        authored 26,875
```

The merger minimises *regions*, and a fewer-regions cut is not always a fewer-cubes cut.
A wall crossing as a post plus four short stubs tiles worse than a post plus four full,
overlapping arms. Both are exact. Choosing a cut for cube count is a later optimisation;
the tiler takes either.

## Next: collision policy

Before anything reaches a runtime, a stage has to decide **what collision geometry to
represent**: none, declared (the game's own collision shape), visual, or visual thickened to
a minimum. That is a policy with a trade-off — exactness versus entity count — and it is the
caller's to make per block, like state selection. `analysis.geometry.collision_from` already
has the declared/carrier/visual split to build on. It should report the entity cost of each
choice, so the trade-off is visible.

The tiler's output is still pure geometry: cubes in model space. Turning a `Cube` into a
runtime hitbox — CraftEngine's position config space, scale, the furniture definition — is
the first code that knows Paper exists. That is the runtime adapter, and the natural place
for the Java seam.
