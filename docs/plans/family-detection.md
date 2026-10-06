# Family detection

Can a family be inferred, or must it be declared? Measured against both mods.

## The plan's proposal

```
properties → state space → geometry → family
```

The question this settles: **is geometry load-bearing, or is the property space enough?**

## Answer: geometry is load-bearing

**Properties alone are not a function of family.** CMB has 7 distinct property spaces,
and one of them — `east, north, south, west` — is **three different families**:

| family | count | example |
|---|---|---|
| wall | 75 | `andesite_brick_wall` |
| fence | 5 | `blue_nether_brick_fence` |
| pane | 1 | `tinted_glass_pane` |

Identical property space, three shapes, three carrier requirements. Nothing in the block's
own state space distinguishes them. So `properties → family` cannot be made to work, and
an inference that tried would be guessing.

FD independently hits the same wall: its `facing` space covers both `full_cube` (1 block)
and `partial` (4 blocks).

**Geometry disambiguates within a property space in almost every case.** FD, measured:

| property space | n | geometry | verdict |
|---|---|---|---|
| *(none)* | 85 | inherits 68, full_cube 8, partial 9 | ambiguous |
| `facing, open` | 11 | full_cube 11 | clean |
| `age` | 7 | partial 7 | clean |
| `facing, servings` | 6 | partial 6 | clean |
| `facing` | 5 | partial 4, full_cube 1 | ambiguous |
| `bites, facing` | 4 | partial 4 | clean |

11 of 12 spaces are clean. The two that are not are the two where the answer genuinely
depends on something other than the property space and the geometry — 85 property-less
blocks, and a 5-block `facing` group split 4/1.

## So the inference is: properties ∪ geometry, and it may abstain

```
family = infer(properties, geometry)
       → confident | ambiguous | unclassified
```

Three outcomes, not two. **Abstaining is a first-class result**, not a failure:

- **confident** — proceed.
- **ambiguous** — more than one candidate family fits. Report every candidate with its
  evidence and let the declaration file choose. Do not pick the most common.
- **unclassified** — no candidate fits. Becomes its own single-block family, which is
  always safe (one carrier, no shape assumptions), and reports itself so the author can
  declare it.

That bias is deliberate. Guessing a shape family wrong ships a block with a corner hitbox;
guessing "unknown" costs one block of capacity. The two errors are not comparable in cost.

## The declaration file stays

Only consulted when inference abstains — so it stays small, and there is no configuration
for the common case.

```yaml
# optional, per mod
families:
  # CMB's wall/fence/pane share a property space; geometry says which, but a
  # mod may ship a shape the analyzer has never seen.
  glazed_wall:
    match: "*_glazed_wall"
    properties: [east, north, south, west]
    geometry: partial
    # which vanilla family supplies carriers, if not this one
    carriers_from: wall
```

## Why this is not option C from the earlier note

Inference-then-override was considered and is still roughly right, but the measurement
sharpened the confidence rule. It is not "infer, then let config correct it" — a wrong
inference that nobody notices is the failure to design against. So:

- inference **must be able to abstain**, and
- an abstention must be **reported in the manifest**, so it is visible without reading code.

`Manifest.deferrals(Reason)` already has the vocabulary; an abstention is
`UNCLASSIFIED_FAMILY`, and it counts toward the deferred total like any other reason.

## Open questions

- CMB's 7 spaces are hand-authored and 1 is ambiguous. FD has 19 and 2 are. Is the real
  number of *geometric* families small enough to enumerate as a lookup rather than a rule
  set? Worth measuring: cluster all 26 property spaces by measured geometry across both mods.
- Does a family ever span more than one vanilla block? CMB's pillars share the cube pool
  with cubes but are not cubes (`axis`, not no properties).
- Should abstention be a build **failure** in strict mode, matching
  `compatibility.unsupported-content: fail`?
