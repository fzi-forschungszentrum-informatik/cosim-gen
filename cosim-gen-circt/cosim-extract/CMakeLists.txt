get_property(dialect_libs GLOBAL PROPERTY CIRCT_DIALECT_LIBS)
get_property(conversion_libs GLOBAL PROPERTY CIRCT_CONVERSION_LIBS)

set(LLVM_LINK_COMPONENTS
  Support
)

add_circt_tool(cosim-extract
  cosim-extract.cpp

  DEPENDS
  SUPPORT_PLUGINS
)

llvm_update_compile_flags(cosim-extract)

target_link_libraries(cosim-extract
  PRIVATE
  ${dialect_libs}
  ${conversion_libs}

  CIRCTCosimGen
  CIRCTCosimGenHelper
  CIRCTHW
  CIRCTHWTransforms
  CIRCTSim

  MLIRIR
  MLIRPass
  MLIRTransforms
  MLIRSupport
  MLIRParser
  MLIROptLib
  MLIRRegisterAllDialects
)
