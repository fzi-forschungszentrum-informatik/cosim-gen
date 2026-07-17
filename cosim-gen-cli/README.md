# cosim

Generate and run a QEMU↔RTL co-simulation from a single declarative `cosim.json`.

Point it at a design (`.fir`/`.hw.mlir`), a device tree, and a list of components to
extract, and `cosim build` produces one `sim` binary **per component** — each an
independent SystemC model, each with its own remote-port channel to QEMU, each its own
**standalone, editable mini-project** under `build/components/<name>/` (its own
`Makefile` you can hand-edit — add a peripheral model, extra flags — that survives every
future `cosim build`; see [How `cosim build` works](#how-cosim-build-works)).
`cosim run` boots QEMU on its own; name components to couple them to it (each its own
remote-port socket), or `cosim run rtl [COMPONENT]` to run one standalone with no QEMU
at all.

Under the hood this drives the `cosim-gen-circt`/`cosim-extract` MLIR passes (see
[`../cosim-gen-circt/README.md`](../cosim-gen-circt/README.md)) and the `libsystemctlm-soc`
remote-port TLM library.

## Install

```sh
pip install -e .
```

This installs the `cosim` console script (`pyproject.toml`'s `cosim = cosim.cli:main`
entry point). It does **not** install the external toolchain `cosim` drives — firtool/
arcilator (CIRCT), `cosim-extract` (this repo's `cosim-gen-circt/build`), verilator, `dtc`,
`qemu`, and SystemC are resolved separately at run time; see
[Toolchain resolution](#toolchain-resolution) below, and run `cosim doctor` to check
what's found.

## Quick start

```sh
cd ../example
cosim build -C cosim.json
```

This extracts 7 real peripherals from a real ~400K-line Rocket-Chip SoC, each into its
own `build/components/<name>/build-<backend>/sim` binary. See
[`example/README.md`](../example/README.md) for
what each component declares, and why running these standalone (`cosim run rtl`) needs
QEMU coupling to actually exercise them.

## `cosim.json` reference

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
      "extra_args": ["+tx_uart=1"] }
  ],
  "toolchain": {
    "firtool": "/opt/firtool/bin/firtool",
    "qemu": "/opt/qemu-fdt/riscv-bin/qemu/bin/qemu-system-riscv64"
  }
}
```

Only `design.input` and `design.supported_backends` are required; everything else is
optional and defaults to "whole design, no QEMU coupling."

### `design`

- **`input`** (required) — `.fir`, or `.hw.mlir`/`.mlir` to skip the firtool lowering
  step entirely (the file is used as-is).
- **`supported_backends`** (required) — a non-empty list of `"arcilator"`/`"verilator"`,
  the backend(s) *this design* actually lowers on. `cosim build` builds a unit for every
  one listed; `cosim run --backend` picks which built variant to execute (default: the
  first one listed). No default value on purpose — some designs only lower on one backend
  (e.g. async-reset registers arcilator can't lower), so this isn't safe to guess at. See
  [Backend vs. run mode](#backend-vs-run-mode).
- **`dts`** — base platform device tree. Only needed to generate the QEMU overlay
  (`qemu`/`cosim` run modes); a design with no bus/interrupt IO can be built and run in
  `rtl` mode without it. The QEMU-side dts mapping lives on the owning component's own
  `compat`/`dts_path` fields (see [`components`](#components) below), not here — there's
  no separate mapping file or field to keep in sync.
- **`seqmem`** — passed to firtool as `--repl-seq-mem-file` (sequential memory
  extraction config).
- **`annotations`** — passed to firtool as `--annotation-file`.

### `qemu`

- **`elfs`** — ELF files passed to **QEMU** via `-device loader`, one per entry, in
  order (typically a bootrom followed by a test image). These are distinct from
  `soc_rtl.extra_files`: these are loaded into QEMU's memory view at startup,
  `soc_rtl.extra_files` are baked into the RTL model at firtool-lowering time.
- **`extra_args`** — extra arguments appended verbatim to every `qemu`
  invocation (plain boot and coupled) — an escape hatch for QEMU flags `cosim` has no
  dedicated knob for.

Both only seed `build/qemu/Makefile`'s `ELFS`/`QEMU_ARGS` the first time `cosim build`
scaffolds it (see [How `cosim build` works](#how-cosim-build-works)) — `cosim run` always
shells out to that Makefile's `run-qemu`/`run-qemu-coupled` targets (`mk/qemu.mk`), so
editing them there afterwards takes effect without a `cosim.json` change or a rebuild,
the same way a component's own `Makefile` hooks do.

### Top-level build/run defaults

These sit at the top of `cosim.json`, alongside `design`/`qemu`/etc. — settings shared by
every build unit, not scoped to any one section:

- **`jobs`** — `make -jN` parallelism for the build. `cosim build` compiles the whole
  design as one make graph (design lowering, `libsystemctlm`, and every component's
  extract → lower → codegen → compile → link, for every `design.supported_backends`
  entry), so a higher `jobs` builds the components (and backends) concurrently. Defaults
  to all CPUs; `cosim build -j N` overrides it per invocation.
- **`sync_quantum`** — cycles each component's `sim` process runs between remote-port
  sync points with QEMU (`qemu`/`cosim` run modes). Too low wastes time context-switching
  to sync; too high coarsens device timing. Defaults to `1000`; a component's own
  `sync_quantum` overrides it for that component
- **`max_cycles`** — stop each RTL model after this many clock cycles instead of running
  forever. Defaults to `0` (unbounded); a component's own `max_cycles` overrides it for
  that component.
- **`extra_args`** — extra argv strings appended to every spawned sim binary invocation,
  after the positional sync_quantum/max_cycles slots. Read by verilator's plusargs
  scanning regardless of position; silently ignored by the arcilator backend. A
  component's own `extra_args` overrides this for that component.

### `soc_rtl`

Optional declaration for **the whole, un-extracted design's own build** - the pseudo-
component `cosim build` always builds alongside any declared `components[]` (see
[`components`](#components) below and [How `cosim build` works](#how-cosim-build-works)).
Without it, the whole design falls back to guessing its clock/reset port names by
suffix (`"clock"`/`"reset"`/`"rst"`) - `soc_rtl` lets you declare them explicitly instead,
the same way a `components[]` entry already does for an extracted peripheral.

It's shaped like a `components[]` entry, minus the fields that don't apply to it:

- **`interfaces`** — only `clock` and `reset` interfaces are allowed (see
  [`components`](#components) below for their shape); anything else is a `cosim.json`
  error.
- **`sync_quantum`**, **`max_cycles`**, **`extra_args`** — same meaning as the matching
  top-level field (see [Top-level build/run defaults](#top-level-buildrun-defaults)),
  overridden for the whole-design unit only, the same way a component overrides them for
  itself.
- **`extra_files`** — a list of already-built files staged into the build directory (by
  basename) *before* firtool runs. Use this for files an annotation references by a bare
  relative filename — e.g. a `MemoryFileInlineAnnotation` pointing `bootrom.mem` at a
  memory macro. **The tool does not do the ELF→mem conversion itself** — how you produce
  that file (`objcopy` flags, address offset, data width) is design-specific; write your
  own small script (see `../example/convert.sh` for a worked example) and
  point `extra_files` at its output. Components (see [`components`](#components) below)
  can contribute their own `extra_files` too — all lists are additive: there's one
  firtool call for the whole design, so a component's `extra_files` just documents which
  files it cares about, not a separate staging location.
- No `type`/`path` (there's nothing to extract - this *is* the whole design) and no
  `compat`/`dts_path`: the whole-design unit has no QEMU bus/interrupt coupling path
  (`build()`'s QEMU-overlay detection, the dtb generation, and `cosim run`'s coupled-run
  machinery only ever look at `components[]`) - setting a bus/interrupt/gpio interface
  under `soc_rtl` is a `cosim.json` error. Declare it as a `components[]` entry instead if
  you need bus/interrupt/gpio IO.

### `components`

A list of components to extract, each with structured IO. `type` is the peripheral's
FIRRTL/circuit module name (only used to keep it alive through whole-design firtool
lowering — see [How `cosim build` works](#how-cosim-build-works)); `path` is the instance
path to extract. `interfaces` declares *what the component's ports are*, by who's on the
other end of each wire — one entry per interface, each tagged with its own `"kind"`:

- **`{ "kind": "clock", "name", "freq_mhz" }`** (exactly one required) — `name` is the
  clock port as it appears in the peripheral's own FIRRTL (usually `"clock"`); `freq_mhz`
  is required - every clock declares its own, there's no project-wide default. It's also
  the anchor every other interface's instance prefix is derived from, which is why
  exactly one is required.
- **`{ "kind": "reset", "name", "active_low" }`** (at most one) — `name` is the reset
  port as it appears in the peripheral's own FIRRTL (usually `"reset"`); `active_low` is
  optional and defaults to `false` (active-high — the historical, only behavior before
  this field existed). Controls the generated `sim.cpp`'s startup reset sequence:
  active-high writes `true` then `false`, active-low writes `false` then `true`.
- **`{ "kind": "<protocol>", "prefix", "dir" }`** — a memory-mapped TLM bus wired to
  QEMU, keyed by protocol (`"tilelink"` today — see [Bus protocols](#bus-protocols)).
  `prefix` is the port prefix (e.g. `"auto_control_xing_in"`) — always a prefix, never a
  single exact port, since a bus protocol bundle always decomposes into several leaf
  ports (`_a_valid`, `_a_bits_opcode`, ...) sharing it; `dir` is `"slave"` (QEMU is
  master, the common case for a peripheral's control interface) or `"master"` (the
  peripheral is a DMA master). Slave buses are matched positionally against
  `compat`/`dts_path`'s node's own `reg` windows — a node with one bus needs just one
  `reg`/`reg-names` entry (the common case); a node with several buses needs one
  `reg`/`reg-names` entry per bus, in the same order the buses are declared here.
- **`{ "kind": "interrupt", "prefix"/"name", "dir" }`** — wired to QEMU as a remote-port
  wire. Exactly one of `prefix` or `name` is required: `prefix` matches this port plus
  any leaf ports under it (e.g. a bundled `_sync_0..N` vector — the common case for a
  diplomacy-derived config, since `cosim gen-config` can't tell from the diplomacy config
  alone whether a given interrupt is a bundle); `name` requires a single, already-exact
  extracted port and errors if it isn't one — use it once you've confirmed a given
  interrupt really is a single bit, to catch an accidental over-match. `dir` is `"out"`
  (the peripheral raises an IRQ — the common case) or `"in"` (the component *consumes*
  interrupt lines from elsewhere in the design — e.g. a PLIC's device IRQ inputs). Only
  `"out"` interrupts are matched positionally against `compat`/`dts_path`'s node's own
  `interrupts`/`interrupts-extended` property — that property describes what the node
  itself routes *out* to its interrupt-parent, never what feeds into it, so the *count*
  of `"out"`-direction interrupts must match the node (a mismatch means `compat`/
  `dts_path` points at the wrong node, or the RTL and dts disagree on how many interrupt
  lines this peripheral raises). `"in"`-direction interrupts aren't checked against the
  node at all — they're wired the same as `gpio` (see below), just labeled for clarity.
- **`{ "kind": "gpio", "prefix"/"name" }`** — also wired to QEMU (remote-port gpio
  wires), but *not* interrupt-routed — external I/O, not a PLIC source.
- **`compat`** (a dts `compatible` string) or **`dts_path`** (an explicit dts node path)
  — this component's own **QEMU-side dts binding**: the single existing node in
  `design.dts` it talks to. Only needed for `qemu`/`cosim` run modes, and only one of the
  two (compat is the common case; `dts_path` for when compat alone doesn't disambiguate).
  One node can carry several buses and several interrupts — that's *why* this is a
  component-level field and not repeated per interface: a dts node has exactly one
  `compatible` string, but can have multiple `reg`/`reg-names` windows and multiple
  `interrupts` cells.
- **`name`** — this component's identity everywhere except matching the real FIRRTL
  circuit: `build/components/<name>/`, `cosim run <name>`, `TOP_NAME` (`<name>_TOP`), the
  dtb/remote-port node name. Optional — defaults to `path`'s last hierarchy segment (the
  actual instance name in the design, e.g. `"uart_0"` from
  `"topDesign/topMod/uartClockDomainWrapper/uart_0"`), which is usually enough to tell
  apart multiple instances of the same `type`. Set it explicitly only if two components'
  derived names collide (`cosim build`/`cosim run` reject a collision with an error
  naming the offending components) or the derived one isn't descriptive enough.
- **`sync_quantum`**, **`max_cycles`**, **`extra_args`** — all optional, all override
  the matching top-level field (see
  [Top-level build/run defaults](#top-level-buildrun-defaults)) for this component only
  (omit to inherit the top-level default). **`extra_files`** is also optional but
  **additive**, not overriding — see
  [`soc_rtl.extra_files`](#soc_rtl) above.

**Names are the bare port name from the peripheral's own FIRRTL** — you do *not* prefix
them with the instance hierarchy (`uart_0.`, `topMod.dmx512_0.`, …) that `cosim-extract`
adds to the extracted ports; the tool strips that common prefix for you.

**Undeclared ports are not an error.** Anything you don't name (e.g. a uart's `txd`/`rxd`,
an ethernet MAC's `gmii`) is a *user-model connection point*: it's exposed in the
generated `sim.cpp` as a plain `sc_signal` for you to wire your own SystemC model to. It
does **not** talk to QEMU. Only the interface kinds above do, which is why only they need
declaring — device pins ride along as passthrough automatically.

Internally `interfaces` just derives the `cosim-extract --port` regex (previously the
hand-written `io` field, then the separate `clock`/`reset`/`buses`/`interrupts`/`gpio`
fields) and drives the codegen's port classification — see
[`cosim/interfaces/`](cosim/interfaces/), one `Interface` subclass per `"kind"`. The old
opaque `io` regex field, and the old five-fields shape, are both gone — a component still
carrying either is rejected with an error pointing at this section.

`cosim build` always builds the whole, un-extracted design as its own standalone model
too (ports classified by name heuristics since there's no per-component declaration for
it) — alongside any declared components, not instead of them, under
`build/components/<TopModuleName>/build/sim` just like any real component (it's a
pseudo-component with no `--path`/`--port` to extract by). `cosim run rtl` targets this
whole design by default; pass a component name (`cosim run rtl <name>`) to run one of the
extracted components standalone instead. Leaving `components` empty (or omitting it)
just means there's nothing to extract — the whole design is then the *only* model.

Don't want to hand-write this list for a large design? `cosim gen-config` derives it
from a diplomacy config (see [CLI reference](#cli-reference)).

### Bus protocols

Each bus interface's `"kind"` selects a `BusInterface` subclass from the registry in
[`cosim/interfaces/`](cosim/interfaces/) (`INTERFACE_KINDS`). Only `"tilelink"` — in its
own file, [`cosim/interfaces/tilelink.py`](cosim/interfaces/tilelink.py) — is wired
end-to-end today. A `BusInterface` subclass bundles everything protocol-specific in one
place — the boundary signal layout, the TLM bridge class names, the bridge socket
member, and the bridge template types — so **adding a new bus type (e.g. AXI, whose
bridge headers already ship in the `libsystemctlm-soc` submodule) is one new subclass**,
not edits scattered across the codegen. The SystemC emission itself
(`codegen/templates/*.j2`, rendered via Jinja2) reads only the interface object, never a
hard-coded `"tilelink"`.

Not every field of a bus protocol's signal layout has to exist on a given peripheral's
actual extracted ports. TileLink's `a_param`/`a_corrupt` and all of the D-channel
metadata (`d_param`/`d_sink`/`d_denied`/`d_data`) are optional: some real peripherals
negotiate a narrower bus that never carries them (e.g. a Rocket Chip CLINT/PLIC's
control bus has no `a_param`/`a_corrupt` at all, and an error-responder device like
`TLError` has no `d_data`) because they're tied to a constant upstream and diplomacy
elides the wire entirely. A missing optional field is simply left unbound in the
generated `sim.cpp`/arcilator wrapper (the bridge's own signal keeps its default reset
value) instead of erroring — only the fields that matter for basic addressing/framing
(`a_valid`/`a_opcode`/`a_size`/`a_source`/`a_address`/`a_mask`/`a_data`, `d_ready` on the
A-channel; `a_ready`/`d_valid`/`d_opcode`/`d_size`/`d_source` on the return path) are
required.

### `toolchain`

Per-field overrides: `firtool`, `arcilator`, `cosim_extract`, `cosim_plugin`, `systemc`,
`systemc_include`, `systemc_lib`, `qemu`. Anything not set here falls through to the
resolution order below.

## CLI reference

- **`cosim init [dir] [--backend arcilator|verilator] [-f]`** — scaffold a starter
  `cosim.json` in `dir` (default: cwd).
- **`cosim gen-config <diplomacy.json> [-o cosim.json] [--dts board.dts]`** — derive a
  structured `components` list from a design's `*.diplomacy.json` config (one entry per
  labeled module, classifying its `interfaces` - clock/reset/bus/interrupt - from the
  config's interface tags). `gpio` has no diplomacy interface type, so it's left for
  hand-editing. With `--dts`, also derives each component's `dts_path` mapping by
  matching its bus interfaces' diplomacy address against the dts's node addresses - a
  convenience, not required.
- **`cosim build [-C cosim.json] [-j N]`** — run the full pipeline: lower the design,
  extract and lower each component, link each component's own
  `build/components/<name>/build-<backend>/sim` for *every* backend in
  `design.supported_backends`, *and* the whole, un-extracted design's own (alongside any
  declared components - not instead of them). One top `build/Makefile` builds the shared
  prerequisites (design lowering, `libsystemctlm`) then recurses into each unit's own
  `build/components/<name>/Makefile`, which in turn builds every supported backend itself
  - `-j N` (or top-level `jobs`) builds every component and backend concurrently;
  defaults to all CPUs. See [How `cosim build` works](#how-cosim-build-works).
- **`cosim run [rtl] [COMPONENT ...] [--all] [--backend arcilator|verilator] [-C cosim.json] [-j N]`** -
  put `-C`/`-j`/`--all`/`--backend` either right after `run` or at the very end, not
  between `rtl` and a component name - `argparse` can't always resolve that split.
  - `--backend` — which built backend to run (must be one of `design.supported_backends`
    in `cosim.json`; default: the first one listed). `cosim build` already built every
    one of them, so this just selects which one's `sim` binary this particular run uses.
  - No arguments — a plain QEMU boot straight off `design.dts`: no remote-port overlay,
    no RTL coupling, no `-machine-path` - nothing to wait on.
  - One or more component names (e.g. `cosim run uart_0 gpio_0`) — couple QEMU to
    *just those* components: their own dtb overlay nodes and their own `sim` processes,
    not any of the others declared in `cosim.json`. (Using the all-components overlay
    here would leave QEMU waiting forever on sockets for every other coupled component
    that was never spawned.)
  - `--all` — couple QEMU to *every* component that has bus/interrupt IO at once: one
    `sim` process per such component, each its own remote-port channel, all sharing one
    QEMU instance. Mutually exclusive with naming components or with `rtl`.
  - `rtl [COMPONENT]` — run a `sim` standalone, no QEMU at all. No component name runs
    the whole design's own `sim`; one component name (at most one) runs that extracted
    component's own sim instead. Run it again yourself for another target - the tool
    doesn't orchestrate multiple `rtl` runs together.
  - `-j N` — `make -jN` when regenerating the dtb (default: top-level `jobs`, or all
    CPUs). Doesn't affect the spawned `sim` binaries themselves.
  - `-l`/`--list` — print the component names declared in `cosim.json` (each tagged
    `qemu-coupled` or `rtl-only`, with the exact `cosim run` invocation for it, plus its
    `type` in brackets), then exit without running anything. Mutually exclusive with
    everything else above.
  - The dtb QEMU boots from is regenerated fresh on every `cosim run` - not reused from
    whatever `cosim build` last wrote - so a component's `compat`/`dts_path`/`interfaces`
    or `design.dts` edits take effect without a full rebuild. Each coupled component's own
    overlay fragment is (re)written to `build/components/<name>/overlay.dts` (shared
    across backends - the overlay only depends on bus/interrupt/gpio classification, not
    on which backend built the component); the top-level `build/cosim.dts` is just a thin
    `/include/` of `design.dts` plus exactly the fragments for the components this
    particular run couples (see
    [How `cosim build` works](#how-cosim-build-works)).
  - Combined stdout/stderr is teed to a `run.log` (like `... 2>&1 | tee run.log`) as well
    as the terminal, so a run's console output survives after the terminal scrolls past
    it. For `qemu`/`cosim` modes that's QEMU's own output, at the top-level
    `build/run.log`. For `rtl` mode it's that one sim binary's output, at
    `build/components/<name>/build-<backend>/run.log` - the same path `make run`/`make
    run-coupled` (below) write to for the same binary, so there's one canonical log per
    component-backend pair regardless of which entry point ran it.
- **`cosim clean [-C cosim.json] [--all]`** — remove build artifacts: each unit's
  `config.mk`, `overlay.dts`, and nested `build/` (the compiled outputs), plus the shared
  top-level ones (`design.hw.mlir`, `systemctlm/`, the top `Makefile`, dtb). **Preserves** every
  unit's own scaffolded `Makefile`, its `sim.cpp`, and any hand-added sources (e.g.
  `periph.cpp`) - those are yours, not `cosim build`'s. Pass `--all` to also wipe those
  (loses hand edits) - equivalent to `rm -rf build`.
- **`cosim doctor [-C cosim.json]`** — print resolved toolchain paths and flag anything
  missing.

## How `cosim build` works

Each component (and the whole design, as a pseudo-component) is a **standalone, editable
mini-project** under its own `build/components/<name>/` - one directory shared by every
backend in `design.supported_backends`: the editable/generated top-level files
(`Makefile`, `config.mk`, `sim.cpp`, and - only when `arcilator` is supported -
`gen-arc-<name>.cpp`/`.h`/`A<Model>.h`) don't depend on which backend built them (`sim.cpp`
picks its backend via `#ifdef USE_ARCILATOR`/`USE_VERILATOR` at compile time - see
[`codegen/sim_main.py`](cosim/codegen/sim_main.py)/[`templates/sim_cpp.j2`](cosim/codegen/templates/sim_cpp.j2)).
Only the actual compiled output forks per backend, into its own `build-<backend>/` -
extraction output itself differs by backend (arcilator's `--remove-sv` HW vs. verilator's
combined HW+state-json), so those can't be shared:

```
build/
  Makefile                     # generated: shared prereqs (design.hw.mlir, libsystemctlm), then recurses
  design.hw.mlir               # shared, built once
  systemctlm/libsystemctlm.a   # shared, built once
  qemu/
    Makefile                    # scaffolded ONCE - yours to edit (ELFS/QEMU_ARGS), never overwritten again
    config.mk                   # regenerated every `cosim build` - do not edit
  components/
    uart_0/                      # instance name of the TLUART component (path's last segment)
      Makefile                 # scaffolded ONCE - yours to edit, never overwritten again
      config.mk                # regenerated every `cosim build` - do not edit
      sim.cpp                  # generated once, shared across backends (unless you set GENERATE_SIM_CPP := 0)
      periph.cpp                # (optional) your own SystemC peripheral model
      overlay.dts                # QEMU overlay fragment - also shared, backend-independent
      build-verilator/           # only populated if "verilator" is in design.supported_backends
        uart_0.hw.mlir  uart_0.json  vsrc/  verilator/  sim.o  sim
      build-arcilator/            # only populated if "arcilator" is in design.supported_backends
        uart_0.hw.mlir  uart_0.json  uart_0.o  gen-arc-uart_0.o  sim.o  sim
    RocketSoC/                    # the whole design - same shape as any component
      ...
```

`project.py` renders **one top `build/Makefile`** that builds the shared prerequisites
(design lowering, `libsystemctlm`) then recurses — `+$(MAKE) -C components/<name>` — into
each unit's own `Makefile`. One `cosim build` is still one `make` process end to end (`-j
N` parallelizes across every component and backend), but the per-unit rules
([`mk/component.mk`](mk/component.mk)) are plain, readable, single-component Make - no
unrolled multi-component codegen to wade through. Both backends' rule blocks are always
defined in there (harmless when unused - Make only evaluates a rule if something actually
depends on it); `SUPPORTED_BACKENDS` (from `config.mk`) is what `all` consults to know
which `build-<backend>/sim` targets this particular project actually wants built. A
separate, run-time-only `BACKEND` variable (defaulting to the first supported one) selects
which one `make run`/`run-coupled`/`sim` executes - exactly the mechanism `cosim run
--backend` drives underneath (`make -C components/<name> run BACKEND=<selected>`).

**Editing a component.** Its `Makefile` is created once and is yours from then on -
`cosim build` never overwrites or deletes it again (only `cosim clean --all` does). It
`include`s the regenerated `config.mk` (tool paths, `--path`/`--port`, backend - anything
that comes from `cosim.json`) plus your own hook variables:

- **`EXTRA_SRCS`** — extra `.cpp` files (e.g. your own `periph.cpp`) compiled and linked
  into `sim`. The generated `sim.cpp` calls a weak `cosim_user_wire(Top&)` hook once,
  right where it lists the undeclared "connect your own SystemC model" ports (`Top`'s
  members are public) - define a strong `void cosim_user_wire(Top &top) { ... }` in your
  `EXTRA_SRCS` file to bind them; the weak no-op default is used if you don't.
- **`EXTRA_CXXFLAGS`**, **`EXTRA_LDLIBS`** — extra compile/link flags.
- **`SYNC_QUANTUM`**, **`RUN_ARGS`** — used by `make run`/`make run-coupled` (below);
  seeded once from `cosim.json`'s top-level/component `sync_quantum` when the unit's
  Makefile is first scaffolded, then a plain hand-editable `?=` default afterwards.
- **`GENERATE_SIM_CPP`** — set to `0` to hand-own `sim.cpp` entirely (stops regeneration).
- Tracing — three **independent, combinable** knobs, not one choice:
  - **`VM_TRACE_VCD`**/**`VM_TRACE_FST`** — set to `1` for verilator's own *native* tracer,
    with full internal RTL signal visibility (hooked directly onto the verilated
    submodule, not just `Top`'s own ports). `verilator` backend only; mutually exclusive
    with each other (VCD wins if both are `1`); a build-time `#error` under `arcilator`
    (no native tracer there to pick a format from). Setting either also passes
    `--trace-vcd`/`--trace-fst` to verilator itself (a compile-time define alone doesn't
    instrument the model - verilator needs to know at *verilate* time), and uses its
    native `VerilatedVcdSc`/`VerilatedFstSc` SystemC integration. Output:
    `verilator_sysc_native.{vcd,fst}`.
  - **`ARC_TRACE`** — set to `1` to enable arcilator's own separate internal tracer.
    `arcilator` backend only; its own file output, handled entirely inside the generated
    `A<Model>` wrapper.
  - **`SYSC_TRACE`** — set to `1` for a generic SystemC `sc_trace_file` VCD of `Top`'s own
    declared ports (every clock/reset/interrupt/gpio/other/bus signal - see the generated
    `Top::trace()`) - a boundary-level view, not internal RTL state. Works identically for
    either backend, and independently of the knobs above - e.g. `VM_TRACE_VCD=1
    SYSC_TRACE=1` together gives you both an internal-signals VCD *and* a boundary-only
    VCD, in separate files. Output: `{verilator,arcilator}_sysc.vcd`.
  - **`VM_COVERAGE`** — set to `1` for verilator's own line/toggle coverage collection.
    `verilator` backend only; independent of and combinable with everything above (like
    the trace knobs, also passes `--coverage` to verilator itself at verilate time - a
    compile-time define alone isn't enough to instrument the model). Output: `coverage.dat`
    (`verilator_coverage -write-info coverage.dat.info -annotate <dir> coverage.dat` turns
    that into an annotated-source report).

All five default to `0` in both `mk/component.mk` and the scaffolded per-component
`Makefile` - set them there (survives future `cosim build`s) or one-off on the command
line, e.g. `cosim build` doesn't take a tracing flag itself, so `make -C
build/components/uart_0 VM_TRACE_VCD=1` (or edit the component's own `Makefile`) is how
you turn tracing on.

Each component dir is also independently buildable: `cd build/components/uart_0 && make`
builds just that one; `make run` runs its `sim` standalone (only meaningful for a
component with no bus/interrupt/gpio IO, e.g. the whole design or a bus-less component -
one that *does* have such IO expects a QEMU remote-port socket as its first argument
instead of a cycle count, so use `cosim run <name>` for those); `make run-coupled`
runs it against a QEMU peer you've already started yourself. Both tee the sim binary's
combined stdout/stderr to `build/run.log` (like `cosim run` does), in addition to the
terminal.

The steps in each unit's own build:

1. `firtool <input> --ir-hw […]` → `design.hw.mlir` (skipped if the input is already
   `.hw.mlir`; done once at the top, shared by every unit).
2. `cosim-extract --path=<path> --port=<io> --top-name=<name>_TOP` runs the full
   extraction pipeline (see [`cosim-gen-circt/README.md`](../cosim-gen-circt/README.md)) - or, for
   the whole-design pseudo-component (no `--path`), the equivalent `cosim-gen-opt`
   cleanup pipeline directly.
3. Backend lowering — orthogonal to run mode (see below):
   - **arcilator:** `cosim-extract --remove-sv` → `arcilator --state-file` → `opt`/`llc`
     → `.o`; codegen emits a C wrapper plus a hand-written SystemC wrapper (`A<TopName>`).
   - **verilator:** `cosim-extract --state-json` → `firtool --split-verilog` →
     `verilator -sc --build` → `.a`; verilator's own generated header (`V<TopName>`) is
     already SystemC-compatible, no wrapper needed.
4. A codegen recipe (`python -m cosim.codegen.main`) renders `sim.cpp` from a Jinja2
   template (`codegen/templates/`): one SystemC `Top` wrapping just that one model, its
   own `QemuTLM` if it has bus/interrupt/gpio IO, buses wired through the
   registry-selected TLM bridge, interrupts+gpio wired to the remote-port wire channel,
   and any undeclared ports left as user-model connection points (see `EXTRA_SRCS`
   above). Links its own `build/sim` - components are never assembled into one shared
   binary. Classifies each port from the matching `components[]` declaration
   (`--component <name>`) or, for the whole design, `soc_rtl` if declared (`--soc-rtl`) -
   otherwise it falls back to guessing clock/reset by name suffix.

After all units build, `build/cosim_components.json` records which components have
bus/interrupt/gpio IO (the manifest `cosim run --all` reads to know what to couple). The
actual QEMU device-tree overlay isn't generated here - `cosim run` builds it fresh on
every invocation (see [CLI reference](#cli-reference)), using each component's own
`compat`/`dts_path` (see [`components`](#components) above) to write **each coupled
component's own standalone
overlay fragment** - one independent remote-port node per component (own `chrdev-id`,
own local bus/wire indices) - to that component's own
`build/components/<name>/overlay.dts`. `build/cosim.dts`, the file QEMU actually boots
from (compiled to `cosim.dtb`), is then just `design.dts` plus a `/include/` of exactly
the overlay fragments for whichever component(s) this specific run needs - not a
monolithic regenerated overlay, so `qemu run <name>` never pulls in a component it isn't
actually coupling.

## Backend vs. run mode

These are orthogonal:

- **Backend** (`arcilator` | `verilator`) decides *how each component model is
  generated* — arcilator lowers through CIRCT's `arc` dialect to a `.o` behind a
  hand-written SystemC wrapper; verilator compiles generated Verilog straight to a
  SystemC-compatible `.a`, no wrapper needed. `cosim build` builds every backend in
  `design.supported_backends` for every unit (see
  [How `cosim build` works](#how-cosim-build-works)); `cosim run --backend` picks which
  one a given run actually executes.
- **Run mode** (`rtl` | `qemu` | `cosim`) decides *what drives each component's `sim`
  binary* — standalone, alongside QEMU with no coupling, or fully coupled. Concretely,
  `cosim` mode starts each qemu-coupled component as
  `build/components/<name>/build-<backend>/sim unix:$MACHINEPATH/qemu-rport-<name>...`
  (one process per component, one socket each) and one shared
  `qemu -M riscv-fdt -hw-dtb <cosim.dtb> -machine-path $MACHINEPATH`; `rtl` mode runs a
  `sim` (the whole design's, or one extracted component's) standalone with no coupling
  at all.

Either backend works with any run mode; the same `sim` binary interface serves all
three — an arcilator-backed model is just as usable standalone (`rtl`) as it is coupled
to QEMU (`cosim`).

## Toolchain resolution

For each tool, `cosim` resolves in this order (see `cosim/toolchain.py`; no personal
paths are hardcoded anywhere in this chain):

1. `toolchain.<name>` in `cosim.json`.
2. An environment variable, one per tool - `FIRTOOL`, `ARCILATOR`, `OPT`, `LLC`,
   `EXTRACT` (for `cosim_extract`), `COSIM_GEN_OPT`, `COSIM_PLUGIN`, `VERILATOR`, `DTC`,
   `QEMU`, `SYSTEMC_INCLUDE`, `SYSTEMC_LIB` (see `_TOOL_SPECS` in `cosim/toolchain.py`
   for the authoritative list - the names aren't a uniform `COSIM_<NAME>` pattern).
3. `cosim_extract`/`cosim_gen_opt`/`cosim_plugin` additionally fall back to this
   installed package's own `cosim-gen-circt/build/{bin,lib}` (relative to wherever
   `cosim-gen-cli` itself is installed, not a fixed path). Every other tool skips
   straight to $PATH.
4. `$PATH` (not applicable to `systemc_include`/`systemc_lib` - see below).

`systemc_include`/`systemc_lib` are directories, not single binaries, and are resolved
independently (a distro package like apt's `libsystemc-dev` splits headers into
`/usr/include` and the library into `/usr/lib/<triplet>` - no single directory has
both). Each falls back to `<prefix>/include` / `<prefix>/lib` if you instead set a
single-prefix `systemc` / `COSIM_SYSTEMC` / `SYSTEMC_HOME` (a source-built SystemC
install normally has that shape). Run `cosim doctor` to see what was actually found
before running `build`.

## Examples

- [`example/`](../example/) — the sole example and
  de-facto integration test: 7 real peripherals extracted from a real ~400K-line
  Rocket-Chip SoC. `design.supported_backends` lists both `verilator` and `arcilator` -
  this design has historically used async-reset registers arcilator couldn't lower, so
  if `cosim build` fails on the arcilator unit specifically, drop it back to just
  `["verilator"]`. Exercises the structured schema (typed buses, interrupts, gpio,
  user-model `other` ports) end to end, with `design.dts` and each component's own
  `compat` mapping wired up to the design's own real dts. `cosim build`,
  `cosim run rtl` (the whole design or
  `maskROM`, the one bus-less component), and a plain `cosim run` (no RTL
  coupling) all work; coupling any real component (`cosim run uart_0`, or
  `cosim run --all` for all of them) gets QEMU all the way to its monitor prompt with
  every sim process connected before hitting an apparent bug in the pre-built QEMU
  binary's own remote-port write path - see that example's README for the full story.
