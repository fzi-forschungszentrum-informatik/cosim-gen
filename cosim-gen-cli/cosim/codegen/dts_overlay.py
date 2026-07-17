#!/usr/bin/env python3
"""The QEMU device-tree overlay for a coupled component: the remote-port
memory-master/slave nodes its buses become, and the wire node its interrupts
and gpio share.

Backend-agnostic - the dts describes the QEMU side of the channel, which
doesn't care whether the RTL behind it is arcilator- or verilator-built."""

import subprocess
from dataclasses import dataclass, field
from re import Pattern

from pydevicetree import Devicetree, ast

from .jinja import env
from .typedio import *


def parseDts(path: str) -> Devicetree:
    r = subprocess.run(
        [
            "dtc",
            "-I",
            "dts",
            path,
            "-O",
            "dts",
        ],
        capture_output=True,
    )
    if r.returncode != 0:
        raise RuntimeError(
            f"{path}: dtc failed to parse this dts: " + r.stderr.decode("utf-8")
        )
    dts_str = r.stdout.decode("utf-8")
    if not dts_str:
        raise RuntimeError(f"{path}: dtc produced no output")
    dts_str = dts_str.replace("&", " &")
    dts_str = dts_str.replace("< &", "<&")
    # Paths shouldn't end in /
    dts_str = dts_str.replace("/}", "}")
    return Devicetree.from_dts(dts_str)


def getSingleCompat(tree: Devicetree, compatible: Pattern) -> str:
    nodes = tree.match(compatible)
    if len(nodes) != 1:
        if not nodes:
            raise RuntimeError(f"no dts node matches compatible {compatible!r}")
        raise RuntimeError(
            f"multiple dts nodes match compatible {compatible!r}: "
            f"{', '.join(node.get_path() for node in nodes)}"
        )
    return nodes[0]


def getNodePhandles(tree: Devicetree):
    r = {}
    for node in tree.all_nodes():
        phandle = node.get_field("phandle")
        if phandle:
            r[phandle] = node
    return r


def resolve_component_node(tree: Devicetree, comp: "Component"):
    """The single dts node this component binds to, via comp.dts_path
    (an explicit node path) or comp.compat (a "compatible" match) - or None
    if it declares neither, meaning it isn't wired to anything in the base
    platform dts. A node can carry several buses (one reg/reg-names window
    each) and several interrupts - this binding lives once per component,
    not per bus (see Component.compat/dts_path in config.py)."""
    if comp.dts_path:
        node = tree.get_by_path(comp.dts_path)
        if node is None:
            raise RuntimeError(
                f"cosim.json: dts_path {comp.dts_path!r} not found in the base platform dts"
            )
        return node
    if comp.compat:
        return getSingleCompat(tree, comp.compat)
    return None


def _resolve_intc_ref(tree: Devicetree, ref) -> "ast.node.Node":
    """The dts node a phandle-shaped property value refers to, regardless of
    which of pydevicetree's three reference shapes it came out as (raw
    phandle int, string reference, or LabelReference - dtc's `-O dts`
    round-trip normally yields LabelReference, but all three show up in the
    wild)."""
    if type(ref) == int:
        return getNodePhandles(tree)[ref]
    if type(ref) in (str, ast.reference.LabelReference):
        return tree.get_by_reference(ref)
    assert False, f"Unknown type {type(ref)}"


def _node_interrupts(tree: Devicetree, node) -> tuple[str, list]:
    """(interrupt-parent path, interrupt cells) for this component's one dts
    node - `node=None` (no compat/dts_path declared) means no interrupt
    binding at all."""
    if node is None:
        return "TODO_SET_INTERRUPT_PARRENT", []

    intc_path = "TODO_SET_INTERRUPT_PARRENT"
    intcRef = node.get_field("interrupt-parent")
    if intcRef is not None:
        intc_path = _resolve_intc_ref(tree, intcRef).get_path()
        return intc_path, list(node.get_fields("interrupts") or [])

    extended = node.get_fields("interrupts-extended")
    if extended:
        groups: list[tuple[str, list]] = []
        for value in extended:
            if type(value) == int and groups:
                groups[-1][1].append(value)
            else:
                groups.append((_resolve_intc_ref(tree, value).get_path(), []))
        targets = {path for path, _cells in groups}
        if len(targets) != 1:
            raise RuntimeError(
                f"{node.get_path()}: interrupts-extended targets multiple "
                f"interrupt controllers ({', '.join(sorted(targets))}) - not supported"
            )
        intc_path = groups[0][0]
        return intc_path, [cell for _path, cells in groups for cell in cells]

    return intc_path, []


def _bus_reg_windows(node) -> list:
    """(address, size) pairs from this node's own `reg` property, in order -
    assigned to this component's slave buses positionally, one window per
    bus (matching the node's own reg-names order: a node with two buses has
    `reg-names = "control", "control2"` and two (addr, size) pairs in `reg`,
    one per attached bus)."""
    if node is None:
        return []
    reg = node.get_reg()
    return list(reg) if reg is not None else []


@dataclass
class _MasterBusView:
    name: str
    index: int  # this bus's 0-based index among the component's own master buses
    rp_index: int  # remote-port wire index (index + 10 - see QemuTLM.h)


@dataclass
class _SlaveNode:
    label: str  # dts label, e.g. "tlslave_TLUART_uart_0_auto_control_xing_in"
    node_name: str  # the dts node name/re-opening, e.g. "serial@64000000"
    index: int  # remote-port wire index (this bus's position among slave buses)
    registers: str  # "0xADDR 0xSIZE", already hex-formatted for the template


@dataclass
class _OverlayCtx:
    name: str
    rp_label: str
    chrdev_id: str
    sys_bus: str
    master_buses: list[_MasterBusView]
    # dts path ("/soc/", "/", ...) -> the slave nodes re-opened under it.
    slaves_by_path: dict[str, list[_SlaveNode]] = field(default_factory=dict)
    intc_path: str = "TODO_SET_INTERRUPT_PARRENT"
    interrupts: list[int] = field(default_factory=list)


def _build_overlay_ctx(
    name: str, comp, typedIO: TypedIO, tree: Devicetree, sysBus: str
) -> _OverlayCtx:
    """One component's own remote-port channel: its own RP node (own
    chrdev-id, so its own unix socket under $MACHINEPATH), and its own local
    bus/wire index space (0-based - safe because each component gets its own
    sim process/QemuTLM instance, never shared with another component's)."""
    node = resolve_component_node(tree, comp)
    intc_path, allIntrs = _node_interrupts(tree, node)
    outIntrs = [s for s in typedIO.intrs if s.typ == StateType.OUTPUT]
    if len(allIntrs) != len(outIntrs):
        raise RuntimeError(
            f"{name}: dts node has {len(allIntrs)} interrupt cell(s) but the component's "
            f"extracted OUTPUT interrupt wires number {len(outIntrs)} - compat/dts_path likely "
            "points at the wrong node, or a declared interrupt's prefix/name is wrong"
        )
    reg_windows = _bus_reg_windows(node)

    tlSlave = [bus for bus in typedIO.bus if bus.dir == BusDir.SLAVE]
    tlMaster = [bus for bus in typedIO.bus if bus.dir == BusDir.MASTER]

    ctx = _OverlayCtx(
        name=name,
        rp_label=f"RP_{name}",
        chrdev_id=name.lower(),
        sys_bus=sysBus,
        # One shared remote-port-gpio node/wire channel (QemuTLM only has one -
        # see include/QemuTLM.h's single `rp_wires` at index 20): interrupts
        # and gpio are both just bits in the same wire_in/wire_out array on
        # the SystemC side (sim_main._build_ctx puts interrupt bits
        # first, gpio bits after). The `interrupts` property only lists
        # entries for the interrupt bits (allIntrs never includes gpio) - the
        # gpio bits that follow in the same array are simply absent from that
        # list, so QEMU leaves them as plain, PLIC-unrouted gpio wires
        # without needing a second node or channel. The wires_in node itself
        # is always emitted (see the template) even when allIntrs is empty
        # (e.g. a bus-only component with no declared interrupts/gpio) -
        # QemuTLM always registers rp_wires at index 20 regardless, so the
        # dts needs a matching node for the remote-port handshake. But
        # `interrupt-parent`/`interrupts` are only meaningful when there's at
        # least one interrupt-routed bit - the template omits them (rather
        # than pointing at a placeholder phandle) when `interrupts` is empty.
        intc_path=intc_path,
        interrupts=list(allIntrs),
        master_buses=[
            _MasterBusView(name=bus.port_prefix, index=i, rp_index=i + 10)
            for i, bus in enumerate(tlMaster)
        ],
    )

    for i, bus in enumerate(tlSlave):
        if node is None or i >= len(reg_windows):
            reason = (
                "the component has no compat/dts_path binding"
                if node is None
                else f"its bound dts node only has {len(reg_windows)} reg window(s), need at least {i + 1}"
            )
            raise RuntimeError(
                f"{name}.{bus.port_prefix}: no dts reg window to bind this slave bus to - "
                f"{reason}. Fix cosim.json's compat/dts_path, or the base platform dts's "
                "reg/reg-names, to continue"
            )
        else:
            pathToken = node.get_path().split("/")
            baseName = pathToken[-1]
            path = "/".join(pathToken[:-1]) + "/"
            addr, size = reg_windows[i][:2]
            # A lone slave bus reuses the node's own bare name, merging the
            # remote-port properties into it in place. Multiple slave buses
            # on the same node instead each get their own synthetic name
            # (their own reg window's address) - they can't all re-open the
            # one node under the same name without colliding.
            nodeName = (
                baseName if len(tlSlave) == 1 else f"{baseName.split('@')[0]}@{addr:x}"
            )
            registers = f"{hex(addr)} {hex(size)}"

        ctx.slaves_by_path.setdefault(path, []).append(
            _SlaveNode(
                label=f"tlslave_{name}_{bus.port_prefix}",
                node_name=nodeName,
                index=i,
                registers=registers,
            )
        )

    return ctx


def open_base_tree(inputDtsPath: str) -> tuple[Devicetree, str]:
    """Parse the base platform dts once and locate its system bus node - the
    (tree, sysBus) pair is reused across every component's own overlay
    fragment in one `cosim run` (see gen_component_dts)."""
    tree = parseDts(inputDtsPath)
    sysBus = (
        getSingleCompat(tree, r"freechips,rocketchip-unknown-soc|simple-bus").get_path()
        + "/"
    )
    return tree, sysBus


def gen_component_dts(
    name: str, comp: "Component", typedIO: TypedIO, tree: Devicetree, sysBus: str
) -> str:
    """One component's own standalone overlay fragment: its own `&{/} {...}`
    block (RP node + wires) plus any per-path `&{path} {...}` blocks for its
    bus slave nodes. No `/include/` of the base dts here - written to that
    component's own build dir and pulled in by the top-level cosim.dts for
    whichever run actually couples it (see gen_run_dts / project.py)."""
    ctx = _build_overlay_ctx(name, comp, typedIO, tree, sysBus)
    return env().get_template("component_overlay.dts.j2").render(ctx=ctx)


def gen_run_dts(base_dts_name: str, component_overlay_paths: list[str]) -> str:
    """The top-level dts for one `cosim run`: the base platform dts plus
    `/include/` of exactly the coupled components' own overlay files (paths
    relative to build_dir, where this file itself lives - dtc resolves plain
    `/include/` relative to the including file's own directory). An empty
    `component_overlay_paths` is a plain boot: design.dts as-is, no overlay."""
    return (
        env()
        .get_template("run.dts.j2")
        .render(
            base_dts_name=base_dts_name,
            component_overlay_paths=component_overlay_paths,
        )
    )
