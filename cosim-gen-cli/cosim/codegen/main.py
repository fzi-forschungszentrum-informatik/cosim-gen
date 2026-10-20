#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from .arc_model import gen_cpp, gen_header
from .arc_wrapper import gen_wrapper
from .sim_main import gen_main
from .typedio import *


def processJson(state_json, io_spec=None) -> List[ModelInfo]:
  """Models of a state json, classified by `io_spec` or, if None, by port names."""
  with open(state_json, "r") as f:
    models = [ModelInfo.decode(d) for d in json.load(f)]

  for model in models:
    internal = []
    for state in model.states:
      state.name = state.name.replace(".", "_")

      if state.typ != StateType.INPUT and state.typ != StateType.OUTPUT:
        internal.append(state)
      else:
        model.io.append(state)
    model.hierarchy = [
        StateHierarchy("internal", *group_state_by_hierarchy(internal))
    ]
    model.typedIO = build_typedIO(io_spec, model.io) if io_spec is not None else infer_typedIO(model.io)
  return models


def _write_if_changed(path: Path, content: str) -> None:
  # Keeps the mtime when unchanged, so make doesn't recompile.
  if not path.exists() or path.read_text() != content:
    path.write_text(content)


def emit(state_json: str, backend: str, out_dir: str, name: str, io_spec=None) -> None:
  """Writes sim.cpp to `out_dir`, plus the arcilator model and A<Model>.h wrapper
  for the arcilator backend. File names derive from `name`."""
  models = processJson(state_json, io_spec=io_spec)
  assert len(models) == 1, "Currently only one top module is allowed"
  model = models[0]

  reserved = {'state'}
  for io in model.io:
    if io.name in reserved:
      io.name = io.name + '_'

  out = Path(out_dir)
  # Independent of `backend`, so sim.cpp is the same for both.
  wrapper_name = f"A{model.name}.h"
  if backend == "arcilator":
    header_path = out / f"gen-arc-{name}.h"
    cpp_path = out / f"gen-arc-{name}.cpp"
    wrapper_path = out / wrapper_name
    _write_if_changed(header_path, gen_header(str(header_path), [model], 1))
    _write_if_changed(cpp_path, gen_cpp(header_path.name, [model]))
    _write_if_changed(wrapper_path, gen_wrapper(str(wrapper_path), header_path.name, [model]))

  _write_if_changed(out / "sim.cpp", gen_main(wrapper_name, model, model.name))


def main():
  parser = argparse.ArgumentParser(
      description="Emit the SystemC sim sources for one cosim component")
  parser.add_argument("--state-json", required=True, help="arcilator/cosim-gen state description file")
  parser.add_argument("--backend", required=True, choices=["arcilator", "verilator"])
  parser.add_argument("--out-dir", required=True, help="directory to write sim.cpp (and, for arcilator, the wrapper/header) into")
  parser.add_argument("--name", required=True, help="component instance name / whole-design top - the output filename base")
  parser.add_argument("--config", help="cosim.json, required with --component/--soc-rtl to classify IO from the declaration")
  parser.add_argument("--component", help="component name whose 'interfaces' list classifies the extracted ports; omit for the whole-design name-pattern fallback")
  parser.add_argument("--soc-rtl", action="store_true", help="use cosim.json's top-level 'soc_rtl' declaration to classify the whole design's clock/reset, instead of the name-pattern fallback")
  args = parser.parse_args()

  io_spec = None
  if args.soc_rtl:
    if not args.config:
      parser.error("--soc-rtl requires --config")
    from ..config import Config
    cfg = Config.load(Path(args.config))
    io_spec = cfg.soc_rtl
  elif args.component:
    if not args.config:
      parser.error("--component requires --config")
    from ..config import Config
    cfg = Config.load(Path(args.config))
    io_spec = next((c for c in cfg.components if c.name == args.component), None)
    if io_spec is None:
      parser.error(f"--component {args.component!r} not found in {args.config}")

  emit(args.state_json, args.backend, args.out_dir, args.name, io_spec)


if __name__ == '__main__':
  main()
