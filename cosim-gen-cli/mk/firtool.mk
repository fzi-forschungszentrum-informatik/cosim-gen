#===-------------------------------------------------------------------------===
# Whole-design FIRRTL/MLIR -> hw dialect lowering.
#
# Invoked once per project (not per component). Variables are supplied by
# project.py when it renders the generated build Makefile.
#===-------------------------------------------------------------------------===

FIRTOOL              ?= firtool
COSIM_PLUGIN         ?=
ANNOTATION_FILE      ?=
SEQMEM_FILE          ?=
COMPONENT_TYPE_NAMES ?=

FIRTOOL_ARGS := --ignore-info-locators --default-layer-specialization=disable --enable-layers=Verification
ifneq ($(strip $(ANNOTATION_FILE)),)
FIRTOOL_ARGS += --disable-annotation-unknown --annotation-file=$(ANNOTATION_FILE)
endif
ifneq ($(strip $(SEQMEM_FILE)),)
FIRTOOL_ARGS += --repl-seq-mem --repl-seq-mem-file=$(SEQMEM_FILE)
endif

empty :=
space := $(empty) $(empty)
comma := ,

ifneq ($(strip $(COMPONENT_TYPE_NAMES)),)
ifeq ($(strip $(COSIM_PLUGIN)),)
$(error COSIM_PLUGIN must be set when COMPONENT_TYPE_NAMES is non-empty)
endif
MOD_LIST := $(subst $(space),$(comma),$(COMPONENT_TYPE_NAMES))
FIRTOOL_ARGS += --high-firrtl-pass-plugin=firrtl-keep-interfaces{"mod=$(MOD_LIST)"},firrtl-remove-inline \
                --load-pass-plugin=$(COSIM_PLUGIN)
endif

$(DESIGN_HW_MLIR): $(DESIGN_INPUT) | $(BUILD_DIR)
	$(FIRTOOL) $(FIRTOOL_ARGS) --ir-hw $< -o $@
