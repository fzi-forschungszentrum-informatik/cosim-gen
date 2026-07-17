#!/usr/bin/env bash
set -euo pipefail

step() { printf '\n\n=== %s ===\n' "$1"; }

cd example

step "Unpack design and build software"
make

step "Checking toolpaths"
cosim doctor

step "Building all components"
cosim build

step "Running QEMU (no RTL coupling)"
cosim run

step "Running SoC RTL standalone"
cosim run rtl

# seq.firmem.init is currently not supported in arcilator, so maskROM/ocm_bank0 skip it for now
components=(
    "uart_0                 verilator arcilator"
    "gpio_0                 verilator arcilator"
    "dmx512_0               verilator arcilator"
    "identRegs              verilator arcilator"
    "sethi21_0              verilator arcilator"
    "maskROM                verilator"
    "ocm_bank0              verilator"
)
for entry in "${components[@]}"; do
    read -r name backends <<< "$entry"
    for backend in $backends; do
    
        step "Running per-component $name with $backend"
        cosim run "$name" --backend="$backend"
    done
done

echo -e "\nall tests passed"
