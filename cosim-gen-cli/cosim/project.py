"""Build/run orchestration: renders small generated Makefiles around the
mk/*.mk engine, drives the codegen module to assemble each component's own
sim.cpp + the combined QEMU overlay, and links the results.

Each extracted component gets its own sim binary and its own remote-port
channel (see codegen/sim_main.py, codegen/dts_overlay.py) - they
are never assembled into one shared Top/QemuTLM. The "whole design as the
model" case (cosim.json has no components) is the degenerate one-component
case and keeps producing a single build/sim, same as before.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

from . import paths
from .codegen import dts_overlay
from .codegen.main import processJson
from .config import Config
from .toolchain import ResolvedToolchain, resolve


def _write_if_changed(path: Path, content: str) -> None:
    # Leave the file's mtime alone when content is unchanged, so config.mk's
    # own mtime is a meaningful staleness signal for the make rules keyed on
    # it (see mk/component.mk's extraction targets) - otherwise every `cosim
    # build` would bump it and force a full re-extraction even when nothing
    # in cosim.json changed. Same pattern as codegen/main.py's own
    # _write_if_changed, for the same reason.
    if not path.exists() or path.read_text() != content:
        path.write_text(content)


def _run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def _run_make(build_dir: Path, name: str, variables: dict[str, str], include: Path, targets: list[str],
              jobs: int | None = None):
    build_dir.mkdir(parents=True, exist_ok=True)
    mk_path = build_dir / f"_{name}.mk"
    # Escape literal "$" as "$$" - Make's ":=" assignment expands "$" immediately
    # while parsing this file, so an unescaped "$" in e.g. a component's IO
    # regex (which is full of "$" anchors) gets silently eaten before the
    # recipe that actually uses the variable ever runs.
    lines = [f"{k} := {str(v).replace('$', '$$')}" for k, v in variables.items() if v is not None]
    lines.append(f"include {include}")
    mk_path.write_text("\n".join(lines) + "\n")
    # Run from build_dir, not the caller's cwd: firtool resolves a
    # MemoryFileInlineAnnotation's filename (a bare relative name, e.g.
    # "bootrom.mem") against its own working directory.
    _run(["make", "-f", mk_path, f"-j{jobs or os.cpu_count() or 1}"] + targets, cwd=build_dir)


def _design_top_name(design_input: Path) -> str:
    # The whole-design model's top module name, needed at makefile-generation
    # time - i.e. *before* design.hw.mlir is built by the single make call - so
    # it's read from the input, not the (not-yet-existing) output. firtool keeps
    # the FIRRTL circuit's main module as the sole public hw.module, so a .fir's
    # `circuit <Name>` is the lowered top; an already-lowered .mlir input is
    # grepped for its public hw.module directly.
    text = design_input.read_text()
    if design_input.name.endswith(".mlir"):
        matches = re.findall(r"^\s*hw\.module\s+@(\w+)\(", text, re.MULTILINE)
        what = "public hw.module"
    else:
        matches = re.findall(r"^\s*circuit\s+(\w+)\s*:", text, re.MULTILINE)
        what = "circuit"
    uniq = list(dict.fromkeys(matches))
    if not uniq:
        raise RuntimeError(f"No {what} found in {design_input}")
    if len(uniq) > 1:
        raise RuntimeError(
            f"Multiple {what} names in {design_input} ({uniq}); "
            "specify a component in cosim.json to select one"
        )
    return uniq[0]


def _unit_spec(cfg: Config, comp, whole: bool, build_dir: Path) -> dict:
    """One entry in the build graph: a declared component (whole=False), or
    the whole, un-extracted design as its own standalone model (whole=True) -
    a pseudo-component with no path/io to extract by, living under
    components/<TopName>/ just like any real one, built alongside the
    components rather than instead of them. `comp` is None for a whole-design
    build with no cosim.json 'soc_rtl' declaration - `whole` (not `comp is
    None`) drives name/path/io_regex/top_name since soc_rtl (when given) is a
    real Component that still describes the un-extracted whole design, not an
    extracted one. One unit serves every backend in design.supported_backends
    at once (see mk/component.mk) - `cosim build` builds all of them from this
    one directory; `cosim run --backend` picks which built variant to
    execute."""
    name = _design_top_name(cfg.design.input) if whole else comp.name
    return {
        "name": name,
        "dir": build_dir / "components" / name,
        "whole": whole,
        # Nothing renames the whole design's top, so TOP_NAME is its own name;
        # an extracted component is renamed to <name>_TOP by cosim-extract.
        "top_name": name if whole else comp.top_name,
        "path": "" if whole else comp.path,
        "io_regex": "" if whole else comp.io_regex,
        # No Component (declared or soc_rtl) to override with, so fall back
        # to the top-level default.
        "sync_quantum": cfg.sync_quantum if comp is None or comp.sync_quantum is None else comp.sync_quantum,
        "max_cycles": cfg.max_cycles if comp is None or comp.max_cycles is None else comp.max_cycles,
        "extra_args": cfg.extra_args if comp is None or comp.extra_args is None else comp.extra_args,
    }


def _render_common_mk(cfg: Config, tools: ResolvedToolchain, build_dir: Path,
                      design_hw_mlir: Path, verilator_root: str) -> str:
    """Everything every unit's own config.mk would otherwise repeat verbatim,
    regardless of which backend that unit builds: the resolved toolchain, and
    paths fixed for the whole `cosim build` (the lowered design,
    libsystemctlm, this checkout's mk/include/third_party dirs). One file at
    the build root instead of N identical copies - each unit's own config.mk
    includes it (see _render_config_mk) rather than restating it, and the top
    build/Makefile does the same instead of resolving the overlapping subset
    (COSIM_MK_DIR/SYSTEMC_INCLUDE/SYSTEMC_LIBDIR/DESIGN_HW_MLIR/FIRTOOL) a
    second time."""
    lines = [
        "# Regenerated by `cosim build` - do not edit; shared by every unit's",
        "# own config.mk (see mk/component.mk) and the top build/Makefile.",
        f"DESIGN_HW_MLIR := {design_hw_mlir}",
        f"LIBSYSTEMCTLM := {build_dir / 'systemctlm' / 'libsystemctlm.a'}",
        f"RTLGEN_INC_DIR := {paths.INCLUDE_DIR}",
        f"LIBSOC_DIR := {paths.LIBSYSTEMCTLM_SOC_DIR}",
        f"COSIM_MK_DIR := {paths.MK_DIR}",
        f"PYTHON := {sys.executable}",
        f"SYSTEMC_INCLUDE := {tools.require('systemc_include')}",
        f"SYSTEMC_LIBDIR := {tools.require('systemc_lib')}",
        f"COSIM_EXTRACT := {tools['cosim_extract']}",
        f"COSIM_GEN_OPT := {tools['cosim_gen_opt']}",
        f"QEMU := {tools['qemu']}",
        f"ARCILATOR := {tools['arcilator']}",
        f"FIRTOOL := {tools['firtool']}",
        f"VERILATOR := {tools['verilator']}",
        f"VERILATOR_ROOT := {verilator_root}",
        f"OPT := {tools['opt']}",
        f"LLC := {tools['llc']}",
    ]
    return "\n".join(lines) + "\n"


def _render_config_mk(cfg: Config, unit: dict) -> str:
    """The machine-owned half of a unit's build: regenerated every `cosim
    build`, so cosim.json edits (a moved --path, a new bus, a different
    freq_mhz) always take effect. Never hand-edit this - see the unit's own
    Makefile for the hooks meant to be edited. Everything NOT specific to
    this one unit lives in common.mk instead (see _render_common_mk) -
    SUPPORTED_BACKENDS itself is here, not there, since which backends this
    build supports is a whole-project fact but mk/component.mk needs it
    per-unit to know which of its always-defined backend rule blocks `all`
    should actually depend on."""
    # `$` in the port regex is a make metachar - escape to `$$` so it survives
    # to the recipe verbatim (the anchors matter to cosim-extract's --port).
    io = unit["io_regex"].replace("$", "$$")
    if unit["whole"]:
        io_flags = f"--config {cfg.path} --soc-rtl" if cfg.soc_rtl is not None else ""
    else:
        io_flags = f"--config {cfg.path} --component {unit['name']}"
    lines = [
        "# Regenerated by `cosim build` - do not edit; see Makefile for hooks.",
        # Relative, like the unit Makefile's own `include config.mk` - every
        # unit lives at the same fixed depth (build/components/<name>/), so
        # this stays valid even if the whole cosim.json project moves. A real
        # prerequisite (not order-only) of mk/component.mk's extraction
        # targets, same as this file itself - a toolchain/backend change must
        # invalidate every unit just as much as a per-unit cosim.json edit does.
        "COMMON_MK := ../../common.mk",
        "include $(COMMON_MK)",
        f"SUPPORTED_BACKENDS := {' '.join(cfg.design.supported_backends)}",
        f"COMPONENT_NAME := {unit['name']}",
        f"COMPONENT_PATH := {unit['path']}",
        f"COMPONENT_IO := {io}",
        f"TOP_NAME := {unit['top_name']}",
        f"IS_COMPONENT := {0 if unit['whole'] else 1}",
        f"CONFIG_COMPONENT_FLAG := {io_flags}",
    ]
    return "\n".join(lines) + "\n"


_MAKEFILE_SCAFFOLD = """\
# {name} build. Safe to edit - created once by `cosim build`, never
# overwritten or removed by it again (only `cosim clean --all` removes it).
# Machine-generated config lives in config.mk (regenerated every build, do
# not edit - it includes ../../common.mk for the vars shared by every unit);
# shared rules are in $(COSIM_MK_DIR)/component.mk. COSIM_MK_DIR itself comes
# from that include, so this file stays valid even if the cosim checkout moves.
include config.mk

# --- your customization ------------------------------------------------------
EXTRA_SRCS       ?=        # extra .cpp linked into sim - e.g. your own periph.cpp
EXTRA_CXXFLAGS   ?=
EXTRA_LDLIBS     ?=
SYNC_QUANTUM     ?= {sync_quantum}    # cycles between remote-port syncs (make run-coupled)
MAX_CYCLES       ?= {max_cycles}      # 0 = unbounded; stop `make run`/`run-coupled` after this many clock cycles
RUN_ARGS         ?= {run_args}        # extra args passed to `make run` / `make run-coupled`, after MAX_CYCLES
GENERATE_SIM_CPP ?= 1      # set to 0 to hand-own sim.cpp (stops regeneration)
TRACE            ?= 0      # 1 = this backend's own native internal-signal tracer
                           #     (verilator: VCD; arcilator: its own format)
SYSC_TRACE       ?= 0      # 1 = generic boundary-level VCD of Top's own ports (either backend,
                           #     independent of/combinable with TRACE above)
VM_COVERAGE      ?= 0      # 1 = verilator's own line/toggle coverage (verilator backend only)
VERILATOR_ARGS   ?= -DPRINTF_COND=1 -DASSERT_VERBOSE_COND=1 -DSTOP_COND=1 -Wno-fatal -O3 \\
                     --x-assign fast --x-initial fast --noassert \\
                     -Wno-WIDTHEXPAND -Wno-UNSIGNED -Wno-WIDTHTRUNC -Wno-TIMESCALEMOD \\
                     --expand-limit 1024
ARCILATOR_ARGS   ?=
# ------------------------------------------------------------------------------

include $(COSIM_MK_DIR)/component.mk
"""


# The machine-owned half of build/qemu/'s Makefile pair - rewritten every
# `cosim build` so a toolchain change (a different QEMU binary) takes effect.
_QEMU_CONFIG_MK = """\
# Regenerated by `cosim build` - do not edit; see Makefile for hooks.
COMMON_MK := ../common.mk
include $(COMMON_MK)
"""


_QEMU_MAKEFILE_SCAFFOLD = """\
# QEMU invocation. Safe to edit - created once by `cosim build`, never
# overwritten or removed by it again (only `cosim clean --all` removes it).
# Machine-generated config lives in config.mk (regenerated every build, do
# not edit - it includes ../common.mk for the vars shared by every unit);
# shared rules are in $(COSIM_MK_DIR)/qemu.mk. COSIM_MK_DIR itself comes from
# that include, so this file stays valid even if the cosim checkout moves.
include config.mk

# --- your customization ------------------------------------------------------
ELFS         ?= {elfs}            # ELF files passed to QEMU via -device loader, in order
QEMU_ARGS    ?= {qemu_args}       # extra qemu flags, appended after the ELF loaders
SYNC_QUANTUM ?= {sync_quantum}    # max ns between QEMU<->remote-port syncs (run-qemu-coupled only)
# ------------------------------------------------------------------------------

include $(COSIM_MK_DIR)/qemu.mk
"""


def _render_top_makefile(cfg: Config, tools: ResolvedToolchain, build_dir: Path,
                         units: list[dict]) -> str:
    """The top build/Makefile: builds the shared prerequisites (design
    lowering, libsystemctlm) once, then recurses into each unit's own
    Makefile (`make -C components/<name>`) - each unit is independently
    buildable/runnable, and 'one cosim build' is still one `make` process
    driving the whole recursive tree. Each unit's own Makefile in turn builds
    every backend in design.supported_backends itself (see mk/component.mk) -
    there's no backend-level fan-out here."""
    lowered_input = cfg.design.input.name.endswith(".mlir")
    # firrtl-keep-interfaces runs during firtool, before cosim-extract ever
    # renames a component to <type>_TOP - so it must match on the original
    # FIRRTL module name (c.type), not the post-extraction top_name.
    type_names = " ".join(c.type for c in cfg.components)

    lines = [
        "# Generated by `cosim build` - do not edit; re-run `cosim build`.",
        f"include {build_dir / 'common.mk'}",
        f"TLM_BUILD_DIR := {build_dir / 'systemctlm'}",
        ".DEFAULT_GOAL := all",
    ]
    if not lowered_input:
        # Design lowering is a rule here (not a pre-make Python step), so a
        # .fir edit propagates to every unit through this one make process.
        # FIRTOOL itself already came from common.mk's include above.
        lines += [
            f"DESIGN_INPUT := {cfg.design.input}",
            f"COSIM_PLUGIN := {tools['cosim_plugin'] if type_names else ''}",
            f"ANNOTATION_FILE := {cfg.design.annotations or ''}",
            f"SEQMEM_FILE := {cfg.design.seqmem or ''}",
            f"COMPONENT_TYPE_NAMES := {type_names}",
            f"include {paths.MK_DIR / 'firtool.mk'}",
        ]
    lines.append(f"include {paths.MK_DIR / 'systemctlm.mk'}")

    unit_names = " ".join(u["name"] for u in units)
    lines += [
        f"UNITS := {unit_names}",
        ".PHONY: all $(UNITS)",
        "all: $(UNITS)",
        "$(UNITS): $(DESIGN_HW_MLIR) $(LIBSYSTEMCTLM)",
        # '+' marks this as a sub-make so each unit's own make invocation
        # shares our jobserver - units build in parallel under one `-jN`.
        "\t+$(MAKE) -C components/$@",
    ]
    return "\n".join(lines) + "\n"


def _extra_files(cfg: Config) -> list[Path]:
    """Every file staged into build_dir before firtool runs: each component's
    (and soc_rtl's) own extra_files. Additive, not overriding - there's one
    firtool call for the whole design, so a component's extra_files just
    documents which files it cares about, not a separate staging location."""
    files = [f for c in cfg.components for f in c.extra_files]
    if cfg.soc_rtl is not None:
        files += cfg.soc_rtl.extra_files
    return files


def _missing_required_tools(cfg: Config, tools: ResolvedToolchain, lowered_input: bool) -> list[str]:
    """Every tool this project's `cosim build` will actually shell out to,
    given every backend in design.supported_backends and whether design.input
    still needs firtool lowering. Checked up front so a missing one fails
    with a clear message right here - _render_common_mk/_render_top_makefile
    write tool paths straight into generated Makefiles with no None-check of
    their own, so an unresolved tool otherwise surfaces much later as a
    cryptic 'sh: None: not found' or '$(error ...)' from deep inside a make
    recipe."""
    backends = cfg.design.supported_backends
    required = ["cosim_extract", "systemc_include", "systemc_lib"]
    # firtool lowers the whole design (unless it's already .mlir) and, for
    # the verilator backend, also --split-verilog's every unit regardless.
    if not lowered_input or "verilator" in backends:
        required.append("firtool")
    # Only needed for the firrtl-keep-interfaces pass, itself only run
    # during whole-design lowering when components[] exist to keep alive.
    if not lowered_input and cfg.components:
        required.append("cosim_plugin")
    if "arcilator" in backends:
        required += ["arcilator", "opt", "llc"]
    if "verilator" in backends:
        required.append("verilator")
    return [name for name in required if tools[name] is None]


def build(cfg: Config, generate_only: bool = False) -> int:
    build_dir = cfg.root / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    tools = resolve(cfg.toolchain)

    lowered_input = cfg.design.input.name.endswith(".mlir")
    missing = _missing_required_tools(cfg, tools, lowered_input)
    if missing:
        hints = "\n".join(
            f"  {name}: set toolchain.{name} in cosim.json, the {name.upper()} env var, or install it on $PATH"
            for name in missing
        )
        raise RuntimeError(f"cosim build: required tool(s) not found - {', '.join(missing)}\n{hints}")

    # firtool resolves a MemoryFileInlineAnnotation's bare relative filename
    # (e.g. "bootrom.mem") against its own cwd, which is build_dir when make runs.
    for f in _extra_files(cfg):
        shutil.copy2(f, build_dir / f.name)

    design_hw_mlir = (
        cfg.design.input if lowered_input
        else build_dir / "design.hw.mlir"
    )

    verilator_root = ""
    if "verilator" in cfg.design.supported_backends:
        verilator_root = subprocess.run(
            [str(tools.require("verilator")), "--getenv", "VERILATOR_ROOT"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

    # Shared by every unit's own config.mk (see _render_common_mk) instead of
    # each repeating an identical copy - written once, before the per-unit
    # loop below.
    _write_if_changed(
        build_dir / "common.mk",
        _render_common_mk(cfg, tools, build_dir, design_hw_mlir, verilator_root),
    )

    # One unit per component, plus one for the whole design (soc_rtl) - each
    # builds every design.supported_backends entry itself (see
    # mk/component.mk); `cosim run --backend` picks which built variant to
    # execute.
    comps: list = [c for c in cfg.components] + [cfg.soc_rtl]
    wholes = [False] * len(cfg.components) + [True]
    units = [_unit_spec(cfg, comp, whole, build_dir) for comp, whole in zip(comps, wholes)]
    for comp, unit in zip(comps, units):
        unit["dir"].mkdir(parents=True, exist_ok=True)
        for f in (comp.extra_files if comp is not None else []):
            shutil.copy2(f, unit["dir"] / f.name)
        _write_if_changed(unit["dir"] / "config.mk", _render_config_mk(cfg, unit))
        makefile = unit["dir"] / "Makefile"
        if not makefile.exists():
            # Scaffolded once - a user's EXTRA_SRCS/flags/SYNC_QUANTUM edits
            # here must survive every future `cosim build`.
            makefile.write_text(_MAKEFILE_SCAFFOLD.format(
                name=unit["name"], sync_quantum=unit["sync_quantum"], max_cycles=unit["max_cycles"],
                run_args=" ".join(unit["extra_args"]),
            ))

    qemu_dir = build_dir / "qemu"
    qemu_dir.mkdir(parents=True, exist_ok=True)
    (qemu_dir / "config.mk").write_text(_QEMU_CONFIG_MK)
    qemu_makefile = qemu_dir / "Makefile"
    if not qemu_makefile.exists():
        # Scaffolded once - a user's ELFS/QEMU_ARGS/SYNC_QUANTUM edits here
        # must survive every future `cosim build`.
        qemu_makefile.write_text(_QEMU_MAKEFILE_SCAFFOLD.format(
            elfs=" ".join(str(e) for e in cfg.qemu.elfs),
            qemu_args=" ".join([
                "-serial", "mon:stdio", "-display", "none",
                *cfg.qemu.extra_args,
            ]),
            sync_quantum=cfg.sync_quantum,
        ))

    top_makefile = build_dir / "Makefile"
    top_makefile.write_text(_render_top_makefile(cfg, tools, build_dir, units))

    overlay_components = [c.name for c in cfg.components if any(i.NEEDS_QEMU for i in c.interfaces)]
    if overlay_components and cfg.design.dts:
        (build_dir / "cosim_components.json").write_text(json.dumps(overlay_components) + "\n")

    if generate_only:
        return 0

    _run(["make", "-f", top_makefile, f"-j{cfg.jobs or os.cpu_count() or 1}", "all"], cwd=build_dir)

    for unit in units:
        for backend in cfg.design.supported_backends:
            print(f"Built {unit['dir'] / f'build-{backend}' / 'sim'}")

    return 0


def _component_typed_io(comp, comp_dir: Path, backend: str):
    # comp_dir is the unit dir (build/components/<name>/); its own
    # build-<backend>/ subfolder holds that backend's extracted state.json,
    # same as its "sim" binary. IO classification doesn't depend on backend
    # (same declared interfaces, same --top-name either way), so any built
    # backend's own state json works - callers pass whichever is relevant
    # (the run's selected backend, or a canonical one for build()'s own
    # bookkeeping).
    state_json = comp_dir / f"build-{backend}" / f"{comp.name}.json"
    if not state_json.exists():
        raise RuntimeError(f"{state_json} not found - run 'cosim build' first")
    models = processJson(state_json, io_spec=comp)
    assert len(models) == 1, f"component {comp.name}: expected exactly one top module in its state json"
    return models[0].typedIO


def _gen_dtb(cfg: Config, tools: ResolvedToolchain, build_dir: Path, comp_names: list[str] | None,
             backend: str) -> Path:
    """(Re)generates build/cosim.dts/.dtb fresh on every call - this is what a
    'run' command actually boots from, so it must reflect the *current*
    component declarations (including each bus's compat/path/interrupts dts
    mapping), not whatever `cosim build` last happened to write. Each coupled
    component's own overlay fragment is (re)written to its own unit dir
    (build/components/<name>/overlay.dts - shared across backends, since the
    overlay only depends on bus/interrupt/gpio classification, not on which
    backend built the component); build/cosim.dts is just a thin `/include/`
    of the base platform dts plus exactly those fragments. `comp_names=None`
    compiles design.dts as-is, no remote-port overlay at all - no RTL
    coupling, no -machine-path needed. A non-empty list overlays *only* those
    components: 'qemu --component X' must not reuse the all-components
    overlay, or QEMU waits forever on sockets for every other coupled
    component that was never spawned. `backend` selects which built variant's
    own state json this run classifies IO from - the one `cosim run --backend`
    picked (classification itself doesn't vary by backend)."""
    if not cfg.design.dts:
        raise RuntimeError("this needs design.dts (a base platform device tree) to build the DTB from.")
    cosim_dts = build_dir / "cosim.dts"
    overlay_paths: list[str] = []
    if comp_names:
        comps_by_name = {c.name: c for c in cfg.components}
        tree, sys_bus = dts_overlay.open_base_tree(str(cfg.design.dts))
        for name in comp_names:
            comp = comps_by_name[name]
            unit_dir = build_dir / "components" / name
            typed_io = _component_typed_io(comp, unit_dir, backend)
            overlay_dts = dts_overlay.gen_component_dts(name, comp, typed_io, tree, sys_bus)
            overlay_path = unit_dir / "overlay.dts"
            overlay_path.write_text(overlay_dts)
            overlay_paths.append(str(overlay_path.relative_to(build_dir)))
    cosim_dts.write_text(dts_overlay.gen_run_dts(cfg.design.dts.name, overlay_paths))
    dtb = cosim_dts.with_suffix(".dtb")
    _run_make(
        build_dir, "dtb",
        {"DTC": tools["dtc"], "DTS_INCLUDE_DIR": cfg.design.dts.parent},
        include=paths.MK_DIR / "qemu.mk",
        targets=[str(dtb)],
        jobs=cfg.jobs,
    )
    return dtb


def _run_coupled(cfg: Config, build_dir: Path, dtb: Path, comp_names: list[str], backend: str) -> int:
    # One sim process per component, each its own remote-port chardev/socket
    # under one shared machine-path, matching the RP_<name>/chrdev-id scheme
    # dts_overlay.gen_component_dts declared for it in `dtb`. Each is started
    # via that unit's own `make run-coupled` (mk/component.mk) rather than
    # exec'ing build/sim directly - SOCK and SYNC_QUANTUM are always passed
    # (SYNC_QUANTUM resolved from cosim.json here, not left to the unit's own
    # Makefile default, so a component's own override or the top-level
    # default always takes effect without needing a rebuild); MAX_CYCLES is
    # whatever the unit's own Makefile has (seeded from its cosim.json
    # override, or the top-level default, at scaffold time - see
    # _MAKEFILE_SCAFFOLD - and hand-editable after).
    comps_by_name = {c.name: c for c in cfg.components}
    machine_path = Path(tempfile.mkdtemp(prefix="qemu-cosim."))
    procs = []
    try:
        sync_quantums = []
        for name in comp_names:
            unit = _unit_spec(cfg, comps_by_name[name], False, build_dir)
            sync_quantums.append(unit["sync_quantum"])
            # Matches RemotePort's own rp_autocreate_chardev() naming
            # (hw/core/remote-port.c): "qemu-rport-<node-name>", where
            # <node-name> is this component's own <name> node -
            # confirmed against QEMU's own "waiting for connection on ..."
            # diagnostic (no leading "_" - that would only apply if the node
            # sat under a path prefix, which it doesn't here, it's a direct
            # child of the root).
            sock = machine_path / f"qemu-rport-{name.lower()}"
            cmd = ["make", "-C", str(unit["dir"]), "run-coupled", f"SOCK={sock}", f"BACKEND={backend}",
                   f"SYNC_QUANTUM={unit['sync_quantum']}"]
            print("+", " ".join(cmd))
            # New session (own process group) so the `finally` below can kill
            # make's whole recipe pipeline (the shell it spawns, and that
            # shell's own `./sim ... | tee` children) - terminating just the
            # make process itself wouldn't reach the sim binary underneath it.
            procs.append(subprocess.Popen(cmd, start_new_session=True))

        # Shells out to build/qemu's own `make run-qemu-coupled` (mk/qemu.mk),
        # same as the plain-boot case above - ELFS/QEMU_ARGS come from that
        # unit's own Makefile; DTB/MACHINE_PATH/LOG are per-invocation, always
        # passed on the command line, same as SOCK/BACKEND above. QEMU's own
        # -sync-quantum gets the minimum of the coupled components' own
        # sync_quantum (same values just passed to their sim processes above,
        # not a separate guess) - the RTL side's tightest sync requirement is
        # the one QEMU must not sync less often than.
        _run(["make", "-C", str(build_dir / "qemu"), "run-qemu-coupled",
              f"DTB={dtb}", f"MACHINE_PATH={machine_path}", f"LOG={build_dir / 'run.log'}",
              f"SYNC_QUANTUM={min(sync_quantums)}"])
    finally:
        for p in procs:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for p in procs:
            p.wait()
        shutil.rmtree(machine_path, ignore_errors=True)
    return 0


def _resolve_sim_target(cfg: Config, build_dir: Path, component: str | None, backend: str) -> Path:
    # No component name => the whole, un-extracted design - a pseudo-component
    # under components/<TopName>/, always built by build() alongside any
    # declared components. "rtl" mode defaults to it, not to guessing at one
    # extracted piece.
    name = _design_top_name(cfg.design.input) if component is None else component
    if component is not None:
        valid = {c.name for c in cfg.components}
        if component not in valid:
            raise RuntimeError(f"Unknown component {component!r}; valid: {', '.join(sorted(valid))}")
    return build_dir / "components" / name / f"build-{backend}" / "sim"


def run(cfg: Config, mode: str, components: list[str] | None = None, backend: str | None = None) -> int:
    build_dir = cfg.root / "build"
    tools = resolve(cfg.toolchain)
    components = components or []
    backend = backend or cfg.design.supported_backends[0]
    if backend not in cfg.design.supported_backends:
        raise RuntimeError(
            f"backend {backend!r} isn't in design.supported_backends "
            f"({', '.join(cfg.design.supported_backends)})"
        )

    if mode == "rtl":
        if len(components) > 1:
            raise RuntimeError("'rtl' mode runs one target standalone - pass at most one component name.")
        comp_name = components[0] if components else None
        is_component = comp_name is not None
        comp = cfg.soc_rtl if not is_component else next((c for c in cfg.components if c.name == comp_name), None)
        _resolve_sim_target(cfg, build_dir, comp_name, backend)  # raises if comp_name is unknown
        unit = _unit_spec(cfg, comp, not is_component, build_dir)
        # Shells out to this unit's own `make run` (mk/component.mk) instead
        # of exec'ing build-<backend>/sim directly - MAX_CYCLES/RUN_ARGS are
        # whatever that unit's own Makefile has (seeded from its cosim.json
        # max_cycles/extra_args at scaffold time, hand-editable after).
        # BACKEND=<selected> picks which built backend's sim binary `make
        # run` actually executes (default there is the first supported one,
        # same as here). That recipe already tees to this unit's own
        # build-<backend>/run.log, the same path whether it ran via `cosim
        # run rtl` or by hand - so there's one canonical log per backend, not
        # two.
        jobs = f"-j{cfg.jobs or os.cpu_count() or 1}"
        _run(["make", "-C", unit["dir"], jobs, "run", f"BACKEND={backend}"])
        return 0

    if mode == "qemu":
        if not components:
            # Plain boot, no RTL coupling at all: design.dts as-is, no
            # remote-port overlay, no -machine-path, no sim peers to wait on.
            # Shells out to build/qemu's own `make run-qemu` (mk/qemu.mk)
            # instead of exec'ing qemu directly - ELFS/QEMU_ARGS are whatever
            # that unit's own Makefile has (seeded from cosim.json's
            # qemu.elfs/qemu.extra_args at scaffold time, hand-editable
            # after). That recipe already tees to build/run.log.
            dtb = _gen_dtb(cfg, tools, build_dir, None, backend)
            _run(["make", "-C", str(build_dir / "qemu"), "run-qemu",
                  f"DTB={dtb}", f"LOG={build_dir / 'run.log'}"])
            return 0

        # Just these components: their own overlay/dtb, their own sim
        # processes - not the all-components overlay, which would leave QEMU
        # waiting on sockets for every other coupled component never spawned.
        valid = {c.name for c in cfg.components}
        unknown = [name for name in components if name not in valid]
        if unknown:
            raise RuntimeError(f"Unknown component(s) {', '.join(unknown)}; valid: {', '.join(sorted(valid))}")
        comps_by_name = {c.name: c for c in cfg.components}
        for name in components:
            typed_io = _component_typed_io(comps_by_name[name], build_dir / "components" / name, backend)
            if not typed_io.needs_qemu:
                raise RuntimeError(f"{name!r} has no bus/interrupt/gpio IO - use `cosim run rtl {name}` instead.")
        dtb = _gen_dtb(cfg, tools, build_dir, components, backend)
        return _run_coupled(cfg, build_dir, dtb, components, backend)

    # mode == "cosim": one sim process per component that needs QEMU coupling
    # (see build()'s cosim_components.json for which ones), all sharing one
    # QEMU instance. Any COMPONENT args are ignored - it's always all of them.
    manifest_path = build_dir / "cosim_components.json"
    if not manifest_path.exists():
        raise RuntimeError(
            "No components need QEMU coupling (no bus/interrupt IO) - use `cosim run rtl` "
            "or `cosim run` (a plain boot) instead."
        )
    comp_names = json.loads(manifest_path.read_text())
    dtb = _gen_dtb(cfg, tools, build_dir, comp_names, backend)
    return _run_coupled(cfg, build_dir, dtb, comp_names, backend)


def clean(cfg: Config, all: bool = False) -> int:
    build_dir = cfg.root / "build"
    if all or not build_dir.exists():
        _run(["rm", "-rf", build_dir])
        return 0

    # Artifact-only clean: each unit's scaffolded Makefile, sim.cpp, and any
    # user-added sources (periph.cpp, ...) live directly under
    # components/<name>/ and are never touched here - only the machine-owned
    # config.mk, overlay.dts, and each backend's own nested build-<backend>/
    # artifact dir are. Use `cosim clean --all` to also wipe those (loses hand
    # edits).
    targets = [
        build_dir / "Makefile",
        build_dir / "common.mk",
        build_dir / "design.hw.mlir",
        build_dir / "systemctlm",
        build_dir / "cosim.dts",
        build_dir / "cosim.dtb",
        build_dir / "cosim_components.json",
        build_dir / "run.log",
    ]
    targets += [build_dir / f.name for f in _extra_files(cfg)]
    components_dir = build_dir / "components"
    if components_dir.is_dir():
        for unit_dir in sorted(components_dir.iterdir()):
            targets += [unit_dir / "config.mk", unit_dir / "overlay.dts"]
            for entry in sorted(unit_dir.iterdir()):
                if entry.is_dir() and entry.name.startswith("build-"):
                    targets.append(entry)
    _run(["rm", "-rf", *targets])
    return 0
