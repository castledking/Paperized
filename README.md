<p align="center">
  <img alt="Paperized" width=100% height=auto src="https://castled.codes/assets/paperized-banner.png">
</p>

# <p align="center">A toolkit for porting Minecraft mod content to Paper servers, without a client mod</p>

**Paperized** is a development toolkit for turning a Fabric/NeoForge mod's block content
into something a Paper server can serve — a CraftEngine pack, plus a machine-readable
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

## Scope

Given a mod jar, the toolkit produces a Paper-ready implementation:

```
mod.jar  →  configuration/     CraftEngine config: blocks, items, recipes, furniture
            resourcepack/      assets: models, textures, lang
            manifest.json      what was served, what was deferred, and why
```

`manifest.json` is the contract. A consuming plugin reads it to learn which blocks exist,
what they cost in states, and why anything is missing — without parsing CraftEngine YAML.

### In scope

Mod source parsing · asset extraction · vanilla blockstate analysis · carrier analysis and
allocation · CraftEngine pack generation · resource-pack generation · collision and
furniture generation · validation gates

### Out of scope

Block **behaviour** — redstone, water physics, placement rules. Those are engine
concerns, and CraftEngine plus the consuming plugin own them.

---

## Design

The toolkit is layered, so a consumer takes only what it needs:

```
                        paperized
                            │
        ┌───────────────┬───┴───────────┬────────────────┐
        ▼               ▼               ▼                ▼
     core          generator          paper            cli
        │               │               │                │
  mod analysis    CraftEngine      runtime API     mod → Paper
  definitions     config, assets   CE integration  the command
  validation      manifest         furniture       developers run
        │               │               │                │
        └───────────────┴───────────────┴────────────────┘
                            │
                   any Paper plugin, or CMB
```

- **core** — mod parsing and the block/collision/behaviour definitions. No CraftEngine
  dependency, so it is testable without a server.
- **generator** — turns definitions into a pack plus the manifest.
- **paper** — the runtime API a consuming plugin uses.
- **cli** — `paperized convert mymod.jar`. The thing developers actually run.

### On runtime access

A java agent could inspect a *running* modded client for things static analysis cannot
reach: registered blocks, block properties, voxel shapes, item mappings. That is genuinely
more powerful than reading a jar, and it belongs here eventually.

It is not the foundation. Requiring `-javaagent:` to perform a static conversion makes it
harder to explain, harder to secure and harder to maintain, for a capability a static pass
covers. It stays a later phase, and only if a concrete need shows up that static analysis
provably cannot meet.

It does have a natural home when it arrives: Modrinth supports `java-agent` as a loader
(under the `mod` project type), which is where Plugin ASM sits today. See
[`docs/distribution.md`](docs/distribution.md).

---

## Status

**Greenfield, and deliberately incremental.** The conversion logic is proven, but it lives
in [Cinch's Missing Blocks — Paperized](https://github.com/castledking/Cinchs_Missing_Blocks_Paperized),
hardcoded to one mod. This repo is the extraction of the general part.

What is proven upstream:

| | |
|---|---|
| Carrier allocation across shape families | working, strict validation |
| State identity against Mojang's block report | working |
| Multipart eligibility rejection | working — this is what killed the walls |
| Ownership discovery (other packs' claims) | working |
| Mod data translation (loot, tags, recipes) | working |
| Generic mod support | **not started** |

**The rule for this repo: extract abstractions out of working code, never ahead of it.**
Nothing moves here until CMB has proven it on a second mod. A framework written before its
second consumer is a framework written for an imagined one.

---

## Documentation

| | |
|---|---|
| [`docs/carrier-safety.md`](docs/carrier-safety.md) | The rules, and why each exists |
| [`docs/plans/`](docs/plans/) | Design notes, in progress |
| [`docs/distribution.md`](docs/distribution.md) | Where each layer is published, and why |

## Requirements

- Python 3.11+ (a Java port is a considered later step, not a commitment)
- A CraftEngine `resources/` directory, read to discover what is already claimed