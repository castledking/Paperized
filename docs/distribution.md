# Distribution

Where each layer is published, and why. The short version: **the toolkit is a developer
tool, not a server plugin**, and picking the wrong listing type hides it from the people
who would use it.

---

## Modrinth project types

Verified against `GET /v2/tag/project_type`:

```
mod  modpack  resourcepack  shader  plugin  datapack  minecraft_java_server
```

There is **no java-agent type**. Projects that are java agents are filed as `mod` — for
example Plugin ASM, which is explicitly distributed as a java agent for runtime bytecode
injection.

That is a category error for Paperized anyway. A java agent is a `-javaagent:` jar attached
to a JVM at startup to instrument classes. Paperized's static conversion reads a mod jar
and writes a pack to disk. There is no JVM and nothing to instrument.

## What goes where

| artefact | listing | rationale |
|---|---|---|
| **CMB Paperized** | `plugin` | What it is: a Paper plugin. Server admins browsing plugins find it here. |
| `paperized convert` (CLI) | **GitHub only** | A build tool for mod authors. Modrinth's plugin search is not where they look, and filing it as `plugin` misrepresents what it is. |
| `paperized-core` / `-paper` | **Maven** | Libraries are consumed as dependencies, not downloaded from a content platform. |
| generated CraftEngine pack | not published | It is build output, specific to a target server's other packs. |

## Why the toolkit is not a Modrinth plugin

The audience is mod and pack authors. They arrive via GitHub, the CraftEngine Discord and
other projects, not via Modrinth's plugin search. A listing there would add a maintenance
surface — version tracking, changelogs, moderation — in exchange for very little reach.

If it becomes worth publishing later, the honest listing is a `plugin` for the **runtime**
layer (the thing that takes a mod jar and generates a pack on a running server), with the
converter documented as what powers it. That is a different product from the CLI, and worth
revisiting only once the runtime layer exists.

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