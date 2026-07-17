"""The state description JSON that cosim-extract (and arcilator) emit for a
lowered design: a flat list of named signals with their bit offset, width and
kind, plus the helpers for grouping them back into an instance hierarchy.

Backend-agnostic and dependency-free on purpose - it sits below both
`cosim.interfaces` (which classifies these signals into declared interfaces)
and `cosim.codegen` (which emits C++ from them), so neither has to import the
other to talk about a port."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


# needed to support python3 older than 3.9
def removeprefix(text, prefix):
    if text.startswith(prefix):
        return text[len(prefix) :]
    return text


class StateType(Enum):
    INPUT = "input"
    OUTPUT = "output"
    REGISTER = "register"
    WIRE = "wire"
    MEMORY = "memory"


@dataclass
class StateInfo:
    name: str | None
    offset: int
    numBits: int
    typ: StateType
    stride: int | None
    depth: int | None

    def decode(d: dict) -> StateInfo:
        return StateInfo(
            d["name"],
            d["offset"],
            d["numBits"],
            StateType(d["type"]),
            d.get("stride"),
            d.get("depth"),
        )


@dataclass
class StateHierarchy:
    name: str
    states: list[StateInfo]
    children: list[StateHierarchy]


# Organize the state by hierarchy.
def group_state_by_hierarchy(states: list[StateInfo]) -> tuple[list[StateInfo], list[StateHierarchy]]:
    local_state = []
    hierarchies = []
    remainder = []

    used_names = set()

    def uniquify(name: str) -> str:
        if name in used_names:
            i = 0
            while f"{name}_{i}" in used_names:
                i += 1
            name = f"{name}_{i}"
        used_names.add(name)
        return name

    for state in states:
        if not state.name or "/" not in state.name:
            state.name = uniquify(state.name)
            local_state.append(state)
        else:
            remainder.append(state)
    while len(remainder) > 0:
        left = []
        prefix = remainder[0].name.split("/")[0]
        substates = []
        for state in remainder:
            if not state.name.startswith(prefix + "/"):
                left.append(state)
                continue
            state.name = removeprefix(state.name, prefix + "/")
            substates.append(state)
        remainder = left
        hierarchy_states, hierarchy_children = group_state_by_hierarchy(substates)
        prefix = uniquify(prefix)
        hierarchies.append(StateHierarchy(prefix, hierarchy_states, hierarchy_children))
    return local_state, hierarchies


def removeIo(ioList: list[StateInfo], rem: list[StateInfo]) -> list[StateInfo]:
    return [io for io in ioList if io not in rem]


def short_type(state: StateInfo) -> str:
    # Bucket boundaries follow verilator's own `-sc` SystemC port codegen (any
    # multi-bit signal <=32 bits becomes sc_in/sc_out<uint32_t>, never a
    # narrower uintN_t) - not just an arbitrary "smallest type that fits"
    # choice. This also picks the arcilator wrapper's own port types (which is
    # otherwise free to choose anything, since that wrapper is entirely our
    # own codegen); matching verilator's convention here keeps both backends'
    # generated sim.cpp connecting to the same signal types on both sides of
    # the bind().
    if state.numBits <= 1:
        return "bool"
    for bits, ty in [(32, "uint32_t"), (64, "uint64_t")]:
        if state.numBits <= bits:
            return ty
    raise RuntimeError(
        f"{state.name}: {state.numBits}-bit port is wider than the 64 bits sim.cpp codegen "
        "currently supports!"
    )
