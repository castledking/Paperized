# Clustering — how many geometry families actually exist?

Measured across Farmer's Delight (132 blocks) with CMB (296 blocks) as the second subject.
This settles the question `family-detection.md` left open: is the family set small enough
to enumerate, or does the IR need a different primitive?

## Three granularities, compared

| granularity | distinct values | verdict |
|---|---|---|
| property spaces | 17 | too coarse — CMB's wall/fence/pane collide |
| raw box fingerprints | 23 | too fine — every bespoke block is its own cluster |
| **capability signatures** | **22** | see below |

## The long tail is real, and that is the finding

Coverage by capability signature:

```
 92 / 132   single full-height box      (the cube family: cabinets, crates, signs)
 12 / 132   two boxes, full height      (cross-shaped crops)
  5 / 132   one box, 2 tall
  3 / 132   two boxes, 14 tall
 ...        then a tail of 17 singletons, each 1 block
```

**92 blocks are one geometry. The other 40 are 21 distinct geometries.**

So the shape is a **power law, not a taxonomy**. Two consequences, and they pull in
opposite directions:

1. A fixed family list would need ~22 entries for FD alone, and every entry after the
   first two covers exactly one block. That is not a taxonomy, it is a lookup table
   wearing one.
2. The long tail is *bespoke geometry* — `apple_pie`, `cooking_pot`, `skillet`. These
   genuinely have no shared shape, and no amount of inference will find a family for
   them because there isn't one.

## What this means for the IR

The user's framing was right and the measurement confirms it: **family must not be the
primitive.** A block should be described by what it *is*:

```
collision:
  boxes: [...]           # measured, normalized, the real primitive
properties: {...}
visual: {...}
capabilities:
  full_height: true
  thin: false
  grounded: true
  box_count: 2
```

`wall`, `fence`, `pane` then become **recognised profiles** — a collision shape plus a
connection rule — looked up against those boxes. Not the thing the whole compiler
depends on.

**Evidence for this from CMB's own generator:** `vanilla_carriers.py` gives wall, fence
and pane *identical* `used_properties` (`east/north/south/west`, all boolean). Nothing in
the declared state space separates them. What separates them is the per-family carrier
spec and the geometry, which is precisely the profile idea.

## Abstraction: profile, not family

```
  92 blocks → profile "single full box"      → 1 carrier rule, no special case
  12 blocks → profile "cross-shaped, 2 boxes" → 1 profile
  40 blocks → 21 bespoke profiles             → each its own geometry, no inference
```

Three outcomes, and the tail is not a failure of the system:

- **profile matched** — a known profile covers it.
- **novel profile** — geometry measured, no profile matches. Emit the boxes as-is.
  **This is the graceful path, and it is cheap**, because the IR already carries boxes.
- **ambiguous** — several profiles match; declaration decides.

That third bucket is where the earlier "unclassified" idea belongs, and note that in
practice it is small: the tail resolves to "novel profile" rather than "cannot tell",
because a box list is unambiguous even when no family fits it.

## Cost this implies

Decomposing an arbitrary box list into runtime hitboxes is the hard part, and it is
**already solved** in CMB — walls are three shulkers, fences two, vertical slabs four
tiled. But those were hand-authored per family, from measurements. Generalising it means:

```
box list → merge into ≤N axis-aligned regions → tile with scaled shulker hitboxes
```

That is a real piece of work with a real failure mode (boxes that do not merge cleanly),
and it is the next thing to build after the IR. Glass panes are the regression case: they
are proof the decomposition is not secretly a cube-and-stairs special case.

## Open questions

- Does box-merging hit a wall on geometry that does not decompose into axis-aligned
  regions? FD's `rope_fence` and `cooking_pot` are the candidates.
- CMB's geometry has never been measured — `content.json` carries families, not boxes.
  The clustering is FD-only so far, so "12 clusters → 8 families → 6 runtimes" is
  **measured for FD and assumed for CMB**. That assumption should be tested before the
  IR hard-codes anything.
