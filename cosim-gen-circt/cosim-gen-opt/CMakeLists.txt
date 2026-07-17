set(LLVM_LINK_COMPONENTS
  Support
)

add_llvm_executable(cosim-gen-opt
  cosim-gen-opt.cpp

  DEPENDS
  SUPPORT_PLUGINS
)

llvm_update_compile_flags(cosim-gen-opt)


get_property(dialect_libs GLOBAL PROPERTY CIRCT_DIALECT_LIBS)

target_link_libraries(cosim-gen-opt
 PRIVATE
  CIRCTCosimGen
  CIRCTCosimGenHelper
  CIRCTHW
  CIRCTHWTransforms
  CIRCTSim
  MLIRIR
  MLIROptLib
  MLIRParser
  MLIRSupport
  MLIRTransforms

  ${dialect_libs}
  MLIRRegisterAllDialects
)

export_executable_symbols_for_plugins(cosim-gen-opt)
