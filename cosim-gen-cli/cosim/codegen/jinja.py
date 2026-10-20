#!/usr/bin/env python3
"""The cached Jinja environment for templates/."""
from functools import lru_cache

from jinja2 import Environment, PackageLoader

from ..statejson import short_type
from .format import systemc_port_type


@lru_cache(maxsize=1)
def env() -> Environment:
    e = Environment(
        loader=PackageLoader("cosim.codegen", "templates"),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    e.filters["systemc_port_type"] = systemc_port_type
    e.filters["short_type"] = short_type
    # dts "&{path}" references; literal braces in a template would clash with Jinja's.
    e.filters["dts_ref"] = lambda path: "{" + path + "}"
    return e
