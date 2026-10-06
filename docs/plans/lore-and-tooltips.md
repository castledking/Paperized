# Lore and tooltips — the item-layer probe

Measured against Farmer's Delight and `/mnt/storage/repos/Allium`, to answer: **is item
lore a porting problem, and does Allium's pattern transfer?**

## What FD actually has

36 lang keys contain "tooltip". Only **11 are item lore**. The other 25 are
`farmersdelight.configuration.*` — GUI help text for FD's own config screen, which never
becomes an item tooltip at all.

| kind | keys | example |
|---|---|---|
| container state | 3 | `tooltip.farmersdelight.cooking_pot.empty` = `Empty` |
| consumable effect | 5 | `tooltip.farmersdelight.milk_bottle` = `Clears 1 Effect` |
| placement | 2 | `tooltip.farmersdelight.placeable` = `Placeable` |
| debug | 1 | `tooltip.farmersdelight.debug_item` |

Plus **zero** keys ending in `.lore`. FD has no lore *strings* in its lang file at all —
which is the single most useful finding here.

## Why that matters: FD's lore is behaviour, not data

None of FD's 11 keys is static text attached to an item. Every one is computed at render
time by `appendHoverText`:

```java
// ConsumableItem.java:90
public void appendHoverText(ItemStack stack, TooltipContext context,
                            List<Component> tooltip, TooltipFlag isAdvanced) {
    if (Configuration.ENABLE_FOOD_EFFECT_TOOLTIP.get()) {
        if (this.hasCustomTooltip) {
            tooltip.add(TextUtils.tooltip(...).withStyle(ChatFormatting.BLUE));
        }
        if (this.hasFoodEffectTooltip) {
            TextUtils.addFoodEffectTooltip(stack, tooltip::add, 1.0F, context.tickRate());
        }
    }
}
```

Three separate problems in there:

1. **It is a client-side hook.** `appendHoverText` never runs on a server, so no amount of
   lang-file copying reproduces it.
2. **It is conditional on config.** `ENABLE_FOOD_EFFECT_TOOLTIP` gates the whole thing.
3. **The food-effect line is derived from the item's actual food component**, including
   `context.tickRate()` — a runtime value. A static string cannot express "Minor Instant
   Health" *and* stay correct when the food component changes.

Eight FD source files touch tooltips. Six are `appendHoverText` overrides; the other two
are a GUI tooltip class and an event hook.

## What this means for a port

**Lore is a runtime concern, and belongs in the `paper` layer, not the generator.**

| layer | what it owns for lore |
|---|---|
| `generator` | copies the lang keys, so names and any static text survive |
| `paper` | reproduces the *conditional* parts — per-item hooks driven by config |

Attempting this in the generator would produce a pack whose items show a plausible but
wrong tooltip: present when it should be hidden, absent when the server owner enabled it,
and stale the moment a food component is rebalanced.

This is the same shape as the behaviour decision already made for blocks
(`docs/carrier-safety.md` §4): furniture is not blocks, and runtime-derived lore is not
static lore.

## Allium's pattern

Allium's `CardLore.render(card, xp)` is the reference for the `paper` side:

- takes runtime state (`xp`) rather than reading a string,
- returns `List<String>`, so it drops straight into `ItemMeta#setLore`,
- **resets italic per line** — the pack's font ships italic glyphs only, so an unstyled
  line inherits the italic and the whole item reads slanted.

That last point is the trap worth carrying across. It is invisible until a real client
renders it, and it applies to any custom item with a resource pack, not just Allium's
cards.

## Recommendation

1. `generator`: emit the tooltip lang keys verbatim. Cheap, lossless, and the keys are
   inert until something renders them.
2. `paper`: a `TooltipProvider` interface a consuming plugin implements per item.
   Paperized ships FD's `ConsumableItem` behaviour as the reference implementation, not
   as a hardcoded special case.
3. **Never** bake a derived tooltip into an item's static lore at build time. If it must
   change with server state, it is runtime.

## Open question

Whether `TooltipProvider` belongs in `paperized-core` or only in the consuming plugin.
Argument for the core: two mods with food-effect tooltips would otherwise duplicate it.
Argument against: it is engine behaviour, and this project has already drawn the line that
behaviour is CraftEngine's and the plugin's job — not ours.
