#!/usr/bin/env python3
"""sim.cpp: the SystemC main() and Top module wrapping one extracted component
- its clock/reset signals, its TLM bridges and the QemuTLM remote-port
channel, and the bind() calls tying the model's ports to all of it.

Backend-agnostic: the same sim.cpp drives an arcilator A<Model>.h wrapper or a
verilator V<Top>.h, selected by the USE_ARCILATOR/USE_VERILATOR define."""
from dataclasses import dataclass, field

from .typedio import *
from .format import *
from .jinja import env


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
    # One representative clock period backing CLOCK_MHZ - only the
    # max_cycles run-length scaling in sc_main needs a single value; every
    # declared clock (either backend, possibly several) gets its own real
    # period via its own init_entries entry below instead of using this macro.
    anchor_freq_mhz: int
    # How long (in us) to hold reset before releasing it - 1000 periods of
    # the slowest declared clock, long enough that domain can't miss its
    # first edge while reset is held.
    reset_hold_us: float
    buses: list[_BusView]
    num_slave_buses: int
    num_master_buses: int
    wire_out: list[StateInfo]  # interrupt/gpio OUTPUT signals -> qemu.wire_in[]
    wire_in: list[StateInfo]   # interrupt/gpio INPUT signals  -> qemu.wire_out[]
    protocol_includes: list[str]  # headers pulled in by every bus's own bridge
    # Which reset QEMU's own remote-port TLM reset line is wired to - the
    # first bus's own reset (falling back the same way ctor_init's does), or
    # the first declared reset if there are no buses at all (an
    # interrupt/gpio-only component).
    qemu_reset_name: str = ""
    init_entries: list[str] = field(default_factory=list)

    @property
    def needs_qemu(self) -> bool:
        return self.model.typedIO.needs_qemu


def _build_ctx(wrapper_path: str, model: "ModelInfo", top_module: str) -> _RenderCtx:
    top_module = top_module or model.name
    inst = top_module.lower()
    io = model.typedIO

    buses = _plan_buses(io.bus, inst)
    num_slave = sum(1 for v in buses if v.bus.dir == BusDir.SLAVE)
    num_master = sum(1 for v in buses if v.bus.dir == BusDir.MASTER)

    # Interrupts and gpio both talk to QEMU over the same remote-port wire
    # pool (see dts_overlay.py) - combined here so the template can just
    # index qemu.wire_in/out[] by position, no offset arithmetic needed.
    wire_out = [i for i in io.intrs if i.typ == StateType.OUTPUT] + [g for g in io.gpio if g.typ == StateType.OUTPUT]
    wire_in = [i for i in io.intrs if i.typ == StateType.INPUT] + [g for g in io.gpio if g.typ == StateType.INPUT]

    includes = []
    for view in buses:
        for inc in view.bus.INCLUDES:
            if inc not in includes:
                includes.append(inc)

    # Each clock's own resolved period - always its own declared freq_mhz, no
    # project-wide fallback. clock_ifaces/clocks stay 1:1 (ClockInterface is
    # EXACT=True, one port each), so zip() pairs each interface with its port.
    clock_mhz = [iface.freq_mhz for iface in io.clock_ifaces]
    if not clock_mhz:
        raise RuntimeError(f"{top_module}: has no clock - a component needs at least one")
    zero_clocks = [iface.name for iface in io.clock_ifaces if iface.freq_mhz <= 0]
    if zero_clocks:
        raise RuntimeError(
            f"{top_module}: clock(s) {zero_clocks!r} have no frequency set")

    # A bus's own clock/reset (BusInterface.clock/.reset, see interfaces/bus.py)
    # names a sibling interface by its *declared* cosim.json name (e.g.
    # "gemac_gmii_tx_phyClk") - but the sim.cpp signal is named after the
    # *resolved, extraction-prefixed* port (io.clocks[i].name, e.g.
    # "uart_0_clock"), which can differ from the declared name. Map declared
    # name -> resolved port name so a bus's override (or the first-declared
    # fallback) both resolve to the right sim.cpp signal.
    clock_port_by_name = {iface.name: port.name for iface, port in zip(io.clock_ifaces, io.clocks)}
    reset_port_by_name = {iface.name: port.name for iface, port in zip(io.reset_ifaces, io.resets)}

    def _clock_port(declared_name: str | None) -> str:
        return clock_port_by_name[declared_name] if declared_name else io.clocks[0].name

    def _reset_port(declared_name: str | None) -> str:
        return reset_port_by_name[declared_name] if declared_name else io.resets[0].name

    # The reset QEMU's own TLM reset line drives: the first bus's own reset
    # (same fallback as its ctor_init below), or - a bus-less, interrupt/gpio-
    # only component - the first declared reset.
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
    )

    if ctx.needs_qemu:
        ctx.init_entries.append('qemu("riscv", sk_descr_riscv)')
    ctx.init_entries += [
        f'{inst}_{clk.name}("{inst}_{clk.name}", 1.0 / {mhz}, SC_US)'
        for clk, mhz in zip(io.clocks, clock_mhz)
    ]
    ctx.init_entries += [f'{inst}_{sig.name}("{inst}_{sig.name}")' for sig in io.resets]
    ctx.init_entries += [
        # A bus's own clock/reset, when it names one - otherwise the first
        # declared domain, matching every existing single-clock/reset component.
        v.bus.ctor_init(v.member,
                         f"{inst}_{_clock_port(v.bus.clock)}",
                         f"{inst}_{_reset_port(v.bus.reset)}")
        for v in buses
    ]
    ctx.init_entries += [f'{inst}_{sig.name}("{inst}_{sig.name}")' for sig in io.other]
    return ctx


def gen_main(wrapper_path: str, model: "ModelInfo", top_module: str | None = None) -> str:
    # Every sim binary wraps exactly one component now (see cosim-gen-cli/README.md:
    # N components no longer share one Top/QemuTLM - each gets its own sim
    # process and its own remote-port channel).
    ctx = _build_ctx(wrapper_path, model, top_module)
    return env().get_template("sim_cpp.j2").render(ctx=ctx)
