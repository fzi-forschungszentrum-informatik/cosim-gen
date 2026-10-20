# RocketSoC example

Example for [`cosim`](../cosim-gen-cli/README.md) of a full Rocket-Chip-based SoC (`RocketSoC`, ~400K-line `.fir`).

## License

Based on RocketChip; licensed under [`LICENSE.Berkley`](LICENSE.Berkley) and
[`LICENSE.SiFive`](LICENSE.SiFive).

## Setup

- `cosim` and its toolchain installed (see [`../README.md#install`](../README.md#install)); run
  `cosim doctor -C cosim.json` to check it.
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
fields and
[`../cosim-gen-cli/README.md#build-output`](../cosim-gen-cli/README.md#build-output)
for what the build writes per component.
