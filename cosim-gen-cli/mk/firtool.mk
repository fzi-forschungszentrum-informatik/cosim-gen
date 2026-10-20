#===-------------------------------------------------------------------------===
# Lowers the whole design to the hw dialect, once per project.
#===-------------------------------------------------------------------------===

FIRTOOL_ARGS := --ignore-info-locators --default-layer-specialization=disable --enable-layers=Verification
ifneq ($(ANNOTATION_FILE),)
FIRTOOL_ARGS += --disable-annotation-unknown --annotation-file=$(ANNOTATION_FILE)
endif
ifneq ($(SEQMEM_FILE),)
FIRTOOL_ARGS += --repl-seq-mem --repl-seq-mem-file=$(SEQMEM_FILE)
endif

empty :=
space := $(empty) $(empty)
comma := ,

ifneq ($(COMPONENT_TYPE_NAMES),)
MOD_LIST := $(subst $(space),$(comma),$(COMPONENT_TYPE_NAMES))
FIRTOOL_ARGS += --high-firrtl-pass-plugin=firrtl-keep-interfaces{"mod=$(MOD_LIST)"},firrtl-remove-inline \
                --load-pass-plugin=$(COSIM_PLUGIN)
endif

$(DESIGN_HW_MLIR): $(DESIGN_INPUT)
	$(FIRTOOL) $(FIRTOOL_ARGS) --ir-hw $< -o $@
