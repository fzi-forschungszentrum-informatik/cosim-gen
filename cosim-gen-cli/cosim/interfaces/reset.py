"""The reset interface: a single exact port, drives the generated sim.cpp's
startup reset sequence (active-high or active-low)."""

from __future__ import annotations

from dataclasses import dataclass

from . import Interface, _reject_unknown_keys, _require_name


@dataclass
class ResetInterface(Interface):
    KIND, ORDER, EXACT, SOC_RTL_OK = "reset", 1, True, True
    KEYS = ("name", "active_low")

    # False (the default) = active-high, matches historical behavior. Drives
    # the generated sim.cpp's startup reset sequence.
    active_low: bool = False

    @classmethod
    def load(cls, d: dict, where: str) -> ResetInterface:
        _reject_unknown_keys(cls, d, cls.KEYS, where)
        return cls(name=_require_name(cls, d, where),
                   active_low=bool(d.get("active_low", False)))
