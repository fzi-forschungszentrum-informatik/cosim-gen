#===-------------------------------------------------------------------------===
# The shared %.dtb rule, plus the run-qemu/run-qemu-coupled targets `cosim
# run` shells out to (build/qemu/Makefile includes this - see project.py's
# _QEMU_MAKEFILE_SCAFFOLD). DTB/LOG/MACHINE_PATH are per-invocation and
# always passed on the `make` command line (like SOCK/BACKEND are for
# mk/component.mk's run-coupled) - only QEMU_ARGS/ELFS are hand-editable
# `?=` hooks, seeded once from cosim.json's qemu.extra_args/qemu.elfs when
# build/qemu/Makefile is first scaffolded.
#===-------------------------------------------------------------------------===

DTC             ?= dtc
# Directory holding the base platform dts (cosim.json's design.dts) that the
# generated cosim overlay /include/s - dtc needs it (and anything *it*
# /include/s) on the search path even when there's no qemu-boards/ dir.
DTS_INCLUDE_DIR ?=

ifneq ($(strip $(BOARD_DIR)),)
-include $(BOARD_DIR)/board.mk
endif

%.dtb: %.dts
	$(DTC) $(if $(BOARD_DIR),-i $(BOARD_DIR)) $(if $(DTS_INCLUDE_DIR),-i $(DTS_INCLUDE_DIR)) $< -o $@

QEMU_ARGS       ?= -serial mon:stdio -display none
                            # extra qemu flags, appended after the ELF loaders -
                            # an escape hatch for anything project.py doesn't have a dedicated knob for
ELFS            ?=          # ELF files passed to QEMU via -device loader, in order (e.g. bootrom, test image)
SYNC_QUANTUM    ?= 1000    # max ns between QEMU<->remote-port syncs (run-qemu-coupled only) -
                            # matches Config.sync_quantum's own default; project.py's _run_coupled
                            # passes the real per-component value(s) actually in play instead

# bash+pipefail, scoped to just these two targets: otherwise the pipeline's
# exit status is tee's, not qemu's, so a qemu crash would look successful to
# `cosim run` (which checks this recipe's own exit code) - same reasoning as
# mk/component.mk's run/run-coupled.
run-qemu run-qemu-coupled: SHELL := /bin/bash
run-qemu run-qemu-coupled: .SHELLFLAGS := -eu -o pipefail -c

.PHONY: run-qemu run-qemu-coupled

# Plain boot, no RTL coupling: design.dts as-is (no remote-port overlay)
run-qemu:
	$(QEMU) -M riscv-fdt -hw-dtb $(DTB) $(foreach e,$(ELFS),-device loader,file=$(e)) $(QEMU_ARGS) 2>&1 | tee $(LOG)

# Coupled to the sim processes already listening on $(MACHINE_PATH)'s
# qemu-rport-<name> sockets (see project.py's _run_coupled). -sync-quantum
# is set explicitly rather than left to remote-port's own device-level
# default (see qemu-fdt/system/vl.c's global_sync_quantum and
# hw/core/fdt_machine.c's fdt_create_generic_qdev, which only applies a
# default to each remote-port device when this global flag is non-zero).
run-qemu-coupled:
	$(QEMU) -M riscv-fdt -hw-dtb $(DTB) -machine-path $(MACHINE_PATH) -sync-quantum $(SYNC_QUANTUM) $(foreach e,$(ELFS),-device loader,file=$(e)) $(QEMU_ARGS) 2>&1 | tee $(LOG)
