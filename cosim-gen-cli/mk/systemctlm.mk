#===-------------------------------------------------------------------------===
# Builds libsystemctlm.a (the QEMU remote-port TLM bridge) from
# third_party/libsystemctlm-soc.
#===-------------------------------------------------------------------------===

LIBRP_DIR = $(LIBSOC_DIR)/libremote-port

CPPFLAGS += -I $(LIBSOC_DIR) -I $(LIBRP_DIR) -I $(SYSTEMC_INCLUDE) -DSC_ALLOW_DEPRECATED_IEEE_API
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

