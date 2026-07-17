"""cosim: generate and run QEMU<->RTL co-simulations."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .config import Config, ToolchainConfig

_INIT_TEMPLATE = """{{
  "design": {{
    "input": "design.hw.mlir",
    "dts": "board.dts",
    "supported_backends": ["{backend}"]
  }},
  "qemu": {{
    "elfs": ["bootrom.elf", "simram.elf"]
  }},
  "components": [
    {{
      "type": "MyPeripheral",
      "path": "topDesign/topMod/myPeripheral",
      "compat": "sifive,uart0",
      "interfaces": [
        {{ "kind": "clock", "name": "clock", "freq_mhz": 150 }},
        {{ "kind": "reset", "name": "reset" }},
        {{ "kind": "tilelink", "prefix": "auto_control_xing_in", "dir": "slave" }},
        {{ "kind": "interrupt", "prefix": "auto_int_xing_out", "dir": "out" }}
      ]
    }}
  ]
}}
"""


def cmd_init(args: argparse.Namespace) -> int:
    out_dir = Path(args.dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    config_path = out_dir / "cosim.json"
    if config_path.exists() and not args.force:
        print(f"Error: {config_path} already exists. Use --force to overwrite.")
        return 1
    config_path.write_text(_INIT_TEMPLATE.format(backend=args.backend))
    print(f"Created {config_path}")
    print(
        "Edit it to point at your design, dts, mapping, and components, then run 'cosim build'."
    )
    return 0


def cmd_gen_config(args: argparse.Namespace) -> int:
    from .genconfig import gen_config

    dts_path = Path(args.dts) if args.dts else None
    return gen_config(Path(args.diplomacy_json), Path(args.output), dts_path)


def cmd_build(args: argparse.Namespace) -> int:
    from .project import build

    cfg = Config.load(Path(args.config))
    if args.jobs is not None:
        cfg.jobs = args.jobs
    return build(cfg, generate_only=args.generate_only)


def cmd_run(args: argparse.Namespace) -> int:
    from .project import run

    cfg = Config.load(Path(args.config))
    if args.jobs is not None:
        cfg.jobs = args.jobs

    if args.list:
        print(f"Components declared in {args.config}:")
        for c in cfg.components:
            needs_qemu = any(i.NEEDS_QEMU for i in c.interfaces)
            tag = (
                "qemu-coupled (cosim run " + c.name + ")"
                if needs_qemu
                else "rtl-only (cosim run rtl " + c.name + ")"
            )
            print(f"  {c.name:<24} {tag}  [{c.type}]")
        print(f"  {'(whole design)':<24} rtl-only (cosim run rtl)")
        return 0

    # 'rtl' is a reserved leading token, not a component name: `cosim run rtl
    # [COMPONENT]` runs standalone, no QEMU. Anything else - zero or more
    # component names, or none at all - couples QEMU to exactly those (or to
    # nothing, for a plain boot).
    if args.args and args.args[0] == "rtl":
        if args.all:
            raise RuntimeError(
                "--all couples QEMU to every component - it doesn't apply to 'rtl' (no QEMU)."
            )
        mode, components = "rtl", args.args[1:]
        if len(components) > 1:
            raise RuntimeError(
                "'rtl' runs one target standalone - pass at most one component name."
            )
    else:
        components = args.args
        if args.all:
            if components:
                raise RuntimeError(
                    "--all already couples every component - don't also name one."
                )
            mode = "cosim"  # couple every component with bus/interrupt/gpio IO
        else:
            mode = "qemu"  # couples the named components, or plain-boots if none given

    return run(cfg, mode, components=components, backend=args.backend)


def cmd_clean(args: argparse.Namespace) -> int:
    from .project import clean

    cfg = Config.load(Path(args.config))
    return clean(cfg, all=args.all)


def cmd_doctor(args: argparse.Namespace) -> int:
    from .toolchain import doctor_report

    toolchain = ToolchainConfig()
    if args.config and Path(args.config).exists():
        toolchain = Config.load(Path(args.config)).toolchain
    print(doctor_report(toolchain))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cosim")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Scaffold a cosim.json in a directory")
    init.add_argument(
        "dir", nargs="?", default=".", help="Directory to scaffold into (default: cwd)"
    )
    init.add_argument(
        "--backend", choices=["arcilator", "verilator"], default="arcilator"
    )
    init.add_argument(
        "-f", "--force", action="store_true", help="Overwrite an existing cosim.json"
    )
    init.set_defaults(func=cmd_init)

    gen_config = subparsers.add_parser(
        "gen-config",
        help="Derive a cosim.json component list from a design's diplomacy config",
    )
    gen_config.add_argument(
        "diplomacy_json", help="Path to the *.diplomacy.json config"
    )
    gen_config.add_argument(
        "-o", "--output", default="cosim.json", help="Output cosim.json path"
    )
    gen_config.add_argument(
        "--dts",
        default=None,
        help="Base platform dts - if given, also derives each bus's compat/path/interrupts "
        "dts mapping by matching its diplomacy address against dts node addresses",
    )
    gen_config.set_defaults(func=cmd_gen_config)

    build = subparsers.add_parser(
        "build", help="Extract components and build the cosim library"
    )
    build.add_argument(
        "-C", "--config", default="cosim.json", help="Path to cosim.json"
    )
    build.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=None,
        help="make -jN for every build step (default: 'jobs' in cosim.json, or all CPUs)",
    )
    build.add_argument(
        "--generate-only",
        action="store_true",
        help="Write every generated Makefile/config.mk (common.mk, each unit's config.mk, "
        "the qemu unit, the top Makefile) but don't invoke make",
    )
    build.set_defaults(func=cmd_build)

    run = subparsers.add_parser("run", help="Run a simulation")
    run.add_argument(
        "args",
        nargs="*",
        metavar="[rtl] [COMPONENT ...]",
        help="No arguments: plain QEMU boot, no RTL coupling. One or more component "
        "names: couple QEMU to each (its own dtb overlay node and its own sim "
        "process) - e.g. 'cosim run TLUART TLGPIO'. Prefix with the literal "
        "'rtl' to skip QEMU and run standalone instead - at most one component "
        "name (each gets its own sim binary), or omit it for the whole, "
        "un-extracted design (build/sim, always built alongside any declared "
        "components) - e.g. 'cosim run rtl' or 'cosim run rtl TLUART'.",
    )
    run.add_argument(
        "--all",
        action="store_true",
        help="Couple QEMU to every component with bus/interrupt/gpio IO, without naming them "
        "(mutually exclusive with naming components or with 'rtl')",
    )
    run.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="List the component names declared in cosim.json (and whether each is "
        "qemu-coupled or rtl-only), then exit - runs nothing.",
    )
    run.add_argument("-C", "--config", default="cosim.json", help="Path to cosim.json")
    run.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=None,
        help="make -jN when regenerating the dtb (default: 'jobs' in cosim.json, or all CPUs)",
    )
    run.add_argument(
        "--backend",
        choices=["arcilator", "verilator"],
        default=None,
        help="Which built backend to run (must be one of design.supported_backends in cosim.json; "
        "default: the first one listed)",
    )
    run.set_defaults(func=cmd_run)

    clean = subparsers.add_parser("clean", help="Remove build artifacts")
    clean.add_argument(
        "-C", "--config", default="cosim.json", help="Path to cosim.json"
    )
    clean.add_argument(
        "--all",
        action="store_true",
        help="Also remove each component's scaffolded Makefile, sim.cpp, and any hand-added "
        "sources (e.g. periph.cpp) - by default those survive `cosim clean` since they "
        "may be hand-edited; only the machine-owned config.mk and nested build/ artifacts "
        "are removed.",
    )
    clean.set_defaults(func=cmd_clean)

    doctor = subparsers.add_parser("doctor", help="Report resolved toolchain paths")
    doctor.add_argument(
        "-C",
        "--config",
        default=None,
        help="Optional cosim.json to read toolchain overrides from",
    )
    doctor.set_defaults(func=cmd_doctor)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        sys.exit(args.func(args))
    except (
        RuntimeError,
        ValueError,
        FileNotFoundError,
        KeyError,
        subprocess.CalledProcessError,
    ) as e:
        # Print user-facing error directly
        print(f"cosim: error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
