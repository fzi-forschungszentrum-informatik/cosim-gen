#!/usr/bin/env python3
"""Arcilator only: the A<Model>.h SystemC wrapper around a lowered model."""
from .format import *
from .jinja import env
from .typedio import *


def gen_wrapper(filename: str, header_path: str, models: list["ModelInfo"]) -> str:
    return env().get_template("arc_wrapper_h.j2").render(
        guard=format_header_guard(filename),
        header_name=header_path.split("/")[-1],
        models=models,
    )
