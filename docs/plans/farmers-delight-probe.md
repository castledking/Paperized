# Farmer's Delight — provability probe

Measured against `/mnt/storage/devops/FarmersDelight`, to answer one question before
building anything: **is the second mod the same problem as the first?**

## The census

Measured by walking every blockstate's model parent chain, through both of FD's asset
roots, into Mojang's 26.3 client jar. Not read off names.

| | |
|---|---|
| blockstates | 132 |
| total variants to place | 537 |
| multipart — never a safe carrier | 2 (`rope`, `rope_fence`) |
| geometry resolved | 132 / 132 |

| geometry | count | e.g. |
|---|---|---|
| `inherits` (vanilla parent, cube-shaped) | 68 | the canvas signs |
| `partial` (real non-cube geometry) | 40 | `apple_pie`, `cabbages`, `cooking_pot` |
| `full_cube` (measured 0..16) | 24 | cabinets, crates, `cabbage_crate` |

**92 blocks are carrier-eligible** — cube-shaped and not multipart.

For scale, CMB served 296 blocks on 275 states from a pool of ~120 safe cube carriers.

## What this tells us

**The allocator generalises.** Nothing here is CMB-shaped. FD's property spaces are
`facing x open`, `age`, `facing x servings`, `bites x facing`, `axis`, `composting` — none
of which exist in CMB's family table, and all of which are keyed on the *same* principle:
a family is a property space plus the geometry those properties imply.

**The hard part is unchanged and it is the carrier pool, not the parsing.** 92 eligible
blocks against a shared pool that CMB already drains. On a server with both packs, FD
gets whatever CMB left — which is the correct, safe behaviour and exactly what the
ownership discovery exists to compute.

**Furniture carries most of FD, same as CMB.** 40 partial-geometry blocks plus 68 signs
have no cube-shaped carrier available at all. Signs are wall-attached thin plates;
`cabbages` are cross-shaped crops. That is the vertical-slab/wall situation again.

## The existing hand-made port

`/mnt/storage/devops/Farmers-Delight-Paperized-unofficial` — someone's CraftEngine pack,
self-described as an experimental proof of concept.

Worth reading for the outcome, not the method:

- **Zero** stairs, slabs, walls or fences. Confirmed: `configuration/blocks/` contains no
  file matching any of them.
- Every block uses `auto-state: note_block`, which is CraftEngine's *persisted* state
  assignment — not a proven-freed carrier. On a shared server that is a collision waiting
  to happen, and it is precisely the failure `docs/carrier-safety.md` §2 exists to prevent.

So it is a useful existence proof and a useful negative result: it shows what happens when
the carrier analysis is skipped.

## Traps found while measuring this

All four produced silently wrong answers — no error, just blocks reported unplaceable.
Each is now a regression test in `tests/test_shape.py`.

1. **Split asset roots.** FD keeps models in both `src/main/resources` and
   `src/generated/resources`. A generated sign parents to a main-resources model. Search
   one root and all 68 signs resolve to nothing.
2. **`minecraft:block/cube` ≠ `<root>/block/block/cube.json`.** Stripping only the
   namespace leaves the directory, which doubles on lookup.
3. **Variant values can be lists.** `organic_compost` lists the same model four times with
   different `y`. A resolver assuming `variants[key]["model"]` reports it as having no
   model at all.
4. **Property names live in the variant *key*,** not a nested `properties` object. This
   one was mine, in the probe script, and it briefly showed all 132 blocks as
   property-less.

## Next

1. Family inference from measured geometry + property space (`docs/plans/family-detection.md`).
2. Carrier pool for FD's 92 eligible blocks, against the live server.
3. Furniture for the 40 partial + 68 signs.
4. Crop behaviour — Allium's crop system is the reference for this (`/mnt/storage/repos/Allium`).
5. Lore/tooltips: FD items carry lore; Allium's `Lore`/`CustomItem` is the pattern for
   preserving that on a custom item. Worth its own probe — it is an *item* concern, not a
   block one, so it belongs to a different layer than the carrier work above.
