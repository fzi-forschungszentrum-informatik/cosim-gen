"""The gpio interface: also a remote-port wire, but not interrupt-routed -
external I/O, not a PLIC source."""

from __future__ import annotations

from dataclasses import dataclass

from .wire import _WireInterface


@dataclass
class GpioInterface(_WireInterface):
    """Also a remote-port wire, but *not* interrupt-routed - external I/O
    rather than a PLIC source, so it contributes no dts interrupt cells."""
    KIND, ORDER = "gpio", 4
