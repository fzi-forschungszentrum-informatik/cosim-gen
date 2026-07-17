add_llvm_library(CosimGenPlugin
  MODULE BUILDTREE_ONLY
  cosim-gen-plugin.cpp

  DEPENDS
  CIRCTCosimGen
  PLUGIN_TOOL
  cosim-gen-opt

  LINK_LIBS
  CIRCTCosimGen
  CIRCTCosimGenHelper
)

target_include_directories(CosimGenPlugin
  PRIVATE
  "${COSIM_GEN_BINARY_DIR}/include"
)
