# CoSim HW generation out-of-tree passes for circt
Based on https://github.com/uenoku/firtool-standalone-plugin

Part of [cosim-gen](../README.md) — if you want to build and run a
co-simulation rather than work on the passes themselves, see
[`../cosim-gen-cli/README.md`](../cosim-gen-cli/README.md) instead.

## Building

Requires a CIRCT install with `firtool`'s `bin/` on `PATH` (`find_package(CIRCT REQUIRED
CONFIG)` locates `lib/cmake/circt` relative to it — pass `-DCIRCT_DIR=<circt
install>/lib/cmake/circt` explicitly if that resolution fails). See
[`../INSTALL.md`](../INSTALL.md) for getting CIRCT and the rest of the toolchain in
place if you don't have it already.

```sh
mkdir build
cd build
cmake .. -GNinja \
    -DCMAKE_CXX_COMPILER=clang++ \
    -DCMAKE_C_COMPILER=clang \
    -DLLVM_ENABLE_ZSTD=Off
ninja check-cosim-gen
```

## Usage

### Standalone optimizer

```sh
./build/bin/cosim-gen-opt --hw-subgraph=path=/topDesign/topMod design.mlir
```

### Plugin for circt-opt

```sh
circt-opt design.mlir --load-pass-plugin=./build/lib/CosimGenPlugin.so \
  --pass-pipeline='builtin.module(hw-subgraph{path=/topDesign/})'
```

### Packaged per-component extraction (`cosim-extract`)

```sh
./build/bin/cosim-extract design.hw.mlir -o component.hw.mlir \
  --path=/topDesign/topMod --port='.*' --top-name=MY_COMPONENT
```

Optional flags for backend-specific lowering prep:
- `--remove-sv` — strip `sv` dialect asserts/prints (needed before lowering with
  arcilator).
- `--state-json=<path>` — emit the extracted module's bit-level IO layout (needed for
  the verilator path's state JSON).
