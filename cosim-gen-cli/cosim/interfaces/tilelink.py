"""TileLink: signal layout, TLM bridges, and bridge template arguments.

Everything TileLink-specific in cosim-gen lives here. The C++ side is
include/tilelink.h (the TLSignals struct), include/TLM2TLBridge.h (QEMU is
master) and include/TL2TLMBridge.h (the peripheral is master)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from ..statejson import StateType, short_type
from . import BusDir, BusSignal, flip_signals
from .bus import BusInterface

# The slave view: a TL slave receives the A channel and drives the D channel.
# Each entry's `names` are the accepted port suffixes, most-preferred first -
# FIRRTL emits either `_a_opcode` or `_a_bits_opcode` depending on how the
# bundle was flattened, and `names[0]` is the key the codegen looks it up by.
_TL_SLAVE_SIGNALS = [
    BusSignal(StateType.INPUT,  False, ["a_valid"]),
    BusSignal(StateType.INPUT,  False, ["a_opcode", "a_bits_opcode"]),
    BusSignal(StateType.INPUT,  True,  ["a_param", "a_bits_param"]),
    BusSignal(StateType.INPUT,  False, ["a_size", "a_bits_size"]),
    BusSignal(StateType.INPUT,  False, ["a_source", "a_bits_source"]),
    BusSignal(StateType.INPUT,  False, ["a_address", "a_bits_address"]),
    BusSignal(StateType.INPUT,  False, ["a_mask", "a_bits_mask"]),
    BusSignal(StateType.INPUT,  False, ["a_data", "a_bits_data"]),
    BusSignal(StateType.INPUT,  True,  ["a_corrupt", "a_bits_corrupt"]),
    BusSignal(StateType.INPUT,  False, ["d_ready"]),
    BusSignal(StateType.OUTPUT, False, ["a_ready"]),
    BusSignal(StateType.OUTPUT, False, ["d_valid"]),
    BusSignal(StateType.OUTPUT, False, ["d_opcode", "d_bits_opcode"]),
    BusSignal(StateType.OUTPUT, True,  ["d_param", "d_bits_param"]),
    BusSignal(StateType.OUTPUT, False, ["d_size", "d_bits_size"]),
    BusSignal(StateType.OUTPUT, False, ["d_source", "d_bits_source"]),
    BusSignal(StateType.OUTPUT, True,  ["d_sink", "d_bits_sink"]),
    BusSignal(StateType.OUTPUT, True,  ["d_denied", "d_bits_denied"]),
    BusSignal(StateType.OUTPUT, True,  ["d_data", "d_bits_data"]),
    BusSignal(StateType.OUTPUT, True,  ["d_corrupt", "d_bits_corrupt"]),
]


@dataclass
class TileLinkBus(BusInterface):
    KIND = "tilelink"

    SIGNALS: ClassVar[dict[BusDir, list[BusSignal]]] = {
        BusDir.SLAVE: _TL_SLAVE_SIGNALS,
        BusDir.MASTER: flip_signals(_TL_SLAVE_SIGNALS),
    }
    INCLUDES: ClassVar[list[str]] = ["tilelink.h", "TL2TLMBridge.h", "TLM2TLBridge.h"]
    BRIDGE_CLASS: ClassVar[dict[BusDir, str]] = {
        BusDir.SLAVE: "TLM2TLBridge", BusDir.MASTER: "TL2TLMBridge"}
    SOCKET_MEMBER: ClassVar[dict[BusDir, str]] = {
        BusDir.SLAVE: "targetsock", BusDir.MASTER: "socket"}
    SIGNAL_ACCESSOR: ClassVar[str] = "signals."

    # TLM2TLBridge/TL2TLMBridge's template parameters, in declaration order:
    # <bussize_t, addr_t, maskType_t, short_t, logSize_t, source_t, sink_t>
    _TEMPLATE_FIELDS: ClassVar[tuple] = ("a_data", "a_address", "a_mask", "a_opcode",
                                         "a_size", "a_source", "d_sink")

    def template_types(self) -> str:
        return "<" + ", ".join(short_type(self.io[f]) for f in self._TEMPLATE_FIELDS) + ">"
