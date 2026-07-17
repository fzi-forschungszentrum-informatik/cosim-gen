# RocketSoC example

Example for [`cosim`](../cosim-gen-cli/README.md) of a full Rocket-Chip-based SoC (`RocketSoC`, ~400K-line `.fir`).

## License

Based on RocketChip; licensed under [`LICENSE.Berkley`](LICENSE.Berkley) and
[`LICENSE.SiFive`](LICENSE.SiFive).

## Setup

- `cosim` installed (`pip install -e .` from [`../cosim-gen-cli/`](../cosim-gen-cli/)); run
  `cosim doctor -C cosim.json` to check its external toolchain is resolved.
- `make` — decompresses the checked-in `RocketSoC.hw.mlir.xz` and builds the firmware images
  under `sw_build/` from `src/` (see [`Makefile`](Makefile)). `make mem` alone rebuilds just
  the firmware.

## Build & run

```sh
cd example
make
cosim build -C cosim.json
```

Builds all components below for both `verilator` and `arcilator`; each `sim` binary lands
at `build/components/<name>/build-<backend>/sim`. `cosim.json` and `RocketSoC.dts` wire up
each component's interfaces and dts mapping — see
[`../cosim-gen-cli/README.md#components`](../cosim-gen-cli/README.md#components) for the
field reference and
[`../cosim-gen-cli/README.md#how-cosim-build-works`](../cosim-gen-cli/README.md#how-cosim-build-works)
for what the build actually does per component.
