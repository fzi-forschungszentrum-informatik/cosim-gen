#===-------------------------------------------------------------------------===
# Build rules of one unit, included by build/components/<name>/Makefile after
# config.mk. Sources are shared by all SUPPORTED_BACKENDS; build output goes to
# build-<backend>/. Both backend blocks are always defined, so their variables
# carry an _ARCILATOR/_VERILATOR suffix. The whole design is a unit with an
# empty COMPONENT_PATH.
#===-------------------------------------------------------------------------===

O_ARCILATOR := build-arcilator
O_VERILATOR := build-verilator

LIBRP_DIR := $(LIBSOC_DIR)/libremote-port

BASE_CPPFLAGS := -I $(RTLGEN_INC_DIR) -I $(LIBSOC_DIR) -I $(LIBRP_DIR) -I $(SYSTEMC_INCLUDE) \
                 -DTRACE=$(TRACE) -DSYSC_TRACE=$(SYSC_TRACE) -DVM_COVERAGE=$(VM_COVERAGE) \
                 -DSC_ALLOW_DEPRECATED_IEEE_API
SIM_CXXFLAGS := -Wall -O3 -g -std=$(SYSTEMC_STD) $(EXTRA_CXXFLAGS)
SIM_LDFLAGS  := -L $(SYSTEMC_LIBDIR) -Wl,-rpath,$(SYSTEMC_LIBDIR)
SIM_LDLIBS   := -lsystemc -lpthread -latomic $(EXTRA_LDLIBS)
COMPILE_ARCILATOR = $(CXX) -MMD $(BASE_CPPFLAGS) -DUSE_ARCILATOR=1 -I . $(SIM_CXXFLAGS)
COMPILE_VERILATOR = $(CXX) -MMD $(BASE_CPPFLAGS) -DUSE_VERILATOR=1 $(VERI_INCLUDES) $(SIM_CXXFLAGS)

# Objects are named by basename; vpath finds each source in its own directory.
vpath %.cpp $(sort $(dir $(EXTRA_SRCS)))
EXTRA_OBJS_ARCILATOR := $(patsubst %,$(O_ARCILATOR)/%.o,$(basename $(notdir $(EXTRA_SRCS))))
EXTRA_OBJS_VERILATOR := $(patsubst %,$(O_VERILATOR)/%.o,$(basename $(notdir $(EXTRA_SRCS))))

# The backend `sim`/`run`/`run-coupled` use; `all` builds every supported one.
FIRST_BACKEND := $(firstword $(SUPPORTED_BACKENDS))
BACKEND ?= $(FIRST_BACKEND)
SIM := build-$(BACKEND)/sim

.PHONY: all sim run run-coupled clean
all: $(foreach b,$(SUPPORTED_BACKENDS),build-$(b)/sim)

sim: $(SIM)

$(O_ARCILATOR) $(O_VERILATOR):
	mkdir -p $@
clean:
	$(RM) -r $(O_ARCILATOR) $(O_VERILATOR)

STATE_arcilator := $(O_ARCILATOR)/$(COMPONENT_NAME).json
STATE_verilator := $(O_VERILATOR)/$(COMPONENT_NAME).json

ifeq ($(GENERATE_SIM_CPP),1)
sim.cpp: $(STATE_$(FIRST_BACKEND))
	$(PYTHON) -m cosim.codegen.main --state-json $< --backend $(FIRST_BACKEND) --out-dir . --name $(COMPONENT_NAME) $(CONFIG_COMPONENT_FLAG)
endif

HW_ARCILATOR := $(O_ARCILATOR)/$(COMPONENT_NAME).hw.mlir
COMPONENT_LIB_ARCILATOR := $(O_ARCILATOR)/$(COMPONENT_NAME).o

ifeq ($(TRACE),1)
ARCILATOR_ARGS += --observe-wires=1 --observe-ports=1 --observe-named-values=1 --observe-registers=1 --observe-memories=1
else
ARCILATOR_ARGS += --observe-wires=0 --observe-ports=0 --observe-named-values=0 --observe-registers=0 --observe-memories=0
endif

$(HW_ARCILATOR): $(DESIGN_HW_MLIR) config.mk $(COMMON_MK) | $(O_ARCILATOR)
	$(COSIM_EXTRACT) --path=$(COMPONENT_PATH) --port="$(COMPONENT_IO)" --top-name=$(TOP_NAME) --remove-sv $< -o $@

# --no-runtime: the ArcSystemCWrapper drives stepping itself.
$(COMPONENT_LIB_ARCILATOR) $(STATE_arcilator) &: $(HW_ARCILATOR) | $(O_ARCILATOR)
	$(ARCILATOR) $< --state-file=$(STATE_arcilator) -o $(O_ARCILATOR)/$(COMPONENT_NAME).ll --no-runtime $(ARCILATOR_ARGS)
	$(OPT) -O3 -S $(O_ARCILATOR)/$(COMPONENT_NAME).ll -o $(O_ARCILATOR)/$(COMPONENT_NAME).opt.ll
	$(LLC) -relocation-model=pic -O3 --filetype=obj $(O_ARCILATOR)/$(COMPONENT_NAME).opt.ll -o $(COMPONENT_LIB_ARCILATOR)

GEN_ARC_CPP := gen-arc-$(COMPONENT_NAME).cpp
GEN_ARC_OBJ := $(O_ARCILATOR)/gen-arc-$(COMPONENT_NAME).o
ifeq ($(GENERATE_SIM_CPP),1)
$(GEN_ARC_CPP): $(STATE_arcilator)
	$(PYTHON) -m cosim.codegen.main --state-json $< --backend arcilator --out-dir . --name $(COMPONENT_NAME) $(CONFIG_COMPONENT_FLAG)
endif

$(GEN_ARC_OBJ): $(GEN_ARC_CPP) | $(O_ARCILATOR)
	$(COMPILE_ARCILATOR) -c $< -o $@

# $(GEN_ARC_CPP): its codegen run also writes the A<Model>.h that sim.cpp includes.
$(O_ARCILATOR)/sim.o: sim.cpp $(GEN_ARC_CPP) | $(O_ARCILATOR)
	$(COMPILE_ARCILATOR) -c $< -o $@

$(EXTRA_OBJS_ARCILATOR): $(O_ARCILATOR)/%.o: %.cpp | $(O_ARCILATOR)
	$(COMPILE_ARCILATOR) -c $< -o $@

build-arcilator/sim: $(O_ARCILATOR)/sim.o $(GEN_ARC_OBJ) $(EXTRA_OBJS_ARCILATOR) $(COMPONENT_LIB_ARCILATOR) $(LIBSYSTEMCTLM)
	$(CXX) $^ $(SIM_LDFLAGS) $(SIM_LDLIBS) -o $@

#===-------------------------------------------------------------------------===
# verilator
#===-------------------------------------------------------------------------===
HW_VERILATOR := $(O_VERILATOR)/$(COMPONENT_NAME).hw.mlir
COMPONENT_LIB_VERILATOR     := $(O_VERILATOR)/verilator/libV$(TOP_NAME).a
COMPONENT_RUNTIME_VERILATOR := $(O_VERILATOR)/verilator/libverilated.a
COMPONENT_HDR_VERILATOR     := $(O_VERILATOR)/verilator/V$(TOP_NAME).h
VERI_INCLUDES := -I $(O_VERILATOR)/verilator -isystem $(VERILATOR_ROOT)/include -isystem $(VERILATOR_ROOT)/include/vltstd
VERILATOR_ARGS := -DPRINTF_COND=1 -DASSERT_VERBOSE_COND=1 -DSTOP_COND=1 -Wno-fatal -O3 \
                  --x-assign fast --x-initial fast --noassert \
                  -Wno-WIDTHEXPAND -Wno-UNSIGNED -Wno-WIDTHTRUNC -Wno-TIMESCALEMOD \
                  --expand-limit 1024 $(VERILATOR_EXTRA_ARGS)
ifeq ($(TRACE),1)
VERILATOR_ARGS += --trace-vcd
endif
ifeq ($(VM_COVERAGE),1)
VERILATOR_ARGS += --coverage
endif

$(HW_VERILATOR) $(STATE_verilator) &: $(DESIGN_HW_MLIR) config.mk $(COMMON_MK) | $(O_VERILATOR)
	$(COSIM_EXTRACT) --path=$(COMPONENT_PATH) --port="$(COMPONENT_IO)" --top-name=$(TOP_NAME) --state-json=$(STATE_verilator) $< -o $(HW_VERILATOR)

$(O_VERILATOR)/vsrc/.stamp: $(HW_VERILATOR) | $(O_VERILATOR)
	$(FIRTOOL) --split-verilog $< -o $(O_VERILATOR)/vsrc
	touch $@

# touch: verilator leaves its outputs alone when the .sv didn't change.
$(COMPONENT_LIB_VERILATOR) $(COMPONENT_RUNTIME_VERILATOR) $(COMPONENT_HDR_VERILATOR) &: $(O_VERILATOR)/vsrc/.stamp
	+cd $(O_VERILATOR)/vsrc && SYSTEMC_INCLUDE=$(SYSTEMC_INCLUDE) SYSTEMC_LIBDIR=$(SYSTEMC_LIBDIR) SYSTEMC_CXX_FLAGS=-std=$(SYSTEMC_STD) $(VERILATOR) -sc -Mdir $(abspath $(O_VERILATOR))/verilator --top-module $(TOP_NAME) $(VERILATOR_ARGS) --build -j $(shell nproc) $(TOP_NAME).sv
	touch $(COMPONENT_LIB_VERILATOR) $(COMPONENT_RUNTIME_VERILATOR) $(COMPONENT_HDR_VERILATOR)

# sim.o also depends on V<Top>.h so a re-verilate re-triggers the recompile.
$(O_VERILATOR)/sim.o: sim.cpp $(COMPONENT_HDR_VERILATOR) | $(O_VERILATOR)
	$(COMPILE_VERILATOR) -c $< -o $@

$(EXTRA_OBJS_VERILATOR): $(O_VERILATOR)/%.o: %.cpp $(COMPONENT_HDR_VERILATOR) | $(O_VERILATOR)
	$(COMPILE_VERILATOR) -c $< -o $@

build-verilator/sim: $(O_VERILATOR)/sim.o $(EXTRA_OBJS_VERILATOR) $(COMPONENT_LIB_VERILATOR) $(COMPONENT_RUNTIME_VERILATOR) $(LIBSYSTEMCTLM)
	$(CXX) $^ $(SIM_LDFLAGS) $(SIM_LDLIBS) -o $@

#===-------------------------------------------------------------------------===
# Run targets, also used by `cosim run`
#===-------------------------------------------------------------------------===
run run-coupled: SHELL := /bin/bash
run run-coupled: .SHELLFLAGS := -eu -o pipefail -c

# Without QEMU; only for units without bus/interrupt/gpio IO.
run: $(SIM)
	./$(SIM) $(MAX_CYCLES) $(RUN_ARGS) 2>&1 | tee build-$(BACKEND)/run.log

# Coupled to a QEMU peer you've already started on the $(SOCK) socket.
run-coupled: $(SIM)
	./$(SIM) unix:$(SOCK) $(SYNC_QUANTUM) $(MAX_CYCLES) $(RUN_ARGS) 2>&1 | tee build-$(BACKEND)/run.log
