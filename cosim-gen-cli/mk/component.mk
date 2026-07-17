#===-------------------------------------------------------------------------===
# Shared single-component build rules.
#
# Included by each build/components/<name>/Makefile, AFTER config.mk (the
# machine-generated per-unit vars: COMPONENT_NAME/PATH/IO, TOP_NAME,
# IS_COMPONENT, SUPPORTED_BACKENDS - which itself includes ../../common.mk
# for the vars shared by every unit: the resolved toolchain, DESIGN_HW_MLIR,
# LIBSYSTEMCTLM, ... - see project.py's _render_config_mk/_render_common_mk)
# and the user's own hook vars (EXTRA_SRCS, EXTRA_CXXFLAGS, SYNC_QUANTUM,
# GENERATE_SIM_CPP, ...).
#
# One component directory serves every backend in SUPPORTED_BACKENDS at
# once: the editable/generated top-level files (Makefile, config.mk, sim.cpp,
# and - only if arcilator is supported - gen-arc-<name>.cpp/.h/A<Model>.h)
# are shared, since sim.cpp's content doesn't depend on which backend
# generated it (see codegen/main.py:emit) and the arcilator side files are
# backend-specific by nature already. Only the actual compiled artifacts fork,
# into their own build-arcilator/ / build-verilator/ dir - extraction output
# itself differs by backend (arcilator's --remove-sv HW vs. verilator's
# combined HW+state-json), so those can't be shared.
#
# Both backends' rule blocks below are always defined, whether or not that
# backend is actually in SUPPORTED_BACKENDS - Make only ever evaluates a rule
# if something requests it as a prerequisite (see `all:`), so an unused
# backend's rules simply never fire; this also means both blocks' variables
# must NOT collide (unlike the old single-$(BACKEND) version, where an
# ifeq/else made only one side ever active) - every backend-specific name
# below is suffixed _ARCILATOR/_VERILATOR.
#
# The whole, un-extracted design is just a unit with IS_COMPONENT=0
# (COMPONENT_PATH empty, so cosim-extract skips extraction and just runs its
# shared cleanup pipeline - see cosim-extract.cpp).
#===-------------------------------------------------------------------------===

O_ARCILATOR := build-arcilator
O_VERILATOR := build-verilator

CXX ?= g++
LIBRP_DIR := $(LIBSOC_DIR)/libremote-port

EXTRA_SRCS       ?=
EXTRA_CXXFLAGS   ?=
EXTRA_LDLIBS     ?=
GENERATE_SIM_CPP ?= 1
SYNC_QUANTUM     ?= 1000
MAX_CYCLES       ?= 0
RUN_ARGS         ?=
TRACE            ?= 0
SYSC_TRACE       ?= 0
VM_COVERAGE      ?= 0

SYSTEMC_STD ?= c++17

ifneq ($(SYSTEMC_DIR),)
SYSTEMC_INCLUDE ?= $(SYSTEMC_DIR)/include
SYSTEMC_LIBDIR  ?= $(SYSTEMC_DIR)/lib
endif

BASE_CPPFLAGS := -I $(RTLGEN_INC_DIR) -I $(LIBSOC_DIR) -I $(LIBRP_DIR) -I $(SYSTEMC_INCLUDE) \
                 -DTRACE=$(TRACE) -DSYSC_TRACE=$(SYSC_TRACE) -DVM_COVERAGE=$(VM_COVERAGE) \
                 -DSC_ALLOW_DEPRECATED_IEEE_API
SIM_CXXFLAGS := -Wall -O3 -g -std=$(SYSTEMC_STD) $(EXTRA_CXXFLAGS)
SIM_LDFLAGS  := -L $(SYSTEMC_LIBDIR) -Wl,-rpath,$(SYSTEMC_LIBDIR)
SIM_LDLIBS   := -lsystemc -lpthread -latomic $(EXTRA_LDLIBS)

# User .cpp (e.g. your own SystemC peripheral model) compiled + linked into
# sim - once per backend, since each backend's own sim.o needs its own -D.
EXTRA_OBJS_ARCILATOR := $(patsubst %,$(O_ARCILATOR)/%.o,$(basename $(notdir $(EXTRA_SRCS))))
EXTRA_OBJS_VERILATOR := $(patsubst %,$(O_VERILATOR)/%.o,$(basename $(notdir $(EXTRA_SRCS))))

# Which backend `make run`/`make run-coupled`/`make sim` (no explicit target)
# operates on - defaults to the first entry in SUPPORTED_BACKENDS (from
# config.mk, itself from cosim.json's design.supported_backends); override
# per-invocation with e.g. `make run BACKEND=verilator` - this is exactly what
# `cosim run --backend` drives (see project.py's run()). Purely a run-time
# selector: it plays no part in `make all`, which always builds every
# supported backend regardless.
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

ifeq ($(strip $(GENERATE_SIM_CPP)),1)
sim.cpp: $(STATE_$(FIRST_BACKEND))
	$(PYTHON) -m cosim.codegen.main --state-json $< --backend $(FIRST_BACKEND) --out-dir . --name $(COMPONENT_NAME) $(CONFIG_COMPONENT_FLAG)
endif

HW_ARCILATOR := $(O_ARCILATOR)/$(COMPONENT_NAME).hw.mlir
COMPONENT_LIB_ARCILATOR := $(O_ARCILATOR)/$(COMPONENT_NAME).o

ifeq ($(strip $(TRACE)),1)
ARCILATOR_ARGS += --observe-wires=1 --observe-ports=1 --observe-named-values=1 --observe-registers=1 --observe-memories=1
else
ARCILATOR_ARGS += --observe-wires=0 --observe-ports=0 --observe-named-values=0 --observe-registers=0 --observe-memories=0
endif

$(HW_ARCILATOR): $(DESIGN_HW_MLIR) config.mk $(COMMON_MK) | $(O_ARCILATOR)
	$(COSIM_EXTRACT) --path=$(COMPONENT_PATH) --port="$(COMPONENT_IO)" --top-name=$(TOP_NAME) --remove-sv $< -o $@

# arcilator emits its own state file (its runtime ABI); grouped with the .ll->.o.
# --no-runtime always on (not part of ARCILATOR_ARGS): the ArcSystemCWrapper's
# own eval() thread drives stepping itself, a structural requirement of this
# cosim architecture, not a tunable.
$(COMPONENT_LIB_ARCILATOR) $(STATE_arcilator) &: $(HW_ARCILATOR) | $(O_ARCILATOR)
	$(ARCILATOR) $< --state-file=$(STATE_arcilator) -o $(O_ARCILATOR)/$(COMPONENT_NAME).ll --no-runtime $(ARCILATOR_ARGS)
	$(OPT) -O3 -S $(O_ARCILATOR)/$(COMPONENT_NAME).ll -o $(O_ARCILATOR)/$(COMPONENT_NAME).opt.ll
	$(LLC) -relocation-model=pic -O3 --filetype=obj $(O_ARCILATOR)/$(COMPONENT_NAME).opt.ll -o $(COMPONENT_LIB_ARCILATOR)

# codegen writes the arcilator model header/cpp + A<Model>.h wrapper into the
# component dir (alongside the shared sim.cpp) - only ever for this backend.
GEN_ARC_CPP := gen-arc-$(COMPONENT_NAME).cpp
GEN_ARC_OBJ := $(O_ARCILATOR)/gen-arc-$(COMPONENT_NAME).o
ifeq ($(strip $(GENERATE_SIM_CPP)),1)
$(GEN_ARC_CPP): $(STATE_arcilator)
	$(PYTHON) -m cosim.codegen.main --state-json $< --backend arcilator --out-dir . --name $(COMPONENT_NAME) $(CONFIG_COMPONENT_FLAG)
endif

$(GEN_ARC_OBJ): $(GEN_ARC_CPP) | $(O_ARCILATOR)
	$(CXX) -MMD $(BASE_CPPFLAGS) -DUSE_ARCILATOR=1 -I . $(SIM_CXXFLAGS) -c $< -o $@

# sim.cpp's own #include of the wrapper header is invisible to Make (it's
# inside a source file, not a Make-level dependency) - sim.cpp may well have
# been (re)generated by the *verilator* recipe (see the shared sim.cpp rule
# above), which never touches A<Model>.h at all, so this needs an explicit
# real prerequisite on $(GEN_ARC_CPP) (the same codegen invocation that
# writes the wrapper header alongside it) - without it, nothing would force
# that header to exist before this compile under a parallel `-jN` build.
$(O_ARCILATOR)/sim.o: sim.cpp $(GEN_ARC_CPP) | $(O_ARCILATOR)
	$(CXX) -MMD $(BASE_CPPFLAGS) -DUSE_ARCILATOR=1 -I . $(SIM_CXXFLAGS) -c $< -o $@

$(EXTRA_OBJS_ARCILATOR): $(O_ARCILATOR)/%.o: %.cpp | $(O_ARCILATOR)
	$(CXX) -MMD $(BASE_CPPFLAGS) -DUSE_ARCILATOR=1 -I . $(SIM_CXXFLAGS) -c $< -o $@

build-arcilator/sim: $(O_ARCILATOR)/sim.o $(GEN_ARC_OBJ) $(EXTRA_OBJS_ARCILATOR) $(COMPONENT_LIB_ARCILATOR) $(LIBSYSTEMCTLM)
	$(CXX) $^ $(SIM_LDFLAGS) $(SIM_LDLIBS) -o $@

#===-------------------------------------------------------------------------===
# verilator: same shape as the arcilator block above, only reachable if
# "verilator" is in SUPPORTED_BACKENDS.
#===-------------------------------------------------------------------------===
HW_VERILATOR := $(O_VERILATOR)/$(COMPONENT_NAME).hw.mlir
COMPONENT_LIB_VERILATOR     := $(O_VERILATOR)/verilator/libV$(TOP_NAME).a
COMPONENT_RUNTIME_VERILATOR := $(O_VERILATOR)/verilator/libverilated.a
COMPONENT_HDR_VERILATOR     := $(O_VERILATOR)/verilator/V$(TOP_NAME).h
VERI_INCLUDES := -I $(O_VERILATOR)/verilator -isystem $(VERILATOR_ROOT)/include -isystem $(VERILATOR_ROOT)/include/vltstd
# $(strip ...): these vars are user-editable Makefile hooks, typically
# written as "TRACE ?= 1      # comment" for column alignment - the trailing
# spaces before the comment are part of the assigned *value* (comments don't
# get stripped until after expansion), so an unstripped ifeq's literal string
# compare against "1" would silently never match.
ifeq ($(strip $(TRACE)),1)
VERILATOR_ARGS += --trace-vcd
endif
ifeq ($(strip $(VM_COVERAGE)),1)
VERILATOR_ARGS += --coverage
endif

# config.mk/common.mk as prerequisites: see the matching comment in the
# arcilator block above - same reasoning, same effect (a cosim.json edit
# invalidates $(HW_VERILATOR)/$(STATE_verilator) and cascades through
# $(O_VERILATOR)/vsrc/.stamp to a re-verilate).
$(HW_VERILATOR) $(STATE_verilator) &: $(DESIGN_HW_MLIR) config.mk $(COMMON_MK) | $(O_VERILATOR)
	$(COSIM_EXTRACT) --path=$(COMPONENT_PATH) --port="$(COMPONENT_IO)" --top-name=$(TOP_NAME) --state-json=$(STATE_verilator) $< -o $(HW_VERILATOR)

$(O_VERILATOR)/vsrc/.stamp: $(HW_VERILATOR) | $(O_VERILATOR)
	$(FIRTOOL) --split-verilog $< -o $(O_VERILATOR)/vsrc
	touch $@

# touch after --build: verilator's own -Mdir is itself incrementally built,
# so when the .sv content hasn't actually changed it correctly leaves 
# $(COMPONENT_LIB_VERILATOR)/etc untouched 
$(COMPONENT_LIB_VERILATOR) $(COMPONENT_RUNTIME_VERILATOR) $(COMPONENT_HDR_VERILATOR) &: $(O_VERILATOR)/vsrc/.stamp
	+cd $(O_VERILATOR)/vsrc && SYSTEMC_INCLUDE=$(SYSTEMC_INCLUDE) SYSTEMC_LIBDIR=$(SYSTEMC_LIBDIR) SYSTEMC_CXX_FLAGS=-std=$(SYSTEMC_STD) $(VERILATOR) -sc -Mdir $(abspath $(O_VERILATOR))/verilator --top-module $(TOP_NAME) $(VERILATOR_ARGS) --build -j $(shell nproc) $(TOP_NAME).sv
	touch $(COMPONENT_LIB_VERILATOR) $(COMPONENT_RUNTIME_VERILATOR) $(COMPONENT_HDR_VERILATOR)

# sim.o also depends on V<Top>.h so a re-verilate re-triggers the recompile.
$(O_VERILATOR)/sim.o: sim.cpp $(COMPONENT_HDR_VERILATOR) | $(O_VERILATOR)
	$(CXX) -MMD $(BASE_CPPFLAGS) -DUSE_VERILATOR=1 $(VERI_INCLUDES) $(SIM_CXXFLAGS) -c $< -o $@

$(EXTRA_OBJS_VERILATOR): $(O_VERILATOR)/%.o: %.cpp $(COMPONENT_HDR_VERILATOR) | $(O_VERILATOR)
	$(CXX) -MMD $(BASE_CPPFLAGS) -DUSE_VERILATOR=1 $(VERI_INCLUDES) $(SIM_CXXFLAGS) -c $< -o $@

build-verilator/sim: $(O_VERILATOR)/sim.o $(EXTRA_OBJS_VERILATOR) $(COMPONENT_LIB_VERILATOR) $(COMPONENT_RUNTIME_VERILATOR) $(LIBSYSTEMCTLM)
	$(CXX) $^ $(SIM_LDFLAGS) $(SIM_LDLIBS) -o $@

#===-------------------------------------------------------------------------===
# Standalone run helpers. `cosim run` itself now shells out to these (`run`
# for `cosim run rtl`, `run-coupled` - with SOCK - for the QEMU-coupled case),
# so MAX_CYCLES/SYNC_QUANTUM/RUN_ARGS below are the one real override surface:
# cosim.json's top-level/component.* just seed their defaults once, when a unit's
# Makefile is first scaffolded (see project.py's _MAKEFILE_SCAFFOLD) - edit
# them here afterwards and both `make run` and `cosim run` pick it up. Both
# targets act on whichever backend $(BACKEND) resolves to (default: the first
# supported one) - pass BACKEND=<other> to pick a different one, exactly what
# `cosim run --backend` does under the hood.
#===-------------------------------------------------------------------------===
# bash+pipefail, scoped to just these two targets: otherwise the pipeline's
# exit status is tee's, not $(SIM)'s, so a failing sim run would look
# successful to `cosim run` (which now checks this recipe's own exit code
# instead of watching the sim subprocess directly).
run run-coupled: SHELL := /bin/bash
run run-coupled: .SHELLFLAGS := -eu -o pipefail -c

# Standalone RTL, no QEMU. Only for a component with no bus/interrupt/gpio IO
# (a plain register/ALU block, or the whole design) - argv[1] here is a cycle
# count. A component that DOES have such IO always expects argv[1] to be a
# QEMU remote-port socket instead (see run-coupled below) - use `cosim run
# qemu <name>` for that, which also generates the matching dtb overlay.
# Teed to build-$(BACKEND)/run.log (like project.py's own `cosim run`
# invocations) so the console output survives after the terminal scrolls past it.
run: $(SIM)
	./$(SIM) $(MAX_CYCLES) $(RUN_ARGS) 2>&1 | tee build-$(BACKEND)/run.log

# Coupled to a QEMU peer you've already started on the $(SOCK) socket.
run-coupled: $(SIM)
	./$(SIM) unix:$(SOCK) $(SYNC_QUANTUM) $(MAX_CYCLES) $(RUN_ARGS) 2>&1 | tee build-$(BACKEND)/run.log
