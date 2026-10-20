# cosim

Generate and run a QEMU↔RTL co-simulation from a single declarative `cosim.json`.

Given a design (`.fir`/`.hw.mlir`), a device tree, and a list of components to extract,
`cosim build` produces one `sim` binary **per component**, each a SystemC model with its own
remote-port channel to QEMU and its own build directory under
`build/components/<name>/` (see [Build output](#build-output)).
`cosim run` boots QEMU and couples the named components to it; `cosim run rtl [COMPONENT]`
runs one standalone, without QEMU.

## Install

```sh
pip install -e .
```

This installs the `cosim` command only; the external tools are found at run time, see
[Toolchain resolution](#toolchain-resolution).

## `cosim.json` example

```json
{
  "design": {
    "input": "soc.fir",
    "dts": "board.dts",
    "seqmem": "soc.seqmem.conf",
    "annotations": "soc.anno.json",
    "supported_backends": ["arcilator", "verilator"]
  },
  "qemu": {
    "elfs": ["bootrom.elf", "simram.elf"],
    "extra_args": ["-d", "guest_errors"]
  },
  "jobs": "4",
  "sync_quantum": 1000,
  "max_cycles": 0,
  "extra_args": ["+foo=1"],
  "trace": false,
  "sysc_trace": false,
  "coverage": false,
  "cxxflags": ["-DFOO"],
  "ldlibs": [],
  "verilator_args": ["--threads", "2"],
  "arcilator_args": [],
  "soc_rtl": {
    "extra_files": ["bootrom.mem", "simram.mem"],
    "interfaces": [
      { "kind": "clock", "name": "sys_clock", "freq_mhz": 150 },
      { "kind": "reset", "name": "sys_reset" }
    ]
  },
  "components": [
    { "type": "TLUART", "path": "/Shell/uart",
      "compat": "sifive,uart0",
      "interfaces": [
        { "kind": "clock", "name": "clock", "freq_mhz": 150 },
        { "kind": "reset", "name": "reset" },
        { "kind": "tilelink", "prefix": "auto_control_xing_in", "dir": "slave" },
        { "kind": "interrupt", "prefix": "auto_int_xing_out", "dir": "out" }
      ],
      "extra_args": ["+tx_uart=1"],
      "trace": true,
      "user_sim_cpp": false }
  ],
  "toolchain": {
    "firtool": "/opt/firtool/bin/firtool",
    "qemu": "/opt/qemu-fdt/riscv-bin/qemu/bin/qemu-system-riscv64"
  }
}
```

### `design`

| Key | Default | Meaning |
|---|---|---|
| `input` | required | `.fir`, or `.hw.mlir`/`.mlir` to skip the firtool lowering. |
| `dts` | | Base platform device tree, needed for runs with QEMU. A component binds to one of its nodes with `compat`/`dts_path`. |
| `supported_backends` | `["verilator"]` | Non-empty list of `"arcilator"`/`"verilator"`. `cosim build` builds all of them; `cosim run --backend` picks one (default: the first). |
| `seqmem` | | Passed to firtool as `--repl-seq-mem-file`. |
| `annotations` | | Passed to firtool as `--annotation-file`. |
| `extra_vsrcs` | `[]` | Verilog sources passed to every verilator build; not supported with `arcilator`. |

### `qemu`

| Key | Default | Meaning |
|---|---|---|
| `elfs` | `[]` | ELF files loaded into QEMU via `-device loader`, in order. |
| `extra_args` | `[]` | Extra arguments appended to every `qemu` invocation. |

### Top-level build/run defaults

| Key | Default | Meaning |
|---|---|---|
| `jobs` | all CPUs | `make -j` for the build; `cosim build -j N` overrides it. |
| `sync_quantum` | `1000` | Cycles a `sim` runs between remote-port syncs with QEMU. |
| `max_cycles` | `0` | Clock cycles after which a `sim` stops; `0` runs forever. |
| `extra_args` | `[]` | Extra arguments for every `sim`, after sync_quantum/max_cycles. Read as verilator plusargs; ignored by arcilator. |
| `trace` | `false` | The backend's internal-signal tracer: verilator's (`verilator_sysc_native.vcd`) or arcilator's (`arcilator.vcd`). |
| `sysc_trace` | `false` | A VCD of `Top`'s ports (`{verilator,arcilator}_sysc.vcd`). |
| `coverage` | `false` | Verilator line/toggle coverage (`coverage.dat`; see `verilator_coverage`). |
| `cxxflags`, `ldlibs` | `[]` | Extra compile/link flags for the `sim`. |
| `verilator_args`, `arcilator_args` | `[]` | Extra verilator/arcilator flags, added to the built-in ones. |

A component (or `soc_rtl`) can override each of them.

### `soc_rtl`

The whole design, never coupled to QEMU. Same fields as a [component](#components) without
`type`, `path`, `name` and `compat`/`dts_path`; `interfaces` only takes `clock` and `reset`. Without
it, the clock and reset are guessed by port name.

### `components`

Components to extract:

| Key | Default | Meaning |
|---|---|---|
| `type` | required | The module name in the FIRRTL. |
| `path` | required | The instance path. |
| `interfaces` | required | What the ports are connected to, one entry per interface (see below). |
| `compat` / `dts_path` | | A dts `compatible` string or node path: the node in `design.dts` this component binds to; needed to couple it to QEMU. |
| `name` | last segment of `path` | The component's name in `build/components/<name>/`, `cosim run <name>`, `TOP_NAME` (`<name>_TOP`) and the dts. |
| `extra_files` | `[]` | Files copied into the build directory before firtool runs, e.g. the `.mem` file a `MemoryFileInlineAnnotation` names. Producing them (e.g. ELF→mem) is up to you; see `../example/convert.sh`. The lists of all units are combined. |
| `extra_srcs` | `[]` | `.cpp` files (relative to `cosim.json`) compiled into this unit's `sim`, e.g. a SystemC model defining `cosim_user_wire()` (see [User models](#user-models)). Basenames must be unique and not `sim`, `<name>` or `gen-arc-<name>`. |
| `user_sim_cpp` | `false` | `true` stops generating this unit's `sim.cpp`, so you can maintain your own. |
| `sync_quantum`, `max_cycles`, `extra_args`, `trace`, `sysc_trace`, `coverage`, `cxxflags`, `ldlibs`, `verilator_args`, `arcilator_args` | top level | Override the [top-level defaults](#top-level-buildrun-defaults). |

`interfaces` entries, by `"kind"`:

| Kind | Fields | Connected to |
|---|---|---|
| `clock` | `name`, `freq_mhz` | The clock port and its frequency; at least one. The first clock's port also gives the instance prefix of all other ports. |
| `reset` | `name`, `active_low` (default `false`) | The reset port. |
| `<protocol>` | `prefix`, `dir` | A memory-mapped bus to QEMU (see [Bus protocols](#bus-protocols)). `prefix` is the common prefix of the bus ports; `dir` is `"slave"` (QEMU is master) or `"master"` (the peripheral is a DMA master). Slave buses take the `reg` windows of the component's dts node in order. |
| `interrupt` | `prefix` or `name`, `dir` | A remote-port wire to QEMU. `prefix` also matches the ports under it (e.g. `_sync_0..N`); `name` must match exactly one port. `dir` is `"out"` (the peripheral raises it) or `"in"`. The number of `"out"` interrupts must match the `interrupts` of the dts node. |
| `gpio` | `prefix` or `name` | A remote-port wire to QEMU, not routed to an interrupt controller. |
| `unconnected` | `name` | Nothing; the port stays at the extraction boundary for a [user model](#user-models). |

Port names are written as in the peripheral's FIRRTL, without the instance prefix
(`uart_0.`) that extraction adds.

Undeclared ports are allowed: they become plain `sc_signal`s in `sim.cpp` for your own
SystemC model and don't talk to QEMU.

`cosim build` always builds the whole design as one more unit as well;
`cosim run rtl` runs it by default. Without `components`, it is the only unit.

`cosim gen-config` derives the list from a diplomacy config (see [CLI](#cli)).

### Bus protocols

A bus `"kind"` selects a `BusInterface` subclass from
[`cosim/interfaces/`](cosim/interfaces/).A subclass defines the signal
layout, the TLM bridge classes and their template types, so a new protocol is one new
subclass.

### `toolchain`

Per-tool overrides: `firtool`, `arcilator`, `cosim_extract`, `cosim_plugin`, `systemc`,
`systemc_include`, `systemc_lib`, `qemu`. See [Toolchain resolution](#toolchain-resolution).

## CLI

- **`cosim init [dir] [--backend arcilator|verilator] [-f]`** — write a starter
  `cosim.json` to `dir` (default: cwd) for one backend (default: verilator).
- **`cosim gen-config <diplomacy.json> [-o cosim.json] [--dts board.dts]`** — derive
  `components` from a `*.diplomacy.json`: one entry per labeled module, with clock, reset,
  bus and interrupt interfaces. With `--dts`, also sets each component's `dts_path` by bus
  address.
- **`cosim build [-C cosim.json] [-j N]`** — build every unit (each component and the
  whole design) for every backend in `design.supported_backends`.
- **`cosim run [rtl] [COMPONENT ...] [--all] [--backend arcilator|verilator] [-C cosim.json] [-j N]`** —
  put the options right after `run` or at the end, not between `rtl` and a component name.
  - No arguments — boot QEMU on `design.dts`, without RTL.
  - Component names (e.g. `cosim run uart_0 gpio_0`) — couple QEMU to just those.
  - `--all` — couple QEMU to every component with bus/interrupt/gpio IO.
  - `rtl [COMPONENT]` — run one `sim` without QEMU: the whole design's, or the component's.
  - `--backend` — which built backend to run; default: the first supported one.
  - `-j N` — `make -j` for `rtl` runs.
  - `-l`/`--list` — list the components and how to run each, then exit.

  The dtb is regenerated on every run, so dts and `cosim.json` binding changes need no
  rebuild. Output is also written to `build/run.log` (QEMU) or
  `build/components/<name>/build-<backend>/run.log` (`rtl`).
- **`cosim clean [-C cosim.json] [--all]`** — remove build output. Keeps each unit's
  `sim.cpp` and your own sources; `--all` removes the whole `build/`.
- **`cosim doctor [-C cosim.json]`** — print the resolved tool paths.

## Build output

```
build/components/<name>/        # one per component, plus one for the whole design
  Makefile  config.mk           # regenerated by every `cosim build` - do not edit
  sim.cpp                       # generated once, then left alone
  build-<backend>/sim           # the binary
```

## User models

`sim.cpp` calls a weak `cosim_user_wire(Top &top)` and lists the undeclared ports above it.
Define it in one of the unit's `extra_srcs` to drive them; from there, find the signals by
name, e.g. `sc_find_object("top.<signal>")`.

## Toolchain resolution

For each tool, `cosim` takes the first of (see `cosim/toolchain.py`):

1. `toolchain.<name>` in `cosim.json`.
2. An environment variable: `FIRTOOL`, `ARCILATOR`, `OPT`, `LLC`, `EXTRACT` (for
   `cosim_extract`), `COSIM_GEN_OPT`, `COSIM_PLUGIN`, `VERILATOR`, `DTC`, `QEMU`,
   `SYSTEMC_INCLUDE`, `SYSTEMC_LIB` (see `_TOOL_SPECS`).
3. For `cosim_extract`/`cosim_gen_opt`/`cosim_plugin`: `cosim-gen-circt/build/{bin,lib}` of
   this checkout.
4. `$PATH` (not for `systemc_include`/`systemc_lib`).

`systemc_include`/`systemc_lib` are resolved separately, falling back to `<prefix>/include`
and `<prefix>/lib` of `systemc` / `COSIM_SYSTEMC` / `SYSTEMC_HOME`. `cosim doctor` shows
the result.
