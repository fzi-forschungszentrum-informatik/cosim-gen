#!/usr/bin/env python3
"""Renders sim.cpp: sc_main and the Top module that wires one component's model
to its clocks, resets, TLM bridges and QEMU remote-port channel, for either
backend."""
from dataclasses import dataclass, field

from .format import *
from .jinja import env
from .typedio import *


@dataclass
class _BusView:
    bus: BusInterface
    member: str          # declared sim.cpp signal name, e.g. "tluart_top_auto_control_xing_in"
    qemu_array: str      # "pub_mem_master" (bus.dir == SLAVE) | "pub_mem_slave" (MASTER)
    qemu_index: int

    @property
    def bridge_class(self) -> str: return self.bus.bridge_class
    @property
    def template_types(self) -> str: return self.bus.template_types()
    @property
    def socket_member(self) -> str: return self.bus.socket_member
    @property
    def signal_accessor(self) -> str: return self.bus.SIGNAL_ACCESSOR


def _plan_buses(buses: list[BusInterface], inst: str) -> list[_BusView]:
    views = []
    next_index = {BusDir.SLAVE: 0, BusDir.MASTER: 0}
    for bus in buses:
        idx = next_index[bus.dir]
        next_index[bus.dir] += 1
        views.append(_BusView(
            bus=bus,
            member=f"{inst}_{bus.port_prefix}",
            qemu_array="pub_mem_master" if bus.dir == BusDir.SLAVE else "pub_mem_slave",
            qemu_index=idx,
        ))
    return views


@dataclass
class _RenderCtx:
    model: "ModelInfo"
    top_module: str
    inst: str            # SystemC instance/signal-name prefix for this component
    wrapper_path: str     # arcilator only; "" for verilator
    # Backs CLOCK_MHZ, used only to scale max_cycles; each clock has its own period.
    anchor_freq_mhz: int
    # Reset hold time in us: 1000 periods of the slowest clock.
    reset_hold_us: float
    buses: list[_BusView]
    num_slave_buses: int
    num_master_buses: int
    wire_out: list[StateInfo]  # interrupt/gpio OUTPUT signals -> qemu.wire_in[]
    wire_in: list[StateInfo]   # interrupt/gpio INPUT signals  -> qemu.wire_out[]
    protocol_includes: list[str]  # headers pulled in by every bus's own bridge
    # Reset driven by QEMU's TLM reset line: the first bus's, else the first declared.
    qemu_reset_name: str = ""
    init_entries: list[str] = field(default_factory=list)
    # extra_srcs' cosim_user_wire() connects the undeclared ports.
    user_wired: bool = False

    @property
    def needs_qemu(self) -> bool:
        return self.model.typedIO.needs_qemu

    @property
    def undriven_inputs(self) -> list[StateInfo]:
        return [sig for sig in self.model.typedIO.other if sig.typ == StateType.INPUT]


def _build_ctx(wrapper_path: str, model: "ModelInfo", top_module: str, user_wired: bool) -> _RenderCtx:
    top_module = top_module or model.name
    inst = top_module.lower()
    io = model.typedIO

    buses = _plan_buses(io.bus, inst)
    num_slave = sum(1 for v in buses if v.bus.dir == BusDir.SLAVE)
    num_master = sum(1 for v in buses if v.bus.dir == BusDir.MASTER)

    # Interrupts and gpio share QEMU's wire pool, in this order.
    wire_out = [i for i in io.intrs if i.typ == StateType.OUTPUT] + [g for g in io.gpio if g.typ == StateType.OUTPUT]
    wire_in = [i for i in io.intrs if i.typ == StateType.INPUT] + [g for g in io.gpio if g.typ == StateType.INPUT]

    includes = []
    for view in buses:
        for inc in view.bus.INCLUDES:
            if inc not in includes:
                includes.append(inc)

    clock_mhz = [iface.freq_mhz for iface in io.clock_ifaces]
    if not clock_mhz:
        raise RuntimeError(f"{top_module}: has no clock - a component needs at least one")
    zero_clocks = [iface.name for iface in io.clock_ifaces if iface.freq_mhz <= 0]
    if zero_clocks:
        raise RuntimeError(
            f"{top_module}: clock(s) {zero_clocks!r} have no frequency set")

    # Declared clock/reset name -> resolved port name, which may carry a prefix.
    clock_port_by_name = {iface.name: port.name for iface, port in zip(io.clock_ifaces, io.clocks)}
    reset_port_by_name = {iface.name: port.name for iface, port in zip(io.reset_ifaces, io.resets)}

    def _clock_port(declared_name: str | None) -> str:
        return clock_port_by_name[declared_name] if declared_name else io.clocks[0].name

    def _reset_port(declared_name: str | None) -> str:
        return reset_port_by_name[declared_name] if declared_name else io.resets[0].name

    if buses:
        qemu_reset_name = _reset_port(buses[0].bus.reset)
    else:
        qemu_reset_name = io.resets[0].name if io.resets else ""

    ctx = _RenderCtx(
        model=model, top_module=top_module, inst=inst,
        wrapper_path=wrapper_path.split("/")[-1] if wrapper_path else "",
        anchor_freq_mhz=clock_mhz[0],
        reset_hold_us=1000.0 / min(clock_mhz),
        buses=buses,
        num_slave_buses=num_slave, num_master_buses=num_master,
        wire_out=wire_out, wire_in=wire_in, protocol_includes=includes,
        qemu_reset_name=qemu_reset_name,
        user_wired=user_wired,
    )

    if ctx.needs_qemu:
        ctx.init_entries.append('qemu("riscv", sk_descr_riscv)')
    ctx.init_entries += [
        f'{inst}_{clk.name}("{inst}_{clk.name}", 1.0 / {mhz}, SC_US)'
        for clk, mhz in zip(io.clocks, clock_mhz)
    ]
    ctx.init_entries += [f'{inst}_{sig.name}("{inst}_{sig.name}")' for sig in io.resets]
    ctx.init_entries += [
        v.bus.ctor_init(v.member,
                         f"{inst}_{_clock_port(v.bus.clock)}",
                         f"{inst}_{_reset_port(v.bus.reset)}")
        for v in buses
    ]
    ctx.init_entries += [f'{inst}_{sig.name}("{inst}_{sig.name}")' for sig in io.other]
    return ctx


def gen_main(wrapper_path: str, model: "ModelInfo", top_module: str | None, user_wired: bool) -> str:
    ctx = _build_ctx(wrapper_path, model, top_module, user_wired)
    return env().get_template("sim_cpp.j2").render(ctx=ctx)
