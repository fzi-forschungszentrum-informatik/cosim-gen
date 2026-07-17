"""The clock interface: a single exact port, and the anchor every other
declared port's instance prefix is derived from (see PortMatcher)."""

from __future__ import annotations

from dataclasses import dataclass

from . import Interface, _reject_unknown_keys, _require_name


@dataclass
class ClockInterface(Interface):
    KIND, ORDER, EXACT, SOC_RTL_OK = "clock", 0, True, True
    KEYS = ("name", "freq_mhz")

    freq_mhz: int = 0  # always set by load() below - no project-wide fallback

    @classmethod
    def load(cls, d: dict, where: str) -> ClockInterface:
        _reject_unknown_keys(cls, d, cls.KEYS, where)
        freq = d.get("freq_mhz")
        if freq is None:
            raise ValueError(
                f"cosim.json: {where}: clock {d.get('name')!r} is missing required "
                f"'freq_mhz' - every clock must declare its own, there's no project-wide "
                f"default")
        if not isinstance(freq, int):
            raise ValueError(
                f"cosim.json: {where}: clock {d.get('name')!r} freq_mhz must be an "
                f"integer, got {freq!r}")
        return cls(name=_require_name(cls, d, where), freq_mhz=freq)
