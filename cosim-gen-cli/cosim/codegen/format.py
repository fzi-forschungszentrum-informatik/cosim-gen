#!/usr/bin/env python3
"""C++ source formatting helpers shared by both backends: identifier
sanitizing, include guards, and SystemC port types.

The arcilator *state layout* formatters (Signal{}/Hierarchy{} literals, the
`state+offset` view refs) live in arc_model.py instead - only the arcilator
model header needs them."""
import re

from .typedio import *


C_KEYWORDS = [
    "alignas",
    "alignof",
    "and",
    "and_eq",
    "asm",
    "auto",
    "bitand",
    "bitor",
    "bool",
    "break",
    "case",
    "catch",
    "char",
    "char16_t",
    "char32_t",
    "class",
    "compl",
    "const",
    "const_cast",
    "constexpr",
    "continue",
    "decltype",
    "default",
    "delete",
    "do",
    "double",
    "dynamic_cast",
    "else",
    "enum",
    "explicit",
    "export",
    "extern",
    "false",
    "float",
    "for",
    "friend",
    "goto",
    "if",
    "inline",
    "int",
    "long",
    "mutable",
    "namespace",
    "new",
    "noexcept",
    "not",
    "not_eq",
    "nullptr",
    "operator",
    "or",
    "or_eq",
    "private",
    "protected",
    "public",
    "register",
    "reinterpret_cast",
    "return",
    "short",
    "signed",
    "sizeof",
    "static",
    "static_assert",
    "static_cast",
    "struct",
    "switch",
    "template",
    "this",
    "thread_local",
    "throw",
    "true",
    "try",
    "typedef",
    "typeid",
    "typename",
    "union",
    "unsigned",
    "using",
    "virtual",
    "void",
    "volatile",
    "wchar_t",
    "while",
    "xor",
    "xor_eq",
]


def clean_name(name: str) -> str:
  name = re.sub(r'[^a-zA-Z_0-9]', "_", name)
  if not re.match(r'^[a-zA-Z_]', name):
    name = "_" + name
  if name in C_KEYWORDS:
    name = "_" + name
  return name


def format_header_guard(filename: str) -> str:
  return f"_{filename.split('/')[-1].upper().replace('.','_').replace('-','_')}_"


def indent(s: str, amount: int = 1):
  if not s or s == "\n":
    return ""
  while s[-1] == "\n":
    s = s[:-1]
  return s.replace("\n", "\n" + "  " * amount)


def systemc_port_type(state: StateInfo) -> str:
  if state.typ == StateType.INPUT:
    prefix = "sc_in"
  elif state.typ == StateType.OUTPUT:
    prefix = "sc_out"
  else:
    assert False, f"Unexpected io type {state}"
  return f"{prefix}<{short_type(state)}>"
