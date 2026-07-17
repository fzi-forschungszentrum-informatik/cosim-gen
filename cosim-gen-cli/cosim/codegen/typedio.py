#!/usr/bin/env python3
"""Classify a model's extracted ports into typed IO, either from a cosim.json
`interfaces` declaration or - with no declaration - by guessing from name
patterns and feeding the guesses through the same resolve path.

Backend-agnostic: both the arcilator and verilator paths render sim.cpp from
the TypedIO built here. `from .typedio import *` also re-exports statejson's
and interfaces' names, which the rest of codegen/ relies on."""
from dataclasses import dataclass, field
from typing import *

from ..statejson import *      # noqa: F401,F403 - re-exported for `from .typedio import *`
from ..interfaces import *     # noqa: F401,F403
from ..interfaces.bus import BusInterface
from ..interfaces.tilelink import TileLinkBus


@dataclass
class TypedIO:
    """A resolved component's IO: one flat list of interfaces that claimed
    ports, plus whatever they left over.

    The kind buckets below are views, not storage - the interfaces are the
    storage. `other` is what cosim-extract kept as plain passthrough ports
    because nothing in the component's io_regex matched them (a uart's
    txd/rxd): they need no declaration, they're connection points for a
    user-supplied SystemC model, not something this tool wires to QEMU."""

    interfaces: List[Interface]
    other: List[StateInfo]

    def _of(self, cls) -> list:
        return [i for i in self.interfaces if isinstance(i, cls)]

    def _ports(self, cls) -> List[StateInfo]:
        return [p for i in self._of(cls) for p in i.ports]

    @property
    def clock_ifaces(self) -> List[ClockInterface]: return self._of(ClockInterface)
    @property
    def reset_ifaces(self) -> List[ResetInterface]: return self._of(ResetInterface)

    @property
    def clocks(self) -> List[StateInfo]: return self._ports(ClockInterface)
    @property
    def resets(self) -> List[StateInfo]: return self._ports(ResetInterface)
    @property
    def intrs(self) -> List[StateInfo]:  return self._ports(IrqInterface)
    @property
    def gpio(self) -> List[StateInfo]:   return self._ports(GpioInterface)
    @property
    def bus(self) -> List[BusInterface]: return self._of(BusInterface)

    def getSignals(self, clock=False, buses=False):
        r = []
        if clock:
            # Copy, not alias - `r += ...` below is an in-place list.__iadd__
            # and would otherwise mutate the freshly-built clocks list only by
            # accident; keep it explicit.
            r = list(self.clocks)
        r += self.resets + self.intrs + self.gpio + self.other
        if buses:
            r += [k for b in self.bus for k in b.io.values()]
        return r

    @property
    def needs_qemu(self) -> bool:
        """Whether this component has any IO that talks to QEMU at all -
        buses, interrupts (either direction), or gpio. A component with none
        of these (e.g. a plain register/ALU) can only ever run standalone in
        `rtl` mode - there's nothing for QEMU to couple to."""
        return any(i.NEEDS_QEMU for i in self.interfaces)


@dataclass
class ModelInfo:
    name: str
    numStateBytes: int
    initialFnSym: str
    states: List[StateInfo]
    io: List[StateInfo]
    typedIO: TypedIO
    hierarchy: List[StateHierarchy]

    def decode(d: dict) -> "ModelInfo":
        return ModelInfo(
            d["name"],
            d["numStateBytes"],
            d.get("initialFnSym", ""),
            [StateInfo.decode(d) for d in d["states"]],
            [],
            [],
            [],
        )


def resolve_interfaces(ifaces: List[Interface], matcher: PortMatcher,
                       *, strict: bool = True) -> TypedIO:
    """Claim ports for each interface, in kind order (see Interface.ORDER).

    strict=True (a cosim.json declaration): an interface that can't be
    resolved is a config error. strict=False (the name-guessing fallback): a
    candidate that doesn't pan out simply isn't an interface, and its ports
    stay in the passthrough pool. resolve() consumes nothing itself, so a
    failed attempt is atomic and can just be skipped."""
    resolved = []
    for iface in sorted(ifaces, key=lambda i: i.ORDER):
        try:
            r = iface.resolve(matcher)
        except ValueError:
            if strict:
                raise
            continue
        # A bus consumes its optional-signal placeholders too, which aren't in
        # .ports (they matched no real port).
        matcher.consume(r.io.values() if isinstance(r, BusInterface) else r.ports)
        resolved.append(r)
    return TypedIO(resolved, matcher.leftovers)


def build_typedIO(decl, ioIn: List[StateInfo]) -> TypedIO:
    """Classify extracted ports from the cosim.json component *declaration*."""
    return resolve_interfaces(decl.interfaces,
                              PortMatcher(ioIn, decl.clock.name), strict=True)


def infer_interfaces(io: List[StateInfo]) -> List[Interface]:
    """No cosim.json declaration to classify from (the whole design with no
    'soc_rtl'): guess interfaces from name patterns, to be fed through the
    exact same resolve path a declaration takes.

    Guesses come off a shrinking pool so the precedence matches the order
    below - a port already claimed as a clock can't also look like an
    interrupt."""
    CLOCK_NAMES = ("clock", "clk")
    RESET_NAMES = ("reset", "rst")

    rest = list(io)

    def claim(pred, make) -> List[Interface]:
        nonlocal rest
        hits = [s for s in rest if pred(s)]
        rest = removeIo(rest, hits)
        return [make(s) for s in hits]

    ifaces = claim(lambda s: s.name.endswith(CLOCK_NAMES),
                   lambda s: ClockInterface(name=s.name))
    assert ifaces, "design needs a clock"
    ifaces += claim(lambda s: s.name.endswith(RESET_NAMES),
                    lambda s: ResetInterface(name=s.name))
    ifaces += claim(lambda s: "_int_" in s.name,
                    lambda s: IrqInterface(
                        name=s.name, exact=True,
                        dir="out" if s.typ == StateType.OUTPUT else "in"))

    # One candidate per (bus class, direction, anchor port). Master before
    # slave, matching the historical SUPPORTED_BUSSES order - bus list order
    # drives the QemuTLM index spaces. A candidate that doesn't resolve is
    # dropped by resolve_interfaces(strict=False).
    for cls in bus_kinds():
        for dir in (BusDir.MASTER, BusDir.SLAVE):
            anchor = cls.SIGNALS[dir][0]
            assert not anchor.optional
            for suffix in anchor.names:
                for s in rest:
                    if s.name.endswith("_" + suffix) and s.typ == anchor.typ:
                        ifaces.append(cls(name=s.name.removesuffix("_" + suffix), dir=dir))
    return ifaces


def infer_typedIO(ioIn: List[StateInfo]) -> TypedIO:
    io = resolve_interfaces(infer_interfaces(ioIn), PortMatcher(ioIn, ""), strict=False)

    signalF = {
        "clocks": [s.name for s in io.clocks],
        "resets": [s.name for s in io.resets],
        "interrupts": [s.name for s in io.intrs],
        "buses": [f"{b.port_prefix} : {b.KIND.upper()}-{b.dir.name}" for b in io.bus],
        "other signals": [s.name for s in io.other],
    }

    print("  Infered Top Level IO:")
    for key, value in signalF.items():
        listed = "\n".join("      - " + s for s in value)
        print(f"    {key}:\n{listed}")

    return io
