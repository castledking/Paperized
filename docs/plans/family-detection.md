# Plan — shape families without CMB's vocabulary

## The problem

The upstream generator's allocator is general in its mechanics and specific in its
vocabulary. `tools/vanilla_carriers.py` is 952 lines, and a large part of it is a list of
block ids per family:

```python
"stairs": ShapeFamily(
    blocks=("oak_stairs", "spruce_stairs", ..., "waxed_oxidized_cut_copper_stairs"),
    all_properties=(("facing", ...), ("half", ...), ("shape", ...), ("waterlogged", ...)),
    ...
)
```

That list is CMB-specific only in that someone enumerated it. The *properties* are the real
knowledge: a stair is `facing x half x shape x waterlogged`, 448 states, and only the dry
straight ones are lendable.

So there are two separable things:

1. **Family detection** — "this block is a stair, and here is its state space".
2. **Family semantics** — "these properties are the physical geometry, so the carrier must
   match them exactly".

(2) is mod-independent. (1) is the part that needs generalising.

## Options

### A. Declare families in a config file

```yaml
families:
  stairs:
    match: "*_stairs"
    properties: [facing, half, shape, waterlogged]
    model: [facing, half, shape]
    prefer: {waterlogged: false}
```

**Pro:** mod authors describe their own content; no code change per mod. The vocabulary
becomes data.

**Con:** the interesting decisions (`required_carrier_properties`, `value_aliases`,
`merge_safe`, `states_per_custom_block`) are *functions* of the family, not fields. A wall
aliases `true → low`; a plate reserves one state per block. Expressing those in YAML means
either a plugin/expression language or flattening them into fields.

### B. Derive families from vanilla itself

Detect a stair by comparing the block's state space against vanilla's `*_stairs`.

**Pro:** nothing to maintain, works for any mod, and the properties are guaranteed to be
the real ones.

**Con:** matching is heuristic. A mod block named `foo_stairs` with 12 states is not
vanilla-shaped, and vanilla's own families are not the only valid ones — CMB's walls alias
sides and CMB's fences have their own state layout.

### C. Hybrid — detect, then declare overrides

Infer the family from vanilla's shape, then let a config file override or declare anything
the inference gets wrong or that is genuinely novel.

**Pro:** covers the common case with no configuration, and does not block the unusual case.
The config stays small because it is only consulted when it disagrees.

**Con:** the inference still needs a confidence rule, and "it inferred wrong and nobody
noticed" is the failure mode to design against.

## Recommendation

**C**, with the override file always available. Bias the inference toward *not* inferring:
an unrecognised block becomes its own single-block family, which is safe (one carrier, no
shape assumptions) and reports itself as unclassified so the author can declare it
properly.

That matters because the safe default and the useful default disagree here. Guessing a
shape family wrong is how you ship a block with a corner hitbox. Guessing "unknown" costs
one block of capacity.

## Open questions

- Does a family ever need to span more than one vanilla block? (CMB's pillars share the
  cube pool with cubes but are not cubes.)
- How much of `required_carrier_properties` can be inferred as "properties the model
  actually varies"? That may cover most cases and retire the explicit list.
- Should an unclassified block be a build **failure** in strict mode, matching
  `compatibility.unsupported-content: fail`?