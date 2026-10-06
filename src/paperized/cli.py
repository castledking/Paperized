"""``paperized`` on the command line.

What exists today is measurement: walk a mod's blockstates, resolve each one's model chain,
and report what the geometry actually is. That is the census the rest of the compiler is
built on, and it is useful on its own -- it is how Farmer's Delight's 132 blocks were found
to be 68 canvas signs with no model geometry at all, reported as full cubes.

    paperized measure /path/to/mod
    paperized measure /path/to/mod --json

The generator that turns measurement into a pack is not here yet. It lives with the port it
was written for, and moving it is a later step; this command deliberately stops at
measurement rather than pretending to be the whole compiler.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

from .analysis.geometry import measure_blockstate
from .analysis.shape import first_model
from .decompose import GeometryError
from .ir import derive

ASSET_SUFFIXES = ("src/main/resources/assets", "src/generated/resources/assets")


def asset_roots(mod: pathlib.Path) -> list[pathlib.Path]:
    """Every namespace directory whose assets the compile should read.

    Two layouts, both real and both needed:

    * a mod checkout -- ``src/{main,generated}/resources/assets/<namespace>``
    * a built resource pack -- ``assets/<namespace>`` directly, which is what a server
      actually has after the generator ran, and the only way to compile a pack that was
      produced elsewhere

    Both source sets, because a model in one routinely parents to a model in the other:
    Farmer's Delight's generated canvas signs all parent to a template in ``main/resources``.
    """
    roots: list[pathlib.Path] = []
    for suffix in ASSET_SUFFIXES:
        base = mod / suffix
        if base.is_dir():
            roots.extend(sorted(p for p in base.iterdir() if p.is_dir()))
    if roots:
        return roots
    if not mod.is_dir():
        return []
    # The path is itself one namespace, which is what pointing at .../assets/cinchsmissingblocks
    # means. Returning nothing here is what made `compile` refuse a perfectly good pack.
    if (mod / "blockstates").is_dir():
        return [mod]
    # Otherwise an assets directory: a namespace is any child holding blockstates.
    return sorted(p for p in mod.iterdir() if p.is_dir() and (p / "blockstates").is_dir())


def census(mod: pathlib.Path, vanilla_models: pathlib.Path | None) -> dict:
    """Measure every blockstate under ``mod`` and summarise.

    Refusals are counted by reason rather than lumped together. "68 blocks have no model
    geometry" and "3 blockstates were unreadable" are different findings, and a single
    failure count hides which one happened.
    """
    roots = asset_roots(mod)
    if not roots:
        raise SystemExit(
            f"no assets found under {mod} (looked for {' and '.join(ASSET_SUFFIXES)})"
        )

    total = resolved = 0
    shapes: collections.Counter[str] = collections.Counter()
    refusals: collections.Counter[str] = collections.Counter()
    cubes = thin = 0
    inexact = 0

    for root in roots:
        states = root / "blockstates"
        if not states.is_dir():
            continue
        for path in sorted(states.glob("*.json")):
            total += 1
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                refusals[f"unreadable blockstate ({type(exc).__name__})"] += 1
                continue
            if "multipart" in document:
                refusals["multipart: composed of parts, not one model"] += 1
                continue
            try:
                geometry, _properties, _multipart = measure_blockstate(
                    path.stem, document, roots, vanilla_models
                )
            except GeometryError as exc:
                refusals[_reason(exc)] += 1
                continue
            resolved += 1
            shapes[_shape_name(geometry)] += 1
            caps = derive(geometry)
            cubes += caps.full_cube
            thin += caps.thin_axis is not None
            inexact += not geometry.exact

    return {
        "mod": str(mod),
        "assets": [p.name for p in roots],
        "blockstates": total,
        "measured": resolved,
        "full_cubes": cubes,
        "thin_on_one_axis": thin,
        "not_exact": inexact,
        "shapes": dict(sorted(shapes.items())),
        "refused": dict(sorted(refusals.items())),
    }


def _reason(exc: GeometryError) -> str:
    """Group refusals by cause, not by message.

    The chain is in the message and differs per block, so grouping on the whole string
    would report 68 distinct reasons for one cause.
    """
    text = str(exc)
    if "not found" in text:
        return "model chain broken: a model in the chain is missing"
    if "not minecraft:block/cube" in text:
        return "defines no geometry (textures only, no elements and no parent)"
    if "multipart" in text:
        return "multipart: composed of parts, not one model"
    if "exceeded" in text:
        return "parent chain too deep, or cyclic"
    if "from" in text or "coordinate" in text:
        return "malformed element coordinates"
    return "unresolved"


def _shape_name(geometry) -> str:
    if not geometry.boxes and not geometry.oriented:
        return "empty"
    if geometry.oriented and not geometry.boxes:
        return "rotated only (no axis-aligned box)"
    if len(geometry.boxes) == 1 and geometry.boxes[0].as_tuple() == (0, 0, 0, 16, 16, 16):
        return "single full cube"
    return f"{len(geometry.boxes)} box(es)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="paperized", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    measure = sub.add_parser("measure", help="measure a mod's block geometry")
    measure.add_argument("mod", type=pathlib.Path, help="the mod's root directory")
    measure.add_argument(
        "--vanilla-models",
        type=pathlib.Path,
        default=None,
        help="a vanilla models/ root, for model chains that parent into vanilla",
    )
    measure.add_argument("--json", action="store_true", help="machine-readable output")

    build = sub.add_parser("compile", help="compile a mod's blocks to cubes, per a policy table")
    build.add_argument("mod", type=pathlib.Path, help="the mod's root directory")
    build.add_argument(
        "--policy",
        type=pathlib.Path,
        required=True,
        help="the caller's collision policy table (see examples/cmb-policy.json)",
    )
    build.add_argument("--vanilla-models", type=pathlib.Path, default=None)
    build.add_argument("--min-side", type=int, default=1, help="smallest placeable cube")
    build.add_argument("--max-side", type=int, default=256, help="largest placeable cube")
    build.add_argument("--json", action="store_true")

    pack = sub.add_parser("package", help="write a compiled artifact a backend can read")
    pack.add_argument("mod", type=pathlib.Path)
    pack.add_argument("--policy", type=pathlib.Path, required=True)
    pack.add_argument("--out", type=pathlib.Path, required=True)
    pack.add_argument("--vanilla-models", type=pathlib.Path, default=None)
    pack.add_argument("--min-side", type=int, default=1)
    pack.add_argument("--max-side", type=int, default=256)
    pack.add_argument("--assets", action="store_true", help="copy the asset tree alongside")
    pack.add_argument("--no-assets", dest="assets", action="store_false")
    pack.set_defaults(assets=True)

    args = parser.parse_args(argv)
    if args.command == "package":
        return _package(args)
    if args.command == "compile":
        return _compile(args)
    if args.command == "measure":
        report = census(args.mod, args.vanilla_models)
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            _print_report(report)
        return 0
    parser.error(f"unknown command {args.command}")
    return 2


def _compile(args) -> int:
    """The whole chain, and the table a server owner argues with."""
    from .compile import CompileError, PolicyTable, compile_mod, report
    from .tile import CubeLimits

    roots = asset_roots(args.mod)
    if not roots:
        raise SystemExit(f"no assets found under {args.mod}")
    states_dirs = [r / "blockstates" for r in roots if (r / "blockstates").is_dir()]
    if not states_dirs:
        raise SystemExit(f"no blockstates under {args.mod}")

    table = PolicyTable.load(args.policy)
    limits = CubeLimits(args.min_side, args.max_side)
    plans = []
    for states_dir in states_dirs:
        plans.extend(compile_mod(states_dir, roots, args.vanilla_models, table, limits))

    if args.json:
        print(json.dumps([
            {
                "block": p.id,
                "policy": p.policy.value if p.policy else None,
                "matched": p.matched,
                "note": p.note,
                **p.totals(),
            }
            for p in plans
        ], indent=2))
    else:
        print(report(plans, ", ".join(r.name for r in roots)))
    return 0


def _package(args) -> int:
    """Compile, then write the package. The artifact is the contract, not this API."""
    from .artifact import write_package
    from .compile import PolicyTable, compile_mod
    from .tile import CubeLimits

    roots = asset_roots(args.mod)
    if not roots:
        raise SystemExit(f"no assets found under {args.mod}")
    states_dirs = [r / "blockstates" for r in roots if (r / "blockstates").is_dir()]
    if not states_dirs:
        raise SystemExit(f"no blockstates under {args.mod}")

    table = PolicyTable.load(args.policy)
    limits = CubeLimits(args.min_side, args.max_side)
    plans = []
    for states_dir in states_dirs:
        # materialise: a package carries cubes, not a count of them.
        plans.extend(compile_mod(states_dir, roots, args.vanilla_models, table, limits,
                                 materialise_cubes=True))

    namespace = roots[0].name
    written = write_package(args.out, plans, namespace,
                            asset_dirs=roots if args.assets else None)
    summary = written["manifest"]["summary"]
    print(f"{args.out}/manifest.json      format={written['manifest']['format']} "
          f"version={written['manifest']['version']}")
    print(f"{args.out}/definitions.json  {summary['blocks']} blocks, {summary['states']} states")
    for status, n in summary["statuses"].items():
        print(f"  {status:14} {n}")
    print(f"assets copied  {written['asset_files']} files")
    return 0


def _print_report(report: dict) -> None:
    print(f"{report['mod']}")
    print(f"  assets          {', '.join(report['assets'])}")
    print(f"  blockstates     {report['blockstates']}")
    print(f"  measured        {report['measured']}")
    print(f"  full cubes      {report['full_cubes']}")
    print(f"  thin on an axis {report['thin_on_one_axis']}")
    if report["not_exact"]:
        print(f"  not exact       {report['not_exact']}  (rotated off-axis, or fractional)")
    if report["shapes"]:
        print("  geometry:")
        width = max(len(k) for k in report["shapes"])
        for shape, n in report["shapes"].items():
            print(f"    {shape.ljust(width)}  {n}")
    if report["refused"]:
        print("  refused, by reason:")
        width = max(len(k) for k in report["refused"])
        for reason, n in report["refused"].items():
            print(f"    {reason.ljust(width)}  {n}")


if __name__ == "__main__":
    sys.exit(main())
