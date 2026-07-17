"""The interrupt interface: wired to QEMU as a remote-port wire and routed to
the PLIC - see codegen/dts_overlay.py for how its resolved port count is
matched against the component's dts node's own `interrupts` cells."""

from __future__ import annotations

from dataclasses import dataclass

from .wire import _WireInterface


@dataclass
class IrqInterface(_WireInterface):
    """Wired to QEMU as a remote-port wire and routed to the PLIC: the
    interrupt cells are matched positionally against the component's dts
    node's own `interrupts` property, whose count must match."""
    KIND, ORDER = "interrupt", 3
