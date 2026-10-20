#!/usr/bin/env python3
"""The QEMU device-tree overlay of a coupled component: remote-port nodes for its
buses and one wire node for its interrupts and gpio."""

import subprocess
from dataclasses import dataclass, field
from re import Pattern

from pydevicetree import Devicetree, ast

from ..config import Component
from .jinja import env
from .typedio import *


def parseDts(path: str, dtc: str = "dtc") -> Devicetree:
    r = subprocess.run(
        [
            dtc,
            "-I",
            "dts",
            path,
            "-O",
            "dts",
        ],
        capture_output=True,
        check=False,  # the returncode check below owns the error message
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


def resolve_component_node(tree: Devicetree, comp: Component):
    """The dts node selected by comp.dts_path or comp.compat; None if neither is set."""
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
    """The node a phandle int, string or LabelReference refers to."""
    if type(ref) == int:
        return getNodePhandles(tree)[ref]
    if type(ref) in (str, ast.reference.LabelReference):
        return tree.get_by_reference(ref)
    assert False, f"Unknown type {type(ref)}"


def _node_interrupts(tree: Devicetree, node) -> tuple[str, list]:
    """(interrupt-parent path, interrupt cells) of `node`; no interrupts if None."""
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


def _reg_cells(value: int, num_cells: int) -> str:
    """`value` as `num_cells` 32-bit hex cells, most significant first."""
    cells = []
    rest = value
    for _ in range(num_cells):
        cells.insert(0, hex(rest & 0xFFFFFFFF))
        rest >>= 32
    if rest:
        raise RuntimeError(f"reg value {hex(value)} doesn't fit in {num_cells} cell(s)")
    return " ".join(cells)


def _bus_reg_windows(node) -> list:
    """(address, size) pairs of the node's `reg`, one per slave bus in order."""
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
    registers: str  # the `reg` cells, hex-formatted for the template


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
    node = resolve_component_node(tree, comp)
    intc_path, allIntrs = _node_interrupts(tree, node)
    cells_per_irq = 1
    if allIntrs:
        cells_per_irq = tree.get_by_path(intc_path).get_field("#interrupt-cells") or 1
    outIntrs = [s for s in typedIO.intrs if s.typ == StateType.OUTPUT]
    if len(allIntrs) != cells_per_irq * len(outIntrs):
        raise RuntimeError(
            f"{name}: dts node has {len(allIntrs)} interrupt cell(s) "
            f"({cells_per_irq} per interrupt line) but the component's "
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
        # Interrupts and gpio share one wire node; `interrupts` lists only the interrupt bits.
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
            # A lone slave bus reuses the node's name; several get one name per window.
            nodeName = (
                baseName if len(tlSlave) == 1 else f"{baseName.split('@')[0]}@{addr:x}"
            )
            addr_cells = _reg_cells(addr, node.address_cells())
            size_cells = _reg_cells(size, node.size_cells())
            registers = f"{addr_cells} {size_cells}"

        ctx.slaves_by_path.setdefault(path, []).append(
            _SlaveNode(
                label=f"tlslave_{name}_{bus.port_prefix}",
                node_name=nodeName,
                index=i,
                registers=registers,
            )
        )

    return ctx


def open_base_tree(inputDtsPath: str, dtc: str = "dtc") -> tuple[Devicetree, str]:
    """(tree, system bus path) of the base platform dts."""
    tree = parseDts(inputDtsPath, dtc)
    sysBus = (
        getSingleCompat(tree, r"freechips,rocketchip-unknown-soc|simple-bus").get_path()
        + "/"
    )
    return tree, sysBus


def gen_component_dts(
    name: str, comp: Component, typedIO: TypedIO, tree: Devicetree, sysBus: str
) -> str:
    """The overlay fragment of one component, without the base dts."""
    ctx = _build_overlay_ctx(name, comp, typedIO, tree, sysBus)
    return env().get_template("component_overlay.dts.j2").render(ctx=ctx)


def gen_run_dts(base_dts_name: str, component_overlay_paths: list[str]) -> str:
    """The base dts plus /include/s of the given overlays (relative to build_dir)."""
    return (
        env()
        .get_template("run.dts.j2")
        .render(
            base_dts_name=base_dts_name,
            component_overlay_paths=component_overlay_paths,
        )
    )
