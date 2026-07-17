#!/usr/bin/env python3
"""The one shared Jinja environment for everything under templates/.

Cached: the generators run once per component in project.py's build loop, and
a fresh Environment would re-discover the package templates and re-compile
every .j2 to Python on each call. One shared env compiles each template
exactly once. trim_blocks/lstrip_blocks make block tags emit no stray
whitespace-only lines, so no post-render cleanup is needed."""
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
    # dts's "&{path}" extended-reference syntax needs a literal brace glued
    # directly onto the path text - a filter keeps that out of the template's
    # own {{ }}/{% %} delimiters, where adjacent literal braces would
    # otherwise be ambiguous with Jinja's own brace syntax.
    e.filters["dts_ref"] = lambda path: "{" + path + "}"
    return e
