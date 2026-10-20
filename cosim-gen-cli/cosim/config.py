"""Load and validate a cosim.json project configuration."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import ClassVar

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


def _section(d: dict, key: str) -> dict:
    value = d.get(key, {})
    if not isinstance(value, dict):
        raise TypeError(f"cosim.json: {key} must be an object, got {value!r}")
    return value


def _int(d: dict, key: str, where: str) -> int:
    value = d[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"cosim.json: {where}: {key} must be an integer, got {value!r}")
    return value


def _bool(d: dict, key: str, where: str) -> bool:
    value = d[key]
    if not isinstance(value, bool):
        raise TypeError(f"cosim.json: {where}: {key} must be true or false, got {value!r}")
    return value


def _str_list(d: dict, key: str, where: str) -> list[str]:
    value = d[key]
    if not isinstance(value, list):
        raise TypeError(f"cosim.json: {where}: {key} must be a list, got {value!r}")
    return [str(v) for v in value]


@dataclass(kw_only=True)
class UnitSettings:
    """Settings of a built unit, set at the top level and overridable per
    component/soc_rtl. None means unset."""

    # Cycles between a sim's remote-port syncs.
    sync_quantum: int | None = None
    # Clock cycles before a sim stops, 0 = unbounded.
    max_cycles: int | None = None
    extra_args: list[str] | None = None
    trace: bool | None = None
    sysc_trace: bool | None = None
    coverage: bool | None = None
    cxxflags: list[str] | None = None
    ldlibs: list[str] | None = None
    verilator_args: list[str] | None = None
    arcilator_args: list[str] | None = None

    DEFAULTS: ClassVar[dict] = {
        "sync_quantum": 1000, "max_cycles": 0, "extra_args": [],
        "trace": False, "sysc_trace": False, "coverage": False,
        "cxxflags": [], "ldlibs": [], "verilator_args": [], "arcilator_args": [],
    }

    @staticmethod
    def _load_settings(d: dict, where: str) -> dict:
        parse = {int: _int, bool: _bool, list: _str_list}
        return {
            f.name: parse[type(UnitSettings.DEFAULTS[f.name])](d, f.name, where)
            for f in fields(UnitSettings) if f.name in d
        }

    def settings_for(self, comp: UnitSettings | None) -> dict:
        """Every setting, from `comp` where it sets one, else from self."""
        return {
            f.name: getattr(self, f.name) if comp is None or getattr(comp, f.name) is None
            else getattr(comp, f.name)
            for f in fields(UnitSettings)
        }


UNIT_SETTINGS = tuple(f.name for f in fields(UnitSettings))


@dataclass
class DesignConfig:
    input: Path
    # Only needed for the QEMU device tree.
    dts: Path | None = None
    seqmem: Path | None = None
    annotations: Path | None = None
    # Backends `cosim build` builds; `cosim run` defaults to the first.
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
        if not isinstance(backends, list):
            raise TypeError(
                f"cosim.json: design.supported_backends must be a list, got {backends!r}"
            )
        if not backends:
            raise ValueError(
                "cosim.json: design.supported_backends must be a non-empty list"
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
    # ELF files passed to QEMU via `-device loader`, in order.
    elfs: list[Path] = field(default_factory=list)
    extra_args: list = field(default_factory=list)
    # QEMU's -sync-quantum; None falls back to Config.sync_quantum.
    sync_quantum: int | None = None

    @staticmethod
    def load(root: Path, d: dict) -> QemuConfig:
        return QemuConfig(
            elfs=[_resolve(root, f) for f in d.get("elfs", [])],
            extra_args=[str(a) for a in d.get("extra_args", [])],
            sync_quantum=d.get("sync_quantum"),
        )


@dataclass(kw_only=True)
class Component(UnitSettings):
    # Always contains a clock, from which the instance prefix is derived.
    interfaces: list[Interface] = field(default_factory=list)
    type: str | None = None
    path: str | None = None
    name: str | None = None

    compat: str | None = None
    dts_path: str | None = None
    extra_files: list[Path] = field(default_factory=list)
    # The unit's sim.cpp is user-maintained and never generated.
    user_sim_cpp: bool = False

    @property
    def top_name(self) -> str:
        return f"{self.name}_TOP"

    @property
    def ordered_interfaces(self) -> list[Interface]:
        """Interfaces by Interface.ORDER, keeping declaration order within a kind."""
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
        """The cosim-extract --port regex of all declared interfaces."""
        return "|".join(p for i in self.ordered_interfaces for p in i.port_patterns())

    @staticmethod
    def load(root: Path, d: dict, *, require_type_path: bool = True) -> Component:
        """`require_type_path=False` loads the top-level 'soc_rtl' declaration: no
        type/path, only clock/reset interfaces, no compat/dts_path."""
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
            user_sim_cpp=_bool(d, "user_sim_cpp", what) if "user_sim_cpp" in d else False,
            **UnitSettings._load_settings(d, what),
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


@dataclass(kw_only=True)
class Config(UnitSettings):
    root: Path
    design: DesignConfig
    qemu: QemuConfig
    # make -j for every make call; None means os.cpu_count().
    jobs: str | None = None
    soc_rtl: Component | None = None
    components: list[Component] = field(default_factory=list)
    toolchain: ToolchainConfig = field(default_factory=ToolchainConfig)
    # The loaded cosim.json, which may have another name (-C).
    path: Path | None = None

    TOP_LEVEL_KEYS: ClassVar[tuple[str, ...]] = (
        "design", "qemu", "jobs", "soc_rtl", "components", "toolchain", *UNIT_SETTINGS,
    )

    @staticmethod
    def load(path: Path) -> Config:
        path = Path(path).expanduser().resolve()
        with open(path) as f:
            d = json.load(f)
        if not isinstance(d, dict):
            raise TypeError(
                f"cosim.json: top level must be a JSON object, "
                f"got {type(d).__name__}"
            )
        unknown = set(d) - set(Config.TOP_LEVEL_KEYS)
        if unknown:
            raise ValueError(
                f"cosim.json: unknown top-level key(s) {sorted(unknown)} - known: "
                f"{', '.join(Config.TOP_LEVEL_KEYS)}"
            )
        if "components" in d and not isinstance(d["components"], list):
            raise TypeError(
                f"cosim.json: components must be a list, got {d['components']!r}"
            )

        root = path.parent
        cfg = Config(
            root=root,
            design=DesignConfig.load(root, _section(d, "design")),
            qemu=QemuConfig.load(root, _section(d, "qemu")),
            jobs=d.get("jobs"),
            soc_rtl=Component.load(root, _section(d, "soc_rtl"), require_type_path=False) if "soc_rtl" in d else None,
            components=[Component.load(root, c) for c in d.get("components", [])],
            toolchain=ToolchainConfig.load(_section(d, "toolchain")),
            path=path,
            **(copy.deepcopy(UnitSettings.DEFAULTS) | UnitSettings._load_settings(d, "top level")),
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
