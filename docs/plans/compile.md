# The compilation

`src/paperized/compile.py`.

```
blockstates + model roots + a caller's policy table
    -> visual geometry -> collision options -> the one the caller named
    -> merged regions -> cubes
```

Every stage before this was testable alone, which is how each got checked. This runs the
chain and reports the total, so a block that costs 196 cubes is a number in a table rather
than something discovered on a server.

```
paperized compile <mod-or-pack> --policy examples/cmb-policy.json --vanilla-models <path>
```

## CMB, compiled

```
BLOCK                             POLICY     STATES  REGIONS   CUBES  HOW
black_concrete_wall               visual        162        5      26  rule:1 visual
blue_nether_brick_fence           visual         16        9      52  rule:1 visual
polished_deepslate_button         visual         24        1      24  rule:1 visual
andesite_brick_stairs             visual         40        3       7  rule:1 visual
polished_deepslate_pressure_plate none            2        0       0  rule:0 none
...
381 blocks in cinchsmissingblocks: 381 compiled, 0 undecided, 0 refused
worst single state 128 cubes; 4349 summed over every block's worst state
```

Two figures worth keeping: a wall's worst state is **26 cubes**, which is the as-given cut
winning over the merged cut's 34 — the first place that choice shows up in a real block.
And the tinted glass pane at **128** is the only block above 100, which is the first number
to argue with.

## The policy table is the caller's data

There is **no default policy**, and that is the design rather than an omission. A block the
table does not decide comes out `undecided` and costs nothing.

```
{"when": {"max_thickness": 1}, "policy": "none"}
{"when": {}, "policy": "visual"}
```

An empty `when` is a catch-all, so the two rules above read as "a pixel-thick thing gets
no collision, everything else collides as drawn". That second clause is the naive starting
point and the thing to argue with — it is what puts the pressure plate at 196 cubes and
would put a rug's whole visual model in the way.

The table may match on a **block id** or on **measured geometry** — `full_cube`,
`thin_axis`, `max_thickness`, `box_count`, `multi_part`. Anything else is refused at load,
including a family name: "is it a wall" is the taxonomy this project removed, arriving
through the policy table instead of through the decomposer, and
`test_the_table_refuses_matching_on_a_family_name` exists for exactly that.

Rules are tried in order, first match wins, and a named block beats any rule. So a table can
say "thin and flat things get no collision" and still single out one block.

`examples/cmb-policy.json` ships as a first draft and says so in its own `_comment`.

## States, and what a block costs

States are **enumerated**, never invented — reachability is the game's business and stays
out of this pipeline. Every enumerated state is compiled, and a block's cost is the **worst**
of its states, because a server pays that on every tick it is placed.

## Prices are re-derived, not read back

`cube_count()` re-tiles the regions the option carries and fails if the result disagrees
with the price. A pricing bug and a tiling bug cannot then agree by accident, which is the
failure mode where every number downstream still looks plausible.

## What it got wrong, on the way

Written against the real mod rather than a fixture, which is what the E2E is for:

| | symptom |
| --- | --- |
| rules kept the index, dropped the policy | all 381 blocks `undecided` — a silent all-default |
| multipart short-circuited before measurement | 114 blocks refused: every wall, fence and pane |
| `caps.box_count` is a property | calling it raised; the other way round would have compared a method to an int and matched nothing |

The first two are the kind that pass a unit test. Both were caught by running 381 real
blocks.

## Cost

Pricing is memoised per box set. CMB has 21,880 states and roughly 400 distinct shapes, so
the same geometry was being merged and tile-counted fifty times over; the suite went from
104 seconds to 38 with not one count changing. The cache is unbounded, which is fine for a
batch compiler and would not be for anything long-lived.
