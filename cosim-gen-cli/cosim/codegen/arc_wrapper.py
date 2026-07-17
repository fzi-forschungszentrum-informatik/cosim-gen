#!/usr/bin/env python3
"""Arcilator-only: the A<Model>.h SystemC wrapper around a lowered arcilator
model, giving it the sc_in/sc_out ports and the clock-edge eval loop that
sim.cpp binds to.

Verilator needs no equivalent - its own V<Top>.h is already an sc_module."""
from .typedio import *
from .format import *
from .jinja import env


def gen_wrapper(filename: str, header_path: str, models: list["ModelInfo"]) -> str:
    return env().get_template("arc_wrapper_h.j2").render(
        guard=format_header_guard(filename),
        header_name=header_path.split("/")[-1],
        models=models,
    )
