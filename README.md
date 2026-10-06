<p align="center">
  <img alt="Paperized" width=100% height=auto src="https://castled.codes/assets/paperized-banner.png">
</p>

# <p align="center">Turn a Minecraft mod's blocks into CraftEngine content, safely</p>

**Paperized** converts the block content of a Fabric/NeoForge mod into a
[CraftEngine](https://github.com/Xiao-MoMi/craft-engine) pack, plus a machine-readable
manifest describing what it did and why.

It exists because the naive conversion does not work, and does not fail visibly.

---

## The problem

CraftEngine draws a custom block by binding a model to a **vanilla block state** — the
"carrier". The carrier also supplies the client-side collision box. Two custom blocks may
not share one vanilla state unless they also share one model, and CraftEngine enforces
that at config-load time.

So the number of blocks you can add is bounded by how many vanilla states exist *of a
shape that matches*:

```
(custom blocks in a family) x (states each needs) <= (vanilla states of that shape)
```

The naive approach — take whatever states look convenient — **corrupts your world**. A
real barrel drawn as diorite bricks is the classic symptom. It works fine on an empty
test server and then someone places a barrel.

Two failure modes, both silent:

- **Borrowing a state vanilla can still reach.** Real blocks show your model.
- **Overwriting a multipart blockstate.** CraftEngine strips `multipart` and merges its
  own variants in. Every vanilla state of that block you did *not* allocate is left with
  no model at all, and renders magenta in game.

Paperized refuses both. A block is served only when the carrier is **provably** safe, and
otherwise it is deferred and reported — never dropped silently, never shipped broken.

---

## What it produces

```
out/
├── configuration/        CraftEngine config: blocks, items, recipes, categories, furniture
├── resourcepack/         assets: models, textures, lang
└── manifest.json         what was served, what was deferred, and the reason for each
```

`manifest.json` is the contract. A consuming plugin reads it to know which blocks exist,
what they cost in states, and why anything is missing — without parsing CraftEngine YAML.

---

## Status

**Greenfield.** The conversion logic is proven, but it lives in
[Cinch's Missing Blocks — Paperized](https://github.com/castledking/Cinchs_Missing_Blocks_Paperized),
hardcoded to one mod. This repo is the extraction of the general part.

What is proven, from that upstream work:

| | |
|---|---|
| Carrier allocation across shape families | working, with strict validation |
| Block-state identity checking against Mojang's report | working |
| Multipart eligibility rejection | working — this is what killed the walls |
| Ownership discovery (other packs' claims) | working |
| Mod data translation (loot, tags, recipes) | working |
| Generic mod support | **not started** — the families are CMB's vocabulary |

The hard part was never the code. It was establishing *which states are safe*, and that
answer is now written down in [`docs/carrier-safety.md`](docs/carrier-safety.md) instead
of being rediscovered per project.

---

## Why not just write it in Java

Deliberately not, for now. The upstream generator is ~9,700 lines of Python and is
correct. Rewriting it buys one thing — sharing types with a consuming Paper plugin — and
costs a rewrite plus a JVM build step on every iteration.

The manifest is the seam. It is the contract, so the language either side of it is an
implementation detail. If the plugin ever needs to share internals rather than just the
output, that is the moment to port, and it will be a mechanical move rather than a
redesign.

---

## Documentation

| | |
|---|---|
| [`docs/carrier-safety.md`](docs/carrier-safety.md) | The rules, and why each exists |
| [`docs/plans/`](docs/plans/) | Design notes, in progress |

## Requirements

- Python 3.11+
- A CraftEngine `resources/` directory, read to discover what is already claimed