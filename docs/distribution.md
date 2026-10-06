# Distribution

Where each layer is published, and why. The short version: **the toolkit is a developer
tool, not a server plugin**, and picking the wrong listing type hides it from the people
who would use it.

---

## Modrinth project types and loaders

Two independent axes, and conflating them produces wrong answers.

**Project types** — `GET /v2/tag/project_type`:

```
mod  modpack  resourcepack  shader  plugin  datapack  minecraft_java_server
```

**Loaders** — `GET /v2/tag/loader` — 29 of them, each declaring which project types it
attaches to:

```
java-agent   ['mod']
paper        ['plugin', 'mod']
bukkit       ['plugin', 'mod']
datapack     ['datapack', 'mod']
fabric       ['mod', 'modpack']
```

**`java-agent` is a loader, not a project type.** It exists, it is supported, and it
supports `mod` only — so a java agent is published as a **`mod`** carrying the
`java-agent` loader. Plugin ASM is exactly that, and is correctly categorised.

This matters for the runtime layer: `paperized analyze --agent minecraft` would be a `mod`
project with the `java-agent` loader, discoverable alongside Plugin ASM. No new category
would be needed.

> Worth remembering when reading the API: asking `/tag/project_type` cannot tell you
> whether a runtime-instrumentation distribution model is supported. It is not a type.

## What goes where

| artefact | listing | rationale |
|---|---|---|
| **CMB Paperized** | `plugin`, loader `paper` | What it is: a Paper plugin. Server admins browsing plugins find it here. |
| `paperized convert` (CLI) | **GitHub only** | A build tool for mod authors. Modrinth's plugin search is not where they look, and filing it as `plugin` misrepresents what it is. |
| `paperized-core` / `-paper` | **Maven** | Libraries are consumed as dependencies, not downloaded from a content platform. |
| `paperized analyze --agent` (later) | `mod`, loader `java-agent` | The one place instrumentation fits, and where Plugin ASM already sits. |
| generated CraftEngine pack | not published | It is build output, specific to a target server's other packs. |

## Why the CLI is not a Modrinth project

The audience for `paperized convert` is mod and pack authors. They arrive via GitHub, the
CraftEngine Discord and other projects, not via Modrinth's plugin search. A listing there
would add a maintenance surface — version tracking, changelogs, moderation — in exchange
for very little reach.

The runtime layer is a different question, because it *is* something a server admin installs.
`java-agent` being a real, supported loader means there is a natural home for it later
(`mod` + loader `java-agent`, next to Plugin ASM). That is worth revisiting only once the
runtime layer exists — a static converter has no business being attached to a JVM.

## Precedent

Worth knowing that this space already exists and is not uncontested:

- **Farmer's Delight Paperized** — an unofficial CraftEngine port targeting vanilla
  clients. Published, and filed as `mod` rather than `plugin`, which is a small
  misrepresentation in the same direction.
- **Plugin ASM** — a java agent for runtime bytecode injection, published on Modrinth.

Neither is a competitor to the toolkit: both are single ports or single-purpose tools.
The gap being filled is the reusable conversion layer underneath them.

---

## Distribution checklist, per layer

- **core / generator** — Maven coordinates, `sources` and `javadoc` jars published. Semantic
  versioning, and a `CHANGELOG.md` kept by hand rather than generated from commits, because
  the compatibility promise is the whole point of a library.
- **paper** — Maven for compile-time, Modrinth `plugin` for server admins. These are
  different consumers with different expectations and both are worth serving.
- **cli** — GitHub releases with platform-appropriate artifacts. Java would mean
  `java -jar paperized.jar`; if it stays Python, a published `pyz` or a `pipx`-installable
  package.

## One caution on naming

Paperized and CMB Paperized are different things and the overlap is a real risk:

- **Cinch's Missing Blocks Paperized** — the port.
- **Paperized** — the toolkit that makes this kind of port possible.

Say which one you mean in release notes and commit messages. The day there is a
`paperized-core` on Maven and a `paperized` command on PATH, "upgrade Paperized" is
genuinely ambiguous.