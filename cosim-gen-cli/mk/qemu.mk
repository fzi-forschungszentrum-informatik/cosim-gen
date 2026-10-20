#===-------------------------------------------------------------------------===
# The %.dtb rule and the QEMU run targets, included by build/qemu/Makefile.
# DTB/LOG/MACHINE_PATH are passed on the command line.
#===-------------------------------------------------------------------------===

# Fallbacks when common.mk has no resolved tool.
DTC             ?= dtc
QEMU            ?= qemu-system-riscv64
# Directory of design.dts, for the overlay's /include/.
DTS_INCLUDE_DIR ?=

ifneq ($(strip $(BOARD_DIR)),)
-include $(BOARD_DIR)/board.mk
endif

%.dtb: %.dts
	$(DTC) $(if $(BOARD_DIR),-i $(BOARD_DIR)) $(if $(DTS_INCLUDE_DIR),-i $(DTS_INCLUDE_DIR)) $< -o $@

# Extra qemu flags, appended after the ELF loaders.
QEMU_ARGS       ?= -serial mon:stdio -display none $(QEMU_EXTRA_ARGS)
ELFS            ?=          # ELF files passed to QEMU via -device loader, in order (e.g. bootrom, test image)
SYNC_QUANTUM    ?= 1000    # max ns between QEMU<->remote-port syncs (run-qemu-coupled only)

run-qemu run-qemu-coupled: SHELL := /bin/bash
run-qemu run-qemu-coupled: .SHELLFLAGS := -eu -o pipefail -c

.PHONY: run-qemu run-qemu-coupled

# Plain boot, no RTL coupling.
run-qemu:
	$(QEMU) -M riscv-fdt -hw-dtb $(DTB) $(foreach e,$(ELFS),-device loader,file=$(e)) $(QEMU_ARGS) 2>&1 | tee $(LOG)

# Coupled to the sims listening on $(MACHINE_PATH). Without -sync-quantum,
# remote-port devices get no default quantum.
run-qemu-coupled:
	$(QEMU) -M riscv-fdt -hw-dtb $(DTB) -machine-path $(MACHINE_PATH) -sync-quantum $(SYNC_QUANTUM) $(foreach e,$(ELFS),-device loader,file=$(e)) $(QEMU_ARGS) 2>&1 | tee $(LOG)
