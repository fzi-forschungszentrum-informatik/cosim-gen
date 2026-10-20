"""The abstract memory-mapped bus: leaf ports under one prefix, wired to QEMU
through a TLM bridge. A protocol subclass declares its signals and bridge."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import ClassVar

from ..statejson import StateInfo
from . import BusDir, BusSignal, Interface, PortMatcher, _reject_unknown_keys


@dataclass
class BusInterface(Interface):
    KIND, ORDER, NEEDS_QEMU = "", 2, True
    KEYS = ("prefix", "dir", "clock", "reset")

    # --- protocol description, supplied by the concrete subclass ---
    SIGNALS:         ClassVar[dict[BusDir, list[BusSignal]]] = {}
    INCLUDES:        ClassVar[list[str]] = []   # headers sim.cpp needs for the bridge
    BRIDGE_CLASS:    ClassVar[dict[BusDir, str]] = {}
    # The bridge member qemu.pub_mem_*[i] binds to.
    SOCKET_MEMBER:   ClassVar[dict[BusDir, str]] = {}
    # Prefix of the bridge's signal members, e.g. "signals." for TileLink.
    SIGNAL_ACCESSOR: ClassVar[str] = ""

    dir: BusDir = BusDir.SLAVE
    # The prefix as the extracted ports spell it; names the bridge member and dts label.
    port_prefix: str = ""
    io: dict[str, StateInfo] = field(default_factory=dict)
    # Clock/reset interface names; None means the first declared.
    clock: str | None = None
    reset: str | None = None

    @property
    def bridge_class(self) -> str:
        return self.BRIDGE_CLASS[self.dir]

    @property
    def socket_member(self) -> str:
        return self.SOCKET_MEMBER[self.dir]

    def template_types(self) -> str:
        """The bridge's template argument list, e.g. "<uint64_t, uint32_t, ...>"."""
        raise NotImplementedError

    def ctor_init(self, member: str, clock: str, reset: str) -> str:
        """The bridge's sim.cpp constructor init-list entry."""
        return f'{member}("{member}", {clock}, {reset})'

    @classmethod
    def load(cls, d: dict, where: str) -> BusInterface:
        if "name" in d:
            raise ValueError(
                f"cosim.json: {where}: bus {d['name']!r} uses 'name' - a bus bundle is "
                "always matched by its common port prefix, never a single exact name; "
                "use 'prefix' - see cosim-gen-cli/README.md")
        if "compat" in d or "path" in d or "interrupts" in d:
            raise ValueError(
                f"cosim.json: {where}: bus {d.get('prefix')!r} carries compat/path/"
                "interrupts - those live on the owning component ('compat'/'dts_path', "
                "and interrupt interfaces of their own) - see cosim-gen-cli/README.md")
        _reject_unknown_keys(cls, d, cls.KEYS, where)
        for key in ("prefix", "dir"):
            if key not in d:
                raise ValueError(
                    f"cosim.json: {where}: {cls.KIND} bus missing required field "
                    f"{key!r}: {d}")
        if d["dir"] not in ("slave", "master"):
            raise ValueError(
                f"cosim.json: bus {d['prefix']!r}.dir must be 'slave' or 'master', "
                f"got {d['dir']!r}")
        return cls(name=d["prefix"], dir=BusDir(d["dir"]),
                   clock=d.get("clock"), reset=d.get("reset"))

    def port_patterns(self) -> list[str]:
        return [f"{self.name}.*$"]

    def resolve(self, m: PortMatcher) -> BusInterface:
        prefix = m.resolve_prefix(self.name)
        io: dict[str, StateInfo] = {}
        for sig in self.SIGNALS[self.dir]:
            accepted = [f"{prefix}_{n}" for n in sig.names]
            hit = m.find_one(accepted, sig.typ)
            if hit is None:
                if not sig.optional:
                    raise ValueError(
                        f"bus {prefix!r} ({self.KIND}/{self.dir.value}): none of "
                        f"{accepted} found among the extracted ports - check the "
                        "component's 'path'/'interfaces' declaration")
                hit = StateInfo(accepted[-1], None, 0, sig.typ, None, None)
            io[sig.names[0]] = hit
        return replace(self, port_prefix=prefix, io=io,
                       ports=[s for s in io.values() if s.offset is not None])
