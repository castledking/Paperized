# BoxDecomposer

`src/paperized/decompose.py`.

```
resolved model  ->  BoxDecomposer  ->  IR geometry
```

One question: **what geometry does this resolved model describe?** Visual boxes, no
collision, no carrier, no family, no runtime. Restricting it to that is the point — a
decomposer that also merges or also decides collision cannot be checked against anything.

## What it found

Built against the invariant you specified — decomposer output `==` `geometry.py` measurement,
over every blockstate in both mods, not just fixtures:

```
CMB: agree=267  DISAGREE=0  multipart(refused)=114  no-geometry(refused)=0   inexact=0
FD:  agree= 62  DISAGREE=0  multipart(refused)=  2  no-geometry(refused)=68  inexact=20
```

Zero disagreements, and the run was not clean to get there. Four bugs, every one silent:

**1. `rotation` was ignored entirely.** FD has 35 elements rotated ±22.5° or ±45°. Reading
`from`/`to` and stopping reports the *unrotated* box — a different shape under the right
name. No error anywhere.

**2. 68 canvas signs were fabricated as full cubes.** `farmersdelight:block/canvas_sign`
has textures and nothing else: no elements, no parent. The old path classified that as
`INHERITS` and mapped `INHERITS` to a full cube. Every one of FD's 68 signs — wall, hanging,
wall-hanging — reported as a solid block.

This corrects a number quoted earlier in this project. **"92 of 132 FD blocks are one
geometry" was 24 real cubes plus 68 fabrications.** The honest breakdown is 24 full cubes,
38 partial, 68 with no model geometry at all, 2 multipart. The no-taxonomy conclusion
survives — arguably better, since "no geometry here" is a third category neither
"one geometry" nor "bespoke" covered.

**3. Multipart was truncated to part zero.** A wall is 9 parts; measuring the post and
returning it reports a post *as* a wall. Valid-looking single box, no complaint. Same lie as
the canvas signs, so it now refuses too — 114 CMB blocks and 2 FD.

**4. `rescale: true` was missed.** Vanilla rotates about the element's *own centre* when
`rescale` is set, not the declared origin. Honouring the origin literally displaces the box
whenever they differ, which is the normal case.

## Rotated geometry is not projected into boxes

The first implementation took the axis-aligned bounding box of rotated corners. That is
wrong in a way rounding is not: `cabbages` is two thin planes crossed at 45°, and both
project to the *same* 10×16×10 bounds. Reporting that describes a nearly solid block where
the truth is two flat sheets, and it destroys the distinction between two shapes.

So `ir.OrientedBox` exists and stores eight corners. Right-angle rotations stay in `boxes`
because they genuinely are axis-aligned; anything else goes to `oriented` and sets
`exact=False`.

```
cabbages: axis-aligned boxes=0  oriented=2  exact=False
```

A caller that needs axis-aligned bounds takes `.bounds` explicitly, in a later stage, where
being lossy is visible.

## Merging is not decomposition

Boxes are sorted for determinism and never de-duplicated or merged. Two authored elements
that share one bounds are two elements; collapsing them turns "two shapes that happen to
coincide" into "one shape", unrecoverable later. `BoxMerger` gets to be wrong in one visible
place.

## Failure is loud

Unresolvable chain, bare model that is not `minecraft:block/cube`, multipart, parent cycle,
non-numeric coordinate — all raise `GeometryError`. None returns an empty `Geometry`, because
empty is indistinguishable downstream from a real shape, and "these blocks have no geometry"
surfacing three stages later is what the whole arrangement exists to prevent.

The one exception is a real format fact: `minecraft:block/cube` has neither elements nor
parent and *is* the full cube every vanilla cube resolves to.

## Merged into the reference path

`analysis/geometry.py` no longer does its own element→box conversion; it delegates here.

A second independent implementation is only useful while both are correct. It wasn't — it
was the one ignoring rotations — so keeping it would have meant two bugs on the next format
change and no earlier warning than a test someone had to think to write. The cross-check
did its job while both existed; the fixtures now guard the result.

## Boundary test

`test_decomposer_knows_nothing_about_families_carriers_or_runtime` parses the module's AST
and fails on `craftengine`, `shulker`, `carrier`, `slab`, `pillar`, `pane`, `fence` as
identifiers or non-docstring literals. Scanning raw text would fail on the docstring that
disclaims them; this inspects logic only.

## Next

`Geometry -> BoxMerger -> region set`. Done; see [`merge.md`](merge.md).
