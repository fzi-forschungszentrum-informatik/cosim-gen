# Builds bootrom.elf and simram.elf from src/ with clang/lld (no gcc - matches
# the project's Dockerfile, which no longer installs one), converts them to
# the .mem files cosim.json's MemoryFileInlineAnnotation loads, and can drive
# `cosim build` to extract+build the whole design from them.

CC      := clang
DTC     := dtc
OBJCOPY := llvm-objcopy

CFLAGS  := --target=riscv64 -march=rv64gc -mabi=lp64 -mcmodel=medany \
           -O2 -Wall -nostdlib -static -fno-common -g -fuse-ld=lld

BUILD   := sw_build

.PHONY: all mem clean

all: RocketSoC.hw.mlir mem

# The design input to `cosim build` - checked in xz'd to keep the repo small.
RocketSoC.hw.mlir: RocketSoC.hw.mlir.xz
	xz -dk $<

$(BUILD)/devicetree.dtb: RocketSoC.dts
	@mkdir -p $(BUILD)
	$(DTC) -O dtb -o $@ $<

$(BUILD)/devicetree.dts.o: $(BUILD)/devicetree.dtb
	$(OBJCOPY) -I binary -O elf64-littleriscv --binary-architecture riscv:rv64 $< $@

$(BUILD)/bootrom.elf: src/bootrom/boot.S src/bootrom/bootrom.lds $(BUILD)/devicetree.dts.o
	$(CC) $(CFLAGS) -T src/bootrom/bootrom.lds \
	    -o $@ src/bootrom/boot.S $(BUILD)/devicetree.dts.o

$(BUILD)/simram.elf: src/test/start.S src/test/main.c src/test/test.lds
	@mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -Wl,--entry=_prog_start -T src/test/test.lds \
	    -o $@ src/test/start.S src/test/main.c

$(BUILD)/bootrom.mem: $(BUILD)/bootrom.elf
	$(OBJCOPY) -O binary $< $(BUILD)/bootrom.bin
	od -An -tx4 -w4 -v $(BUILD)/bootrom.bin | tr -d ' ' > $@
	rm -f $(BUILD)/bootrom.bin

$(BUILD)/simram.mem: $(BUILD)/simram.elf
	$(OBJCOPY) -O binary $< $(BUILD)/simram.bin
	od -An -tx8 -w8 -v $(BUILD)/simram.bin | tr -d ' ' > $@
	rm -f $(BUILD)/simram.bin

mem: $(BUILD)/bootrom.mem $(BUILD)/simram.mem

clean:
	rm -rf $(BUILD)
	rm RocketSoC.hw.mlir
