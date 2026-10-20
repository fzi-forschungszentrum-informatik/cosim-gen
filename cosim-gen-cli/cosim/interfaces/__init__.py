"""Interface kinds: how a cosim.json `interfaces` entry is loaded (`load`), which
ports it extracts (`port_patterns`) and which extracted ports it claims (`resolve`).
Each kind lives in its own module."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import ClassVar

from ..statejson import StateInfo, StateType, removeIo

# Filled by Interface.__init_subclass__.
INTERFACE_KINDS: dict[str, type[Interface]] = {}


class BusDir(Enum):
    SLAVE = "slave"
    MASTER = "master"


@dataclass
class BusSignal:
    """One wire of a bus bundle. `names` are the accepted suffixes under the bus
    prefix, most preferred first; `names[0]` is the codegen's key for it."""
    typ: StateType
    optional: bool
    names: list[str]


def flip_signals(sig: list[BusSignal]) -> list[BusSignal]:
    """The bundle seen from the other side: inputs and outputs swapped."""
    def flip(t: StateType) -> StateType:
        assert t in (StateType.INPUT, StateType.OUTPUT)
        return StateType.INPUT if t == StateType.OUTPUT else StateType.OUTPUT
    return [BusSignal(flip(s.typ), s.optional, s.names) for s in sig]


class PortMatcher:
    """Claims extracted ports for declared interfaces.

    Declared names are bare port names; extracted ports may carry an instance prefix
    ("uart_0.clock"), which is derived from the clock and tried as well. Matching
    never consumes; callers consume after a successful resolve."""

    def __init__(self, io: list[StateInfo], anchor: str):
        self._io = list(io)
        self._prefix = self._derive_prefix(anchor)

    def _derive_prefix(self, anchor: str) -> str:
        """The instance prefix in front of `anchor` (the clock name) on its port, with
        its "." or "_" separator; "" if there is none."""
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
        """Ports for a declared name, bare or under the instance prefix. `exact` matches
        one whole port name; otherwise the name is a prefix of its leaf ports."""
        for cand in self.candidates(name):
            hits = [io for io in self._io
                    if io.name == cand or (not exact and io.name.startswith(cand + "_"))]
            if hits:
                return hits
        raise ValueError(f"declared signal {name!r} not found among the extracted ports")

    def resolve_prefix(self, name: str) -> str:
        """The bus prefix as the extracted ports spell it."""
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
    """(value, is_name) from exactly one of 'name' or 'prefix'."""
    has_prefix, has_name = "prefix" in d, "name" in d
    if has_prefix == has_name:
        raise ValueError(
            f"cosim.json: {where}: interface of kind {cls.KIND!r} needs exactly one of "
            f"'prefix' or 'name': {d}")
    return (d["name"], True) if has_name else (d["prefix"], False)


def _require_name(cls, d: dict, where: str) -> str:
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
    """One entry of a component's `interfaces` list. `resolve` returns a new instance
    with `ports` filled in."""

    KIND:       ClassVar[str]  = ""     # cosim.json "kind"; "" = abstract, unregistered
    # Resolution order across kinds; within a kind, declaration order is kept.
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


# Registers every kind and re-exports it; `X as X` marks the re-export for ruff.
from .bus import BusInterface
from .clock import ClockInterface as ClockInterface
from .gpio import GpioInterface as GpioInterface
from .interrupt import IrqInterface as IrqInterface
from .reset import ResetInterface as ResetInterface
from .tilelink import TileLinkBus as TileLinkBus
from .unconnected import UnconnectedInterface as UnconnectedInterface
from .wire import _WireInterface as _WireInterface


def known_kinds() -> str:
    return ", ".join(sorted(INTERFACE_KINDS))


def bus_kinds() -> list[type[BusInterface]]:
    return [c for c in INTERFACE_KINDS.values() if issubclass(c, BusInterface)]


def load_interface(d, where: str) -> Interface:
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
