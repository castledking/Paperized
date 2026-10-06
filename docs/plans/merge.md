# BoxMerger

`src/paperized/merge.py`.

```
IR geometry boxes  ->  BoxMerger  ->  region set
```

One question: **can these boxes be represented as fewer axis-aligned boxes without changing
the space they occupy?** Boxes in, boxes out. No family names, carriers, collision, shulkers
or runtime. Cutting regions into whatever a runtime can place is the tiler's job.

## The invariant

**Occupancy is preserved exactly, and the output is a partition.** The union of the output is
the union of the input, and no two output boxes share interior, so the summed volume of the
output *is* the occupied volume.

```
[0,0,0 -> 8,16,16] + [8,0,0 -> 16,16,16]   ->  [0,0,0 -> 16,16,16]     same space
[0,0,0 -> 8,8,16]  + [8,8,0 -> 16,16,16]   ->  unchanged               bounds would add two octants
```

Partition rather than any cover, because overlap makes "same occupied volume" impossible to
check by summing, and it hands the tiler space it would fill twice.

The check runs on every call, not only in tests, and a violation raises `MergeError`. A
merger that returned a different shape would be wrong quietly: every number downstream would
still look plausible.

## Fewer, not minimal

Minimum box partition of a 3D rectilinear shape is NP-hard, so this does not claim a minimum.
It keeps the smallest of a fixed set of deterministic candidates:

1. **Carve the input as authored.** Boxes are taken largest first, and each keeps only the
   space no earlier box claimed. On a partition nothing is carved, so this candidate is the
   input itself. It wins ties, so authored cut lines survive unless re-cutting buys something.
2. **Greedy re-partition, once per axis order.** Six candidates. On its own, greedy found 6
   regions for a wall crossing where the post plus four arm stubs is 5. Carving is what
   finds the 5.

Each candidate is then face-merged: two boxes sharing one whole face become one, until no two
do.

Guarantee: **a partition never comes back larger.** An overlapping input can, and that is
honest. A plus authored as two crossing bars is three regions as a partition.

Identical and contained boxes collapse. This is the one place the decomposer's deliberately
kept duplicates become one shape. Zero-volume boxes (planes) are kept verbatim and never
merged: occupancy cannot see them, and dropping a visible plane would pass every volume check.

## How it is checked

Tests never use the merger's grid. `occupancy()` in the tests is an independent oracle: it
probes a point in every cell of the lattice that both box sets are drawn on, and counts which
boxes contain it, using `Fraction`. It is itself shown to fail on a bounding-box merge and on
an overlap, and the postcondition is shown to raise when every strategy is broken.

Shape fixtures are vanilla's own template elements, composed the way the blockstates compose
them, with counts derived from the geometry:

| shape | regions |
| --- | --- |
| glass pane: post, dead end, straight | 1 each (the post alone is 5 coincident boxes) |
| glass pane: corner, tee, cross | 2, 2, 3 |
| wall: post, post + arm, straight with no post | 1, 2, 1 |
| wall: straight with post, crossing | 3 (arms are lower than the post), 5 |
| fence: post, one side, straight, crossing | 1, 3, 5, 9 (the rail gap never merges) |
| stairs, outer, inner | 2, 2, 3 (a cube less one octant) |

### CMB's hitbox counts are not region counts

CMB's "wall = 3, fence = 2, vertical slab = 4" count **shulkers**, not regions. A shulker
hitbox is a cube, so a 16x16x8 vertical slab is one region tiled as four 8-cubes, and a wall
column is one region stacked as three 0.5 cubes to reach 1.5. Those numbers belong to the
tiler's fixtures. Here, a vertical slab is 1 region, and a wall depends on its connections, as
the table shows.

## What it found

The sweep covers every model any blockstate of either mod names, multipart parts included:

```
CMB  943 models   in = out for all 943       (647 x1, 199 x2, 97 x3)
FD   172 models   171 measured, 167 unchanged
                  honey_glazed_ham stage1 12 -> 11, stage3 9 -> 8
                  roast_chicken stage2       16 -> 15
                  rope_fence_gate_open        3 -> 5
```

**Authored models are already as merged as they get.** On single models the merger is almost
a no-op. Its work is on *composed* geometry: multipart blockstates, where a wall's post and
arms overlap and a pane's post coincides with four noside boxes. The pane, wall and fence
fixtures above are exactly that composition, done by hand in the test.

**Overlap costs regions.** FD's open fence gate has a hinge authored overlapping its post, and
a partition has to cut one around the other: 3 boxes in, 5 regions out. The tiler will pay
for that in entities, so it is pinned as a fixture rather than discovered there.

## Next

The merger has almost nothing to do until multipart blockstates are composed. Today the
decomposer refuses them (114 of CMB's blockstates and 2 of FD's), and the tests compose
panes, walls and fences by hand. So multipart composition, a stage of its own, is what
gives this one real input. After that comes `HitboxTiler`: regions to placeable cubes. That
is the first stage that knows a runtime exists, and the point to revisit Java.
