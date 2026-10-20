"""Derives cosim.json's components from a design's diplomacy config. With a dts,
each component also gets the dts_path of the node its first bus address matches."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from .codegen.dts_overlay import parseDts
from .config import ToolchainConfig
from .interfaces import bus_kinds
from .toolchain import resolve

_SUPPORTED_DIPLOMACY_TAGS = {
    "Reset", "Clock", "AXIBus", "TLBus", "IntrRecv", "IntrDriver", "ClockGroup",
}

# Base address in a diplomacy "AddressMap", e.g. "List(AddressSet(0x64000000, 0xfff))".
_ADDRESS_SET_RE = re.compile(r"AddressSet\(0x([0-9a-fA-F]+)")


class _Port:
    def __init__(self, name: str, config: dict):
        self.name = name
        self.dir = config["dir"]
        if self.dir == "BundleDefault":
            self.dir = "Output"
        elif self.dir == "BundleFlipped":
            self.dir = "Input"
        self.type = config["type"]
        self.config = config.get("config", {})
        self.children = [_Port(n, c) for n, c in config.get("children", {}).items()]

    def get_leafs(self, with_config: bool = True) -> list[_Port]:
        if (with_config and self.config) or not self.children:
            return [self]
        leafs = []
        for child in self.children:
            leafs.extend(child.get_leafs(with_config))
        return leafs

    def is_supported(self) -> bool:
        return bool(
            (set(self.config.keys()) & _SUPPORTED_DIPLOMACY_TAGS)
            or ("TraceBundle" in self.config and self.dir == "Output")
            or self.name == "auto.trace_aux_in"
            or self.name == "io.rtcTick"
        )

    def clean_name(self) -> str:
        return self.name.replace(".", "_")


class _ModIO:
    def __init__(self, name: str, config: dict):
        self.name = name
        self.typ = config["type"]
        self.labels = config["labels"]
        self.ports = [_Port(n, v) for n, v in config["signals"].items()]

    def get_leafs(self) -> list[_Port]:
        leafs = []
        for port in self.ports:
            leafs.extend(port.get_leafs())
        return leafs


def _bus_address(config: dict) -> int | None:
    """First base address of a leaf's TLBus/AXIBus "AddressMap", if any."""
    for key in ("TLBus", "AXIBus"):
        bus_cfg = config.get(key)
        if isinstance(bus_cfg, dict):
            match = _ADDRESS_SET_RE.search(bus_cfg.get("AddressMap", ""))
            if match:
                return int(match.group(1), 16)
    return None


def _dts_address_index(dts_path: Path) -> dict[int, object]:
    # No cosim.json here: resolve dtc like `cosim doctor` (DTC env var, then $PATH).
    dtc = resolve(ToolchainConfig())["dtc"] or "dtc"
    tree = parseDts(str(dts_path), dtc)
    index = {}
    for node in tree.all_nodes():
        reg = list(node.get_reg() or [])
        if reg:
            index[reg[0][0]] = node
    return index


def _component_dts_path(bus_leafs: list[_Port], addr_index: dict) -> str | None:
    """Path of the dts node at the first matching bus address, or None."""
    for leaf in bus_leafs:
        addr = _bus_address(leaf.config)
        if addr is None:
            continue
        node = addr_index.get(addr)
        if node is not None:
            return node.get_path()
    return None


# Only TileLink has a codegen kind; AXI buses are noted, not declared.
_BUS_LEAF_KIND = {"TLBus": "tilelink"}


def _classify_component(
    mod: _ModIO, supported: list[_Port], addr_index: dict | None = None
) -> tuple[dict, list[str], list[str]]:
    """(component, notes, unmapped) for a labeled module; `addr_index` adds dts_path."""
    notes = []
    unmapped = []
    interfaces = []

    clock_leaf = next((leaf for leaf in supported if "Clock" in leaf.config), None)
    # Diplomacy has no clock frequency; left null so loading fails until it's set.
    interfaces.append({"kind": "clock", "name": clock_leaf.clean_name() if clock_leaf else "clock", "freq_mhz": None})
    notes.append(f"{mod.typ}: freq_mhz left null - fill in this clock's actual frequency")
    if clock_leaf is None:
        notes.append(f"{mod.typ}: no Clock-tagged leaf found, defaulting clock name to 'clock'")

    reset_leaf = next((leaf for leaf in supported if "Reset" in leaf.config), None)
    interfaces.append({"kind": "reset", "name": reset_leaf.clean_name() if reset_leaf else "reset"})
    if reset_leaf is None:
        notes.append(f"{mod.typ}: no Reset-tagged leaf found, defaulting reset name to 'reset'")

    bus_leafs = []
    for leaf in supported:
        for key, kind in _BUS_LEAF_KIND.items():
            if key in leaf.config:
                interfaces.append({
                    "kind": kind, "prefix": leaf.clean_name(),
                    "dir": "slave" if leaf.dir == "Input" else "master",
                })
                bus_leafs.append(leaf)
        if "AXIBus" in leaf.config:
            notes.append(f"{mod.typ}.{leaf.clean_name()}: AXI bus found but no AXI codegen kind yet - not declared")

    for leaf in supported:
        # 'prefix': a leaf may expand into several ports.
        if "IntrDriver" in leaf.config and leaf.dir == "Output":
            interfaces.append({"kind": "interrupt", "prefix": leaf.clean_name(), "dir": "out"})
        elif "IntrRecv" in leaf.config:
            interfaces.append({"kind": "interrupt", "prefix": leaf.clean_name(), "dir": "in"})
    # Diplomacy has no gpio-pin interface type to detect - left for hand-editing.

    component = {"type": mod.typ, "path": "/".join(mod.name.split(".")[1:]),
                 "interfaces": interfaces}
    if addr_index is not None and bus_leafs:
        dts_path = _component_dts_path(bus_leafs, addr_index)
        if dts_path is not None:
            component["dts_path"] = dts_path
        else:
            addrs = [hex(a) for a in (_bus_address(leaf.config) for leaf in bus_leafs) if a is not None]
            if addrs:
                unmapped.append(f"{mod.typ} (addr={', '.join(addrs)}): no dts node at that address")
    return component, notes, unmapped


def _components_from_diplomacy(
    diplomacy_path: Path, dts_path: Path | None = None
) -> tuple[list[dict], list[str], list[str]]:
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    with open(diplomacy_path) as f:
        yaml_config = yaml.load(f, Loader=loader)

    addr_index = _dts_address_index(dts_path) if dts_path else None

    mods = [_ModIO(name, cfg) for name, cfg in yaml_config.items()]
    components = []
    unmapped = []
    notes = []
    for mod in mods:
        if not mod.labels:
            continue
        supported = [leaf for leaf in mod.get_leafs() if leaf.is_supported()]
        if not supported:
            continue
        component, component_notes, component_unmapped = _classify_component(mod, supported, addr_index)
        components.append(component)
        notes.extend(component_notes)
        unmapped.extend(component_unmapped)
    return components, unmapped, notes


def gen_config(diplomacy_path: Path, output_path: Path, dts_path: Path | None = None) -> int:
    components, unmapped, notes = _components_from_diplomacy(diplomacy_path, dts_path)
    if not components:
        print(f"No labeled modules found in {diplomacy_path}")
        return 1

    if output_path.exists():
        existing = json.loads(output_path.read_text())
    else:
        existing = {
            "design": {"input": "", "dts": "", "supported_backends": ["arcilator"]},
        }
    existing["components"] = components

    if dts_path is not None:
        bus_kind_names = {c.KIND for c in bus_kinds()}
        n_mapped = sum(1 for c in components if "dts_path" in c)
        n_bus_components = sum(
            1 for c in components
            if any(i["kind"] in bus_kind_names for i in c["interfaces"])
        )
        print(f"Derived dts mapping for {n_mapped}/{n_bus_components} bus-bearing component(s)")
        if unmapped:
            print(f"{len(unmapped)} component(s) had no dts address match:")
            for u in unmapped:
                print(f"  - {u}")

    output_path.write_text(json.dumps(existing, indent=2) + "\n")

    from .config import Config
    _EXPECTED_GAPS = ("missing required 'freq_mhz'", "design.input must be a non-empty path")
    try:
        Config.load(output_path)
    except ValueError as e:
        if not any(gap in str(e) for gap in _EXPECTED_GAPS):
            print(f"Wrote {output_path}, but it doesn't parse back: {e}")
            return 1

    print(f"Found {len(components)} labeled module(s):")
    for c in components:
        print(f"  {c['type']:<24} path={c['path']}")
    if notes:
        print(f"{len(notes)} classification note(s):")
        for n in notes:
            print(f"  - {n}")
    print(f"Wrote {output_path}")
    return 0
