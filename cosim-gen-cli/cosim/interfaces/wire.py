"""Shared base for the interface kinds that become plain remote-port wires
(interrupt, gpio) rather than a bus bundle or a single clock/reset port."""

from __future__ import annotations

from dataclasses import dataclass, replace

from . import Interface, PortMatcher, _one_of_prefix_or_name, _reject_unknown_keys


@dataclass
class _WireInterface(Interface):
    """Declared either as an exact 'name' or as a 'prefix' matching its own
    port plus any leaf ports under it (a bundled `_sync_0..N` vector, a gpio
    `_pins_*`)."""

    NEEDS_QEMU = True
    KEYS = ("name", "prefix", "dir")

    dir: str = "out"
    exact: bool = False

    @classmethod
    def load(cls, d: dict, where: str) -> _WireInterface:
        _reject_unknown_keys(cls, d, cls.KEYS, where)
        name, exact = _one_of_prefix_or_name(cls, d, where)
        dir_ = d.get("dir", "out")
        if dir_ not in ("out", "in"):
            raise ValueError(
                f"cosim.json: {cls.KIND} {name!r}.dir must be 'out' or 'in', got {dir_!r}")
        return cls(name=name, dir=dir_, exact=exact)

    def port_patterns(self) -> list[str]:
        return [f"{self.name}{'$' if self.exact else '.*$'}"]

    def resolve(self, m: PortMatcher) -> _WireInterface:
        return replace(self, ports=m.match(self.name, exact=self.exact))
