"""Load and validate a cosim.json project configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .interfaces import (
    ClockInterface,
    Interface,
    ResetInterface,
    load_interface,
)


def _resolve(root: Path, value: str | None) -> Path | None:
    """Resolve a path in the config relative to the directory cosim.json lives in."""
    if not value:
        return None
    p = Path(value).expanduser()
    return p if p.is_absolute() else (root / p).resolve()


@dataclass
class DesignConfig:
    input: Path
    # dts is only needed to generate the QEMU device-tree overlay - a design
    # with no bus/interrupt IO can be built and run in "rtl" mode without it.
    # The QEMU-side dts binding lives on the owning component's own
    # 'compat'/'dts_path' fields, not per-bus - see Component below.
    dts: Path | None = None
    seqmem: Path | None = None
    annotations: Path | None = None
    # Every backend `cosim build` builds a unit for - `cosim run --backend`
    # then picks which built variant to execute (default: the first one
    # listed). Required, no default: which backends a design actually lowers
    # on is a fact about *this design* (e.g. async-reset registers arcilator
    # can't lower), not a build-tuning knob, and not something safe to guess.
    supported_backends: list[str] = field(default_factory=list)

    @staticmethod
    def load(root: Path, d: dict) -> DesignConfig:
        if "input" not in d:
            raise ValueError("cosim.json: design.input is required")
        if not d["input"]:
            raise ValueError("cosim.json: design.input must be a non-empty path")
        if "supported_backends" not in d:
            raise ValueError(
                "cosim.json: design.supported_backends is required - a list of the "
                "backend(s) this design lowers on and `cosim build` builds, e.g. "
                "[\"arcilator\"] or [\"verilator\"] - see cosim-gen-cli/README.md"
            )
        backends = d["supported_backends"]
        if not isinstance(backends, list) or not backends:
            raise ValueError(
                f"cosim.json: design.supported_backends must be a non-empty list, got {backends!r}"
            )
        bad = [b for b in backends if b not in ("arcilator", "verilator")]
        if bad:
            raise ValueError(
                f"cosim.json: design.supported_backends entries must be 'arcilator' or "
                f"'verilator', got {bad!r}"
            )
        if len(set(backends)) != len(backends):
            raise ValueError(f"cosim.json: design.supported_backends has duplicate entries: {backends!r}")
        return DesignConfig(
            input=_resolve(root, d["input"]),
            dts=_resolve(root, d.get("dts")),
            seqmem=_resolve(root, d.get("seqmem")),
            annotations=_resolve(root, d.get("annotations")),
            supported_backends=list(backends),
        )


@dataclass
class QemuConfig:
    # ELF files passed to QEMU via `-device loader`, in order (bootrom, test
    # image, ...).
    elfs: list[Path] = field(default_factory=list)
    # Extra args appended verbatim to every qemu invocation
    # (plain boot and coupled) - an escape hatch for anything project.py
    # doesn't otherwise expose a dedicated knob for.
    extra_args: list = field(default_factory=list)
    # QEMU's own -sync-quantum for run-qemu-coupled: how often *QEMU itself*
    # syncs with the coupled remote-port sim processes. Independent of any
    # component's own sync_quantum (that governs how often each RTL sim
    # syncs on its side, and can differ per component) - QEMU has one global
    # knob, so this is its own setting, not derived from components. None
    # falls back to the top-level Config.sync_quantum default.
    sync_quantum: int | None = None

    @staticmethod
    def load(root: Path, d: dict) -> QemuConfig:
        return QemuConfig(
            elfs=[_resolve(root, f) for f in d.get("elfs", [])],
            extra_args=[str(a) for a in d.get("extra_args", [])],
            sync_quantum=d.get("sync_quantum"),
        )


@dataclass
class Component:
    # Every port this component exposes, one entry per interface, each tagged
    # with its own 'kind' - see cosim/interfaces/. Always non-empty: a clock
    # is required (it's the anchor the instance prefix is derived from).
    interfaces: list[Interface] = field(default_factory=list)
    type: str | None = None
    path: str | None = None
    name: str | None = None

    compat: str | None = None
    dts_path: str | None = None
    extra_files: list[Path] = field(default_factory=list)
    sync_quantum: int | None = None
    max_cycles: int | None = None
    extra_args: list[str] | None = None

    @property
    def top_name(self) -> str:
        return f"{self.name}_TOP"

    @property
    def ordered_interfaces(self) -> list[Interface]:
        """By kind (Interface.ORDER), not by declaration order - so a
        prefix-matched gpio can't shadow a bus just because it was listed
        first. Stable, so order *within* a kind stays the declaration's: bus
        order lines up with the dts node's reg windows and the QemuTLM index
        spaces, interrupt order with its interrupt cells and wire indices."""
        return sorted(self.interfaces, key=lambda i: i.ORDER)

    @property
    def clock(self) -> ClockInterface:
        return self._of(ClockInterface)[0]

    @property
    def reset(self) -> ResetInterface | None:
        resets = self._of(ResetInterface)
        return resets[0] if resets else None

    def _of(self, cls) -> list:
        return [i for i in self.interfaces if isinstance(i, cls)]

    @property
    def io_regex(self) -> str:
        """The cosim-extract --port regex, derived from every declared signal
        name - never hand-authored. clock/reset and any interrupt or gpio
        declared via 'name' are exact single-port matches; buses (always) and
        anything declared via 'prefix' expand to several leaf ports
        post-extraction (a TileLink bus's `_a_valid`/`_a_bits_opcode`/..., a
        bundled interrupt's `_sync_0..N` vector)."""
        return "|".join(p for i in self.ordered_interfaces for p in i.port_patterns())

    @staticmethod
    def load(root: Path, d: dict, *, require_type_path: bool = True) -> Component:
        """require_type_path=False is the top-level 'soc_rtl' declaration (the
        whole, un-extracted design) rather than a components[] entry: no
        type/path (nothing to extract), and only clock/reset interfaces plus
        no compat/dts_path - there's no QEMU bus/interrupt coupling path for
        the whole-design unit (build()'s QEMU-overlay detection, _gen_dtb, and
        _run_coupled all only ever look at components[])."""
        what = f"component {d.get('type')!r}" if require_type_path else "soc_rtl"
        if require_type_path:
            for key in ("type", "path"):
                if key not in d:
                    raise ValueError(f"cosim.json: component missing required field {key!r}: {d}")
        if "interfaces" not in d:
            raise ValueError(f"cosim.json: {what} missing required field 'interfaces'")
        if not isinstance(d["interfaces"], list):
            raise TypeError(f"cosim.json: {what}: 'interfaces' must be a list, got "
                             f"{d['interfaces']!r}")

        interfaces = [load_interface(i, what) for i in d["interfaces"]]

        clocks = [i for i in interfaces if isinstance(i, ClockInterface)]
        if len(clocks) < 1:
            raise ValueError(
                f"cosim.json: {what} needs at least one 'clock' interface (the first one "
                "declared is the anchor every other port's instance prefix is derived "
                "from) - found none")

        if require_type_path and any(i.NEEDS_QEMU for i in interfaces) \
                and not any(isinstance(i, ResetInterface) for i in interfaces):
            raise ValueError(
                f"cosim.json: {what} has bus/interrupt/gpio IO (which needs a QEMU "
                "remote-port reset line) but no 'reset' interface - declare one")

        if not require_type_path:
            bad = next((i for i in interfaces if not i.SOC_RTL_OK), None)
            if bad is not None:
                raise ValueError(
                    f"cosim.json: soc_rtl interface of kind {bad.KIND!r} isn't supported - "
                    "the whole design has no QEMU bus/interrupt coupling path. Declare it "
                    "as a components[] entry instead if you need bus/interrupt/gpio IO "
                    "- see cosim-gen-cli/README.md")
            unsupported = [key for key in ("compat", "dts_path") if key in d]
            if unsupported:
                raise ValueError(
                    f"cosim.json: soc_rtl.{unsupported[0]} isn't supported - the whole "
                    "design has no QEMU dts binding - see cosim-gen-cli/README.md")

        path = d.get("path", "")
        # Last hierarchy segment of the instance path is the real instance
        # name in the design (e.g. "topDesign/topMod/uart_0" -> "uart_0");
        # falls back to `type` if there's no '/' to split on. Not computed at
        # all for 'soc_rtl' (require_type_path=False) - it's never looked up
        # by name.
        default_name = path.rsplit("/", 1)[-1] if path else d.get("type")
        name = d.get("name", default_name) if require_type_path else None

        return Component(
            type=d.get("type"),
            path=path,
            name=name,
            interfaces=interfaces,
            compat=d.get("compat"),
            dts_path=d.get("dts_path"),
            extra_files=[_resolve(root, f) for f in d.get("extra_files", [])],
            sync_quantum=d.get("sync_quantum"),
            max_cycles=d.get("max_cycles"),
            extra_args=[str(a) for a in d["extra_args"]] if "extra_args" in d else None,
        )


@dataclass
class ToolchainConfig:
    firtool: str | None = None
    arcilator: str | None = None
    opt: str | None = None
    llc: str | None = None
    cosim_extract: str | None = None
    cosim_gen_opt: str | None = None
    cosim_plugin: str | None = None
    systemc: str | None = None
    systemc_include: str | None = None
    systemc_lib: str | None = None
    verilator: str | None = None
    dtc: str | None = None
    qemu: str | None = None

    @staticmethod
    def load(d: dict) -> ToolchainConfig:
        known = {f.name for f in ToolchainConfig.__dataclass_fields__.values()}
        unknown = set(d) - known
        if unknown:
            raise ValueError(f"cosim.json: unknown toolchain key(s): {sorted(unknown)}")
        return ToolchainConfig(**{k: d[k] for k in known if k in d})


@dataclass
class Config:
    root: Path
    design: DesignConfig
    qemu: QemuConfig
    # make -jN for every generated Makefile invocation (design lowering,
    # component extraction, systemctlm, link, dtb). None => os.cpu_count().
    jobs: str | None = None
    # Cycles between each sim binary's remote-port sync point with QEMU -
    # too low and QEMU spends most of its time context-switching to sync
    # rather than running; too high and device timing gets coarse. A
    # component's own sync_quantum overrides this for that component.
    sync_quantum: int = 1000
    # Stop each RTL model after this many clock cycles instead of running
    # forever; 0 = unbounded. A component's own max_cycles overrides this
    # for that component; `cosim run --cycles N` overrides both.
    max_cycles: int = 0
    # Extra argv strings appended to every spawned sim binary invocation,
    # after the positional sync_quantum/max_cycles slots - read by
    # verilator's plusargs scanning regardless of position, silently
    # ignored by arcilator. A component's own extra_args overrides this
    # for that component.
    extra_args: list = field(default_factory=list)
    # The whole, un-extracted design's own clock/reset/sync_quantum/
    # max_cycles/extra_args/extra_files declaration - None if not given (the
    # whole-design build then falls back to name-heuristic clock/reset
    # detection and plain top-level defaults, same as before this field
    # existed).
    soc_rtl: Component | None = None
    components: list[Component] = field(default_factory=list)
    toolchain: ToolchainConfig = field(default_factory=ToolchainConfig)
    # Absolute path to the cosim.json this was loaded from - the codegen make
    # recipe needs it to re-read the component declaration (--config), and it
    # may not be named "cosim.json" (a -C override).
    path: Path | None = None

    @staticmethod
    def load(path: Path) -> Config:
        path = Path(path).expanduser().resolve()
        with open(path) as f:
            d = json.load(f)

        root = path.parent
        cfg = Config(
            root=root,
            design=DesignConfig.load(root, d.get("design", {})),
            qemu=QemuConfig.load(root, d.get("qemu", {})),
            jobs=d.get("jobs"),
            sync_quantum=d.get("sync_quantum", 1000),
            max_cycles=d.get("max_cycles", 0),
            extra_args=[str(a) for a in d.get("extra_args", [])],
            soc_rtl=Component.load(root, d["soc_rtl"], require_type_path=False) if "soc_rtl" in d else None,
            components=[Component.load(root, c) for c in d.get("components", [])],
            toolchain=ToolchainConfig.load(d.get("toolchain", {})),
            path=path,
        )

        seen: dict[str, int] = {}
        for c in cfg.components:
            seen[c.name] = seen.get(c.name, 0) + 1
        dupes = sorted(name for name, count in seen.items() if count > 1)
        if dupes:
            raise ValueError(
                f"cosim.json: component name(s) collide: {dupes!r} - each component's "
                "name defaults to its 'path''s last segment; set an explicit 'name' on "
                "the colliding entries to disambiguate"
            )

        return cfg
