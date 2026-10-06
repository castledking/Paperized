# Multipart composition

`src/paperized/blockstate.py`, `src/paperized/compose.py`, glued by
`analysis.geometry.measure_state`.

```
blockstate, state  ->  BlockstateResolver  ->  placements (model, x, y)
each model         ->  resolve, BoxDecomposer
each geometry      ->  rotate
all of them        ->  GeometryComposer     ->  geometry  ->  BoxMerger
```

Two new stages, each answering one question. The decomposer is unchanged and still knows
nothing about blockstates.

## BlockstateResolver: which models, turned how

It reads JSON and evaluates conditions, and it imports nothing from the package.

- **Variants:** exactly one key matches. A property the key doesn't list is unconstrained.
  No match, or two, raises.
- **Multipart:** every part whose `when` holds applies, all at once.
- **Conditions,** per the format: `a|b`, leading `!`, nested `OR`/`AND`, and JSON booleans.
  A condition naming a property the state lacks raises. Reading it as false would draw
  "not connected": plausible, and wrong.
- **A list `apply`** is a weighted random choice. Every alternative is kept, and
  `measure_state` accepts the choice only if all alternatives draw the same shape once
  turned.

### State spaces are a superset, on purpose

A blockstate names values only where a condition mentions them. A wall's `none` never
appears in its multipart. So `condition_classes()` gives each property the values it names
plus one `UNMENTIONED` class, which stands for every value no condition names. All such
values draw identically. A property named exactly `true`/`false` is a boolean and gets no
extra class.

That reaches every drawing the blockstate can make, plus some the game never reaches.
Which combinations are reachable is behaviour, not blockstate data: a vanilla wall drops its
post only on a straight run. The JSON doesn't say so, and the resolver doesn't guess.

## GeometryComposer: union, not optimisation

- `rotate(geometry, x, y)` turns a geometry about the block centre, x first, then y, in right
  angles. It is an exact coordinate permutation, so the count never changes.
- `compose(geometries)` returns every box of every part, sorted. Coincident boxes stay
  coincident and overlaps stay overlapping.

**The composer never merges.** A wall's post and arms overlap, and a pane's post coincides
with four `noside` boxes. Deciding how to represent that space is the merger's one job. A
composer that tidied up would be a second place that changes geometry, and the two could
quietly disagree. A test pins this: composed boxes equal the multiset of the parts' boxes.

Rotation direction is checked against shapes the game draws, not against itself:

| check | why it is external |
| --- | --- |
| each wall arm reaches the face it connects to | an arm connecting east touches x = 16 |
| stairs `facing=south` (`y: 90`) has its step on the south half | how a stair faces |
| floor button at `x: 90` is `5,6,14 -> 11,10,16` | the game's own north-facing wall button shape |

Flipping the direction of either axis fails these tests; this was checked by mutation.

## What CMB and FD do

Every enumerated state of all 116 multipart blockstates (CMB 114, FD 2), composed and then
merged:

```
CMB walls   108 blocks  17,388 states   161 distinct shapes
            reachable 9,180 (85 per wall: 81 with post + 4 post-less straights)
            regions   1: 540   2: 864   3: 2,592   4: 3,456   5: 1,728
CMB fences    5 blocks      80 states    16 shapes   regions 1, 3, 5, 7, 9
CMB pane      1 block       16 states    16 shapes   regions 1 x7, 2 x8, 3 x1
FD rope       1 block       32 states    32 shapes   regions 1..5
FD fence      1 block       16 states    16 shapes   regions 1..5
refused     108 states: each wall's everything-unmentioned class, which draws nothing
```

The pane's 16 states come out exactly as `test_merge` derived them by hand: dead ends and
straights 1, corners and tees 2, the cross 3.

**No reachable state gets more regions than it had boxes.** All 3,024 states where merging
increases the count are post-less wall corners and tees. Their arms overlap at the centre,
and the game never draws them. The fence-gate effect (overlap costs regions) is real, but in
CMB it lives only in states that don't exist.

**161 distinct shapes for 108 walls.** Every CMB wall is vanilla's templates under a
different texture, so geometry is shared across blocks, not per block. That's the same "a
power law, not a taxonomy" result the clustering found, now for composed shapes.

## Also fixed on the way

`_loader` searched a root that held a `block/` directory instead of searching inside it.
Every caller passed `models/block` directly, so nothing failed until a test passed a
resource root as-is.

## Next

`HitboxTiler`: regions to placeable cubes. It will take CMB's shulker counts (wall = 3
stacked cubes per column, vertical slab = 4) as fixtures, not the region counts here. It is
the first stage that knows a runtime exists, so that is when to settle the Python/Java seam.

Reachability needs deciding before the tiler emits anything. Tiling the 8,208 unreachable
wall states would ship furniture variants no one can place. Options: a per-block
reachability rule supplied by the consumer (CMB's plugin already knows which wall shapes it
picks), or let the tiler run over whatever states the caller asks for and keep enumeration
out of it. The second keeps the boundary.
