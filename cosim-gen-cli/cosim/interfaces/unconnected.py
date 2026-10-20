"""The unconnected interface: keep a port at the extraction boundary, but
wire it to nothing."""

from __future__ import annotations

from dataclasses import dataclass, replace

from . import Interface, PortMatcher


@dataclass
class UnconnectedInterface(Interface):
    KIND, ORDER, EXACT = "unconnected", 5, True

    def resolve(self, m: PortMatcher) -> UnconnectedInterface:
        """Fails if the port is missing; claims nothing, so it stays a passthrough."""
        m.match(self.name, exact=True)
        return replace(self, ports=[])
