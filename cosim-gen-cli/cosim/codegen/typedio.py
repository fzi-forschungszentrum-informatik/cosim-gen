#!/usr/bin/env python3
"""Classifies a model's extracted ports into typed IO, from a cosim.json
declaration or by name patterns."""
from dataclasses import dataclass
from typing import *

from ..interfaces import *
from ..interfaces.bus import BusInterface
from ..statejson import *


@dataclass
class TypedIO:
    """A resolved component's IO: the interfaces that claimed ports, and the
    leftover passthrough ports (`other`)."""

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
            r = list(self.clocks)
        r += self.resets + self.intrs + self.gpio + self.other
        if buses:
            r += [k for b in self.bus for k in b.io.values()]
        return r

    @property
    def needs_qemu(self) -> bool:
        """Whether any interface talks to QEMU (bus, interrupt or gpio)."""
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
    """Claims ports for each interface in Interface.ORDER. With `strict`, an
    unresolvable interface raises; otherwise it is skipped."""
    resolved = []
    for iface in sorted(ifaces, key=lambda i: i.ORDER):
        try:
            r = iface.resolve(matcher)
        except ValueError:
            if strict:
                raise
            continue
        # A bus also consumes the placeholders of its absent optional signals.
        matcher.consume(r.io.values() if isinstance(r, BusInterface) else r.ports)
        resolved.append(r)
    return TypedIO(resolved, matcher.leftovers)


def build_typedIO(decl, ioIn: List[StateInfo]) -> TypedIO:
    return resolve_interfaces(decl.interfaces,
                              PortMatcher(ioIn, decl.clock.name), strict=True)


def infer_interfaces(io: List[StateInfo]) -> List[Interface]:
    """Interfaces guessed from port names; a port claimed by one guess isn't
    offered to the next."""
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

    # One candidate per bus kind, direction and anchor port; master first, since
    # bus order sets the QemuTLM indices.
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
