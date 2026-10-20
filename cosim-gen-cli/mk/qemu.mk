#===-------------------------------------------------------------------------===
# The %.dtb rule and the QEMU run targets, included by build/qemu/Makefile.
# DTB/LOG/MACHINE_PATH/DTS_INCLUDE_DIR and QEMU/DTC are passed on the command line.
#===-------------------------------------------------------------------------===

%.dtb: %.dts
	$(DTC) -i $(DTS_INCLUDE_DIR) $< -o $@

QEMU_ARGS := -serial mon:stdio -display none $(QEMU_EXTRA_ARGS)

run-qemu run-qemu-coupled: SHELL := /bin/bash
run-qemu run-qemu-coupled: .SHELLFLAGS := -eu -o pipefail -c

.PHONY: run-qemu run-qemu-coupled

# Plain boot, no RTL coupling.
run-qemu:
	$(QEMU) -M riscv-fdt -hw-dtb $(DTB) $(foreach e,$(ELFS),-device loader,file=$(e)) $(QEMU_ARGS) 2>&1 | tee $(LOG)

# Coupled to the sims listening on $(MACHINE_PATH). Without -sync-quantum,
# remote-port devices get no default quantum.
run-qemu-coupled:
	$(QEMU) -M riscv-fdt -hw-dtb $(DTB) -machine-path $(MACHINE_PATH) -pidfile $(MACHINE_PATH)/qemu.pid -sync-quantum $(SYNC_QUANTUM) $(foreach e,$(ELFS),-device loader,file=$(e)) $(QEMU_ARGS) 2>&1 | tee $(LOG)
