"""What a component's ports *are*, by who's on the other end of them.

One `interfaces` entry in cosim.json is one `Interface` subclass here, keyed by
its `kind`. A subclass owns both ends of its kind: how it's spelled in
cosim.json (`load`), what it contributes to the cosim-extract --port regex
(`port_patterns`), and which extracted ports it claims (`resolve`). Each kind
gets its own module - clock.py, reset.py, interrupt.py, gpio.py (both built on
the shared wire.py base), bus.py (abstract) + tilelink.py (concrete) - so
adding a kind (e.g. AXI) means adding one file, not editing this one. This
module holds only what every kind shares: the `Interface` base, the kind
registry, port-matching (`PortMatcher`), and the declaration-validation
helpers.

This sits below both config.py (which parses declarations) and codegen/ (which
emits from resolved ones), so neither has to import the other."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import ClassVar

from ..statejson import StateInfo, StateType, removeIo

# kind string -> Interface subclass. Populated by __init_subclass__, so adding
# a kind is adding a class - there is no second table to keep in sync.
INTERFACE_KINDS: dict[str, type[Interface]] = {}


class BusDir(Enum):
    SLAVE = "slave"
    MASTER = "master"


@dataclass
class BusSignal:
    """One wire of a bus protocol bundle. `names` are the accepted suffixes
    under the bus prefix, most-preferred first (FIRRTL emits either
    `_a_opcode` or `_a_bits_opcode` depending on how the bundle was flattened);
    `names[0]` is also the canonical key the codegen looks the signal up by."""
    typ: StateType
    optional: bool
    names: list[str]


def flip_signals(sig: list[BusSignal]) -> list[BusSignal]:
    """The same bundle seen from the other side: every input becomes an output
    and vice versa. A master port list is a slave's, flipped."""
    def flip(t: StateType) -> StateType:
        assert t in (StateType.INPUT, StateType.OUTPUT)
        return StateType.INPUT if t == StateType.OUTPUT else StateType.OUTPUT
    return [BusSignal(flip(s.typ), s.optional, s.names) for s in sig]


class PortMatcher:
    """Claims extracted ports for declared interfaces.

    cosim-extract's port-hoisting (HWPropPorts2TLM) keeps the original
    instance hierarchy as a literal "."-joined prefix on every extracted port
    ("uart_0.clock", or a deeper "topMod.dmx512_0.clock", trimmed to at most
    two segments) - it isn't stripped just because the module got renamed to
    "<type>_TOP", and its depth varies per peripheral. Declared names are the
    bare port name as it appears in the peripheral's own FIRRTL ("clock",
    "auto_control_xing_in"), so this strips the common instance prefix rather
    than making every cosim.json author repeat it. A bus/irq/gpio name's own
    internal leaf suffixes (an interrupt's "_sync_0..N", a bus's "_a_valid")
    are still "_"-joined, since those come from FIRRTL bundle flattening, not
    instance hoisting - only the instance-boundary separator is "."; ports
    that already have no instance prefix (a passthrough port lifted straight
    to the boundary, e.g. "uart0_txd") keep their full name.

    Matching never consumes; the caller consumes after a *successful* resolve,
    so a failed match leaves the pool untouched and can simply be skipped."""

    def __init__(self, io: list[StateInfo], anchor: str):
        self._io = list(io)
        self._prefix = self._derive_prefix(anchor)

    def _derive_prefix(self, anchor: str) -> str:
        """Derive the instance prefix from the one unambiguous anchor: the
        clock port is always "<prefix><clock name>", so whatever precedes the
        declared clock name on the actual clock port is the prefix every other
        real interface port carries too. Handles prefixes of any depth
        ("uart_0." vs "topMod.dmx512_0.") without guessing. The instance
        boundary is joined with "." (HWPropPorts2TLM's hoisting), but "_" is
        checked too since a passthrough/non-hoisted port may still carry an
        underscore-joined prefix - whichever separator the actual port uses
        wins, so callers never need to know which one applies."""
        if not anchor:
            return ""
        for io in self._io:
            if io.name == anchor:
                return ""
            for sep in (".", "_"):
                if io.name.endswith(sep + anchor):
                    return io.name[: -len(anchor)]  # keeps the trailing separator
        return ""

    def candidates(self, name: str) -> tuple:
        return (name, f"{self._prefix}{name}")

    def match(self, name: str, *, exact: bool) -> list[StateInfo]:
        """Ports for a declared name, tried both bare and under the common
        instance prefix. `exact` restricts to a single exactly-named port
        (clock/reset); otherwise a name is a prefix matching its leaf ports
        (an interrupt's `_sync_0..N`, a gpio bundle's `_pins_*`)."""
        for cand in self.candidates(name):
            hits = [io for io in self._io
                    if io.name == cand or (not exact and io.name.startswith(cand + "_"))]
            if hits:
                return hits
        raise ValueError(f"declared signal {name!r} not found among the extracted ports")

    def resolve_prefix(self, name: str) -> str:
        """The bus prefix as the extracted ports actually spell it - bare or
        instance-qualified, whichever some port carries."""
        return next((c for c in self.candidates(name)
                     if any(io.name.startswith(c + "_") for io in self._io)), name)

    def find_one(self, accepted: list[str], typ: StateType) -> StateInfo | None:
        return next((io for io in self._io if io.name in accepted and io.typ == typ), None)

    def consume(self, ports) -> None:
        self._io = removeIo(self._io, list(ports))

    @property
    def leftovers(self) -> list[StateInfo]:
        return self._io


def _one_of_prefix_or_name(cls, d: dict, where: str) -> tuple[str, bool]:
    """cosim.json spells a name-matched interface with 'name' and a
    prefix-matched one with 'prefix'; exactly one is required."""
    has_prefix, has_name = "prefix" in d, "name" in d
    if has_prefix == has_name:
        raise ValueError(
            f"cosim.json: {where}: interface of kind {cls.KIND!r} needs exactly one of "
            f"'prefix' or 'name': {d}")
    return (d["name"], True) if has_name else (d["prefix"], False)


def _require_name(cls, d: dict, where: str) -> str:
    # 'prefix' is deliberately absent from a name-only kind's KEYS (clock,
    # reset), so a declaration using it is already caught by
    # _reject_unknown_keys before this runs - a clock/reset is always a
    # single exact port, never a prefix, so there's no case to special-case.
    if "name" not in d:
        raise ValueError(f"cosim.json: {where}: {cls.KIND} interface missing 'name': {d}")
    return d["name"]


def _reject_unknown_keys(cls, d: dict, known: tuple, where: str) -> None:
    unknown = sorted(set(d) - {"kind"} - set(known))
    if unknown:
        raise ValueError(
            f"cosim.json: {where}: interface {d.get('name') or d.get('prefix')!r} "
            f"(kind {cls.KIND!r}) has unknown key(s) {unknown} - known: "
            f"kind, {', '.join(known)}")


@dataclass
class Interface:
    """One entry of a component's `interfaces` list.

    A declaration carries no ports; `resolve` returns a *new* instance with
    them filled in. It never populates in place, because project.py resolves
    the same Component against a model more than once per run (the build
    manifest, the dts overlay, and the run precheck each do), and because the
    resolved StateInfo objects are the model's own - shared, not copied, since
    codegen/main.py renames some of them after the fact."""

    KIND:       ClassVar[str]  = ""     # cosim.json "kind"; "" = abstract, unregistered
    # Regex/resolution priority. Emission is ordered by kind, not by declaration
    # order, so a prefix-matched gpio can't steal a bus's leaf ports just
    # because it was listed first; order *within* a kind is the declaration's
    # and is load-bearing (bus order <-> dts reg windows, interrupt order <->
    # dts interrupt cells and wire indices).
    ORDER:      ClassVar[int]  = 0
    EXACT:      ClassVar[bool] = False  # name is a whole port name, not a prefix
    NEEDS_QEMU: ClassVar[bool] = False  # talks to QEMU at all
    SOC_RTL_OK: ClassVar[bool] = False  # allowed on the top-level 'soc_rtl' decl
    KEYS:       ClassVar[tuple] = ("name",)

    name: str
    ports: list[StateInfo] = field(default_factory=list, repr=False, compare=False)

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        if cls.KIND:
            INTERFACE_KINDS[cls.KIND] = cls

    @classmethod
    def load(cls, d: dict, where: str) -> Interface:
        _reject_unknown_keys(cls, d, cls.KEYS, where)
        return cls(name=_require_name(cls, d, where))

    def port_patterns(self) -> list[str]:
        """This interface's contribution to the cosim-extract --port regex."""
        return [f"{self.name}$" if self.EXACT else f"{self.name}.*$"]

    def resolve(self, m: PortMatcher) -> Interface:
        return replace(self, ports=m.match(self.name, exact=self.EXACT))


# Each import below both registers its kind(s) into INTERFACE_KINDS (via
# Interface.__init_subclass__) and re-exports the class, so `from ..interfaces
# import *` (config.py, codegen/typedio.py) keeps seeing every concrete kind
# without listing them here by hand.
from .clock import ClockInterface  # noqa: E402 - after Interface, which they subclass
from .reset import ResetInterface  # noqa: E402
from .wire import _WireInterface  # noqa: E402
from .interrupt import IrqInterface  # noqa: E402
from .gpio import GpioInterface  # noqa: E402
from .bus import BusInterface
from .tilelink import TileLinkBus  # noqa: E402,F401 - imported for its registration


def known_kinds() -> str:
    return ", ".join(sorted(INTERFACE_KINDS))


def bus_kinds() -> list[type[BusInterface]]:
    return [c for c in INTERFACE_KINDS.values() if issubclass(c, BusInterface)]


def load_interface(d, where: str) -> Interface:
    """One `interfaces` entry -> its Interface subclass, by 'kind'."""
    if not isinstance(d, dict):
        raise TypeError(f"cosim.json: {where}: every 'interfaces' entry must be an "
                         f"object, got {d!r}")
    kind = d.get("kind")
    if not isinstance(kind, str) or not kind:
        raise TypeError(f"cosim.json: {where}: every 'interfaces' entry needs a "
                         f"'kind': {d}")
    if kind == "bus":
        buses = ", ".join(sorted(c.KIND for c in bus_kinds()))
        raise ValueError(
            f"cosim.json: {where}: 'bus' isn't a kind on its own - use the protocol as "
            f'the kind, e.g. {{ "kind": "tilelink", "prefix": ..., "dir": ... }}. '
            f"Known bus kinds: {buses}")
    cls = INTERFACE_KINDS.get(kind)
    if cls is None:
        raise TypeError(f"cosim.json: {where}: unknown interface kind {kind!r} - "
                         f"known: {known_kinds()}")
    return cls.load(d, where)
