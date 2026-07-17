#!/usr/bin/env python3
"""Arcilator-only: the model header/cpp pair (gen-arc-<name>.h/.cpp) describing
one lowered model's state layout - the Signal/Hierarchy tables the arcilator
runtime reads, and the View struct that maps named signals onto byte offsets
in the model's flat state buffer.

Verilator needs none of this; its own V<Top>.h already exposes the ports."""
from .typedio import *
from .format import *


def format_signal(state: StateInfo) -> str:
  fields = [
      f"\"{state.name}\"", state.offset, state.numBits,
      f"Signal::{state.typ.value.capitalize()}"
  ]
  if state.typ == StateType.MEMORY:
    fields += [state.stride, state.depth]
  fields = ", ".join(str(f) for f in fields)
  return f"Signal{{{fields}}}"


def format_hierarchy(hierarchy: StateHierarchy) -> str:
  states = ",\n  ".join(format_signal(s) for s in hierarchy.states)
  if states:
    states = "\n  " + states + "\n"
  states = "{" + states + "}"
  children = ",\n  ".join(
      format_hierarchy(c).replace("\n", "\n  ") for c in hierarchy.children)
  if children:
    children = "\n  " + children + "\n"
  children = "{" + children + "}"
  return f"Hierarchy{{\"{hierarchy.name}\", {len(hierarchy.states)}, {len(hierarchy.children)}, (Signal[]){states}, (Hierarchy[]){children}}}"


def state_cpp_type_nonmemory(state: StateInfo) -> str:
  for bits, ty in [(8, "uint8_t"), (16, "uint16_t"), (32, "uint32_t"),
                   (64, "uint64_t")]:
    if state.numBits <= bits:
      return ty
  return f"Bytes<{(state.numBits+7)//8}>"


def state_cpp_type(state: StateInfo) -> str:
  if state.typ == StateType.MEMORY:
    return f"Memory<{state_cpp_type_nonmemory(state)}, {state.stride}, {state.depth}>"
  return state_cpp_type_nonmemory(state)


def state_cpp_ref(state: StateInfo) -> str:
  return f"*({state_cpp_type(state)}*)(state+{state.offset})"


def format_signal_declaration(signals):
    lines = ""
    for io in signals:
      lines += f'{state_cpp_type(io)} &{io.name};\n'
    return lines


def format_signal_init(signals):
    lines = ""
    for io in signals:
      lines += f'{io.name}({state_cpp_ref(io)}),\n'
    return lines


def format_signals(signals):
    lines = ""
    for io in signals:
      lines += f'{format_signal(io)},\n'
    return lines


def format_view_hierarchy(hierarchy: StateHierarchy, depth: int) -> str:
  lines = []
  for state in hierarchy.states:
    lines.append(f"{state_cpp_type(state)} &{clean_name(state.name)};")
  if depth != 0:
    for child in hierarchy.children:
      lines.append(
          f"{indent(format_view_hierarchy(child, depth-1))} {clean_name(child.name)};"
      )
  lines = "\n  ".join(lines)
  if lines:
    lines = "\n  " + lines + "\n"
  return f"struct {{{lines}}}"


def format_view_constructor(hierarchy: StateHierarchy, depth: int) -> str:
  lines = []
  for state in hierarchy.states:
    lines.append(f".{clean_name(state.name)} = {state_cpp_ref(state)}")
  if depth != 0:
    for child in hierarchy.children:
      lines.append(
          f".{clean_name(child.name)} = {indent(format_view_constructor(child, depth-1))}"
      )
  lines = ",\n  ".join(lines)
  if lines:
    lines = "\n  " + lines + "\n"
  return f"{{{lines}}}"


def gen_header(filename, models, view_depth):
  MACRO_NEWLINE = "\\\n"
  
  r = f'''#ifndef {format_header_guard(filename)}
#define {format_header_guard(filename)}
  
#include "arcilator-runtime.h"

extern "C" {{
'''
  for model in models:
    r += f'void {model.name}_eval(void* state);\n'
  r += '}\n'


  for model in models:
    r += f'''
class {model.name}Layout {{
public:
  static const char *name;
  static const unsigned numStates;
  static const unsigned numStateBytes;
  static const std::array<Signal, {len(model.io)}> io;
  static const Hierarchy hierarchy;
}};

class {model.name}View {{
public:
  {indent(format_signal_declaration(model.io))}
  {indent(format_view_hierarchy(model.hierarchy[0], view_depth))} {model.hierarchy[0].name};
  uint8_t *state;

  {model.name}View(uint8_t *state) :
    {indent(format_signal_init(model.io), 2)}
    {model.hierarchy[0].name}({indent(format_view_constructor(model.hierarchy[0], view_depth), 2)}),
    state(state) {{}}
}};

class {model.name} {{
public:
  std::vector<uint8_t> storage;
  {model.name}View view;

  {model.name}() : storage({model.name}Layout::numStateBytes, 0), view(&storage[0]) {{}}
  void eval() {{ {model.name}_eval(&storage[0]); }}
  ValueChangeDump<{model.name}Layout> vcd(std::basic_ostream<char> &os) {{
    ValueChangeDump<{model.name}Layout> vcd(os, &storage[0]);
    vcd.writeHeader();
    vcd.writeDumpvars();
    return vcd;
  }}
}};

{f' {MACRO_NEWLINE}  '.join([f'#define {model.name.upper()}_PORTS'] + [f'PORT({io.name})' for io in model.io])}
'''

  r += f"#endif // {format_header_guard(filename)}\n"
  return r


def gen_cpp(header_path, models):
  r = f'#include "{header_path}"\n'

  for model in models:

    r += f'''
const char *{model.name}Layout::name = "{model.name}";
const unsigned {model.name}Layout::numStates = {len(model.states)};
const unsigned {model.name}Layout::numStateBytes = {model.numStateBytes};
const std::array<Signal, {len(model.io)}> {model.name}Layout::io = {{
  {indent(format_signals(model.io))}
}};

const Hierarchy {model.name}Layout::hierarchy = {indent(format_hierarchy(model.hierarchy[0]))};
'''
  return r
  