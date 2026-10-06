# Carrier safety

The rules for borrowing a vanilla block state, and why each one exists. This is the part
that took the longest to get right and the part most worth not rediscovering.

Every rule here was established by reading CraftEngine's source, Mojang's block report,
and by measuring against a live server. Where something is a judgement call rather than a
proof, it says so.

---

## 1. What a carrier is

CraftEngine binds a custom block's model to a vanilla block state:

```yaml
appearances:
  my_block:
    state: "minecraft:note_block[instrument=banjo,note=1,powered=true]"
```

That `state` is the carrier. It supplies:

- the **model** the client draws,
- the **collision box** the client uses,
- the **sounds and light** the client assumes.

Two custom block states may not share a carrier unless they share a model.
`AbstractBlockManager.arrangeModelForStateAndVerify` enforces it at config-load.

So carriers are a **single-bind, finite resource**, and that is the whole constraint.

---

## 2. The progression

A state is lendable only if it passes every stage:

```
exists → unique → freed by a mapping → lendable → collision-safe → available → assigned
```

Each arrow is a distinct failure someone will otherwise ship.

### exists

The block and state must exist on the *target* server, not the version the mod shipped
against. Availability is a runtime question — intersect with the live registry. Never
delete content at build time because a version lacks it.

### unique

Every state parses to a canonical identity. Checked against Mojang's own block report
(`minecraft --reports`), not a regex.

> A trap: the client blockstate file **deduplicates waterlogging** and under-reports
> state counts. `glass_pane` has 32 registry states, not the 16 its blockstate suggests.
> The authoritative count is the block report.

### freed by a mapping

```
lendable  <=>  the state is a mapping key  AND  never a mapping target
```

A `block_state_mappings` entry `A: B` tells every client to draw vanilla state A as state
B. So real blocks in state A never *look* like A, which is what makes A safe to borrow.

A **target** is excluded even if it is also a key: every block mapped onto it is drawn as
it, so binding a model there would change how those real blocks look.

> The earlier fix — "convert the borrowed vanilla block into a CraftEngine block" — only
> ever protected one default state, because players place the real vanilla block. It does
> not work.

### collision-safe

A carrier must not merely be *valid*, it must have the right **geometry**. A stair carried
by `shape=inner_right` is a real vanilla state with a corner hitbox, so a straight stair
carried by it silently gets the wrong collision.

This is why capacity is **per shape family**, not global: a stair needs a stair-shaped
carrier.

### available

Not already claimed by another pack on the same server, and not consumed by an earlier
allocation in this run.

> **Over-claim rather than under-claim.** A false positive costs capacity. A false negative
> puts two blocks on one state, which is a broken pack. Anything unresolvable is claimed
> conservatively and reported.

### assigned

Handed out deterministically, so a rebuild produces the same mapping.

---

## 3. Multipart carriers are forbidden

This is the rule that rejected the largest family.

When CraftEngine writes into a blockstate it removes `multipart` and merges its own entries
into `variants` (`AbstractPackManager.generateBlockOverrides`). For a variants-only
blockstate that is harmless. For a **multipart** one it is destructive:

```
vanilla blockstate      multipart block, renders 7776 states
CraftEngine override    strips multipart, writes only our variants
unconverted state       no model at all -> magenta in game
```

So a carrier is eligible only if modifying its blockstate **cannot destroy unrelated
vanilla rendering** — a property of the *shape* of the vanilla blockstate, not something
to patch per family.

Check it against **vanilla's own definition**, never against our generated output.
Checking against our own output validates the damage against itself, and that version
passed while three unsafe families were live.

> In the upstream project this cost walls: 24 candidate blocks carrying 7,776 vanilla
> states, and 75 blocks depending on them. Not a trade worth making knowingly.

---

## 4. Furniture, and its limits

When no safe carrier exists, the answer is CraftEngine **furniture** rather than borrowing.

A furniture piece is a display entity for the model and a **hitbox** for collision. It
consumes **no vanilla state and no internal state**, so it is not bound by the carrier
budget at all.

Its hitbox system is where the interesting part lives. The **shulker hitbox** is scaled via
the generic scale attribute, which means:

- a single shulker is a **cube** — there is no per-axis control;
- `scale` is applied as `AttributesProxy.SCALE`, not as a box dimension;
- tiling several shulkers is how a non-cubic shape is expressed.

And the shulker entity itself is **invisible, AI-less and client-side only** — spawned
purely via packets, never added to the world server-side. The collision is a separate
server-side AABB. So furniture is cheap and invisible, but it is not a block:

- no redstone or neighbour updates,
- no block-form UI, so mining needs several hits,
- each piece is an entity.

Walls, fences, horizontal stairs and vertical slabs all ship this way in the upstream
project. See `docs/plans/` for the working recipes.

---

## 5. Versioned reference data

For 26.x and later, reference data comes from **Mojang's own client jar** via the version
manifest. For 1.x, from the community asset mirror. The community mirror only tracks 1.x.

> The upstream project lost real time to this: the mod targets 1.21.1, the port targets
> 26.3, and the gap is not a version bump — the schemas changed.

Two schema changes that break silent assumptions:

- **Textures can be objects**: `{"sprite": "...", "force_translucent": true}` rather than
  plain strings. A resolver assuming strings drops every reference and reports nothing.
- **State counts disagree** between the client blockstate file and the real registry, as
  with `glass_pane` above.

---

## 6. The budget

Every declared state combination becomes a real entry in the vanilla block registry, so
declared states are the pack's memory **and** startup cost. The ceiling must be at or
below CraftEngine's own `block.serverside-blocks`.

Two things make this cost more than the naive estimate:

1. Every vanilla block borrowed as a carrier is itself converted into a CraftEngine block.
2. Reserved states — those a converted carrier keeps to render as itself — are metadata,
   and deliberately sit **outside** the assigned/available denominators. Conflating them
   makes a family look far more constrained than it is.

Print used / limit / remaining on every build so headroom is visible rather than implied.

---

## 7. Validation is a gate, not a report

Every rule above is checked **before anything is written**, and the build fails rather
than emitting a pack that is subtly wrong:

- every lent state is freed and is not a mapping target;
- multipart eligibility;
- state identity, against Mojang's report;
- every model reference resolves, transitively, with parents and textures;
- every emitted file parses back to exactly what was intended;
- no generated config references a deferred block;
- builds are deterministic — byte-identical across runs.

A generator that warns is a generator whose warnings get ignored.