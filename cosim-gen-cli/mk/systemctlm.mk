#===-------------------------------------------------------------------------===
# Builds libsystemctlm.a (the QEMU remote-port TLM bridge) from the vendored
# libsystemctlm-soc submodule. Unchanged from leon_vp's systemctlm.mk except
# LIBSOC_DIR now defaults to this repo's third_party/ location instead of a
# sibling directory of the makefile itself.
#===-------------------------------------------------------------------------===

# Captured with := (not ?=) so it's fixed at this line's parse time - $(MAKEFILE_LIST)
# keeps growing as more files are included (e.g. the -include of .d files
# below), so a lazily-expanded reference to it would silently re-resolve to
# the wrong directory on any rebuild once dep files exist.
_SYSTEMCTLM_MK_DIR := $(abspath $(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
LIBSOC_DIR ?= $(abspath $(_SYSTEMCTLM_MK_DIR)/../third_party/libsystemctlm-soc)
LIBRP_DIR   = $(LIBSOC_DIR)/libremote-port

ifeq ($(TLM_BUILD_DIR),)
$(error TLM_BUILD_DIR not set)
endif

# include/ and lib/ may live in separate trees (a distro package: headers in
# /usr/include, libs in /usr/lib/<triplet>). Given a single-prefix install,
# derive both from SYSTEMC_DIR's conventional subdirs.
ifneq ($(SYSTEMC_DIR),)
SYSTEMC_INCLUDE ?= $(SYSTEMC_DIR)/include
SYSTEMC_LIBDIR  ?= $(SYSTEMC_DIR)/lib
endif
ifeq ($(strip $(SYSTEMC_INCLUDE)),)
$(error neither SYSTEMC_INCLUDE nor SYSTEMC_DIR set)
endif

CPPFLAGS += -I $(LIBSOC_DIR) -I $(LIBRP_DIR) -I $(SYSTEMC_INCLUDE) -DSC_ALLOW_DEPRECATED_IEEE_API
# Must match the standard the installed libsystemc.so was built with - see
# the comment in component.mk. Override (e.g. SYSTEMC_STD=c++14) if you're
# pointed at an older SystemC install.
SYSTEMC_STD ?= c++17
CXXFLAGS += -std=$(SYSTEMC_STD)

TLM_BUILD_DIR_LIBTLM  = $(TLM_BUILD_DIR)/libsystemctlm
LIBSYSTEMCTLM     = $(TLM_BUILD_DIR)/libsystemctlm.a

C_SRCS  += $(LIBRP_DIR)/safeio.c
C_SRCS  += $(LIBRP_DIR)/remote-port-proto.c
C_SRCS  += $(LIBRP_DIR)/remote-port-sk.c
SC_SRCS += $(LIBRP_DIR)/remote-port-tlm.cc
SC_SRCS += $(LIBRP_DIR)/remote-port-tlm-memory-master.cc
SC_SRCS += $(LIBRP_DIR)/remote-port-tlm-memory-slave.cc
SC_SRCS += $(LIBRP_DIR)/remote-port-tlm-wires.cc
SC_SRCS += $(LIBRP_DIR)/remote-port-tlm-ats.cc
SC_SRCS += $(LIBRP_DIR)/remote-port-tlm-pci-ep.cc

C_OBJS  = $(patsubst $(LIBRP_DIR)/%.c,$(TLM_BUILD_DIR_LIBTLM)/%.o,$(C_SRCS))
SC_OBJS = $(patsubst $(LIBRP_DIR)/%.cc,$(TLM_BUILD_DIR_LIBTLM)/%.o,$(SC_SRCS))
LIBTLM_OBJS = $(SC_OBJS) $(C_OBJS)

#===-------------------------------------------------------------------------===
# SystemC
#===-------------------------------------------------------------------------===

$(TLM_BUILD_DIR_LIBTLM):
	mkdir -p $(TLM_BUILD_DIR_LIBTLM)

$(TLM_BUILD_DIR_LIBTLM)/%.o: $(LIBRP_DIR)/%.c | $(TLM_BUILD_DIR_LIBTLM)
	$(CC)  -MMD $(CPPFLAGS) $(CFLAGS) -c $< -o $@

$(TLM_BUILD_DIR_LIBTLM)/%.o: $(LIBRP_DIR)/%.cc | $(TLM_BUILD_DIR_LIBTLM)
	$(CXX) -MMD $(CPPFLAGS) $(CXXFLAGS) -c $< -o $@

## Dep generation ##
-include $(LIBTLM_OBJS:.o=.d)

$(LIBSYSTEMCTLM): $(LIBTLM_OBJS)
	$(AR) rcs $@ $^

all: $(LIBSYSTEMCTLM)

clean:
	$(RM) -r $(TLM_BUILD_DIR_LIBTLM)
	$(RM) $(LIBTLM_OBJS) $(LIBTLM_OBJS:.o=.d)
