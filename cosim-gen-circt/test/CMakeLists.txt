llvm_canonicalize_cmake_booleans(
  COSIM_GEN_HAS_PLUGIN
)

configure_lit_site_cfg(
  ${CMAKE_CURRENT_SOURCE_DIR}/lit.site.cfg.py.in
  ${CMAKE_CURRENT_BINARY_DIR}/lit.site.cfg.py
  MAIN_CONFIG
  ${CMAKE_CURRENT_SOURCE_DIR}/lit.cfg.py
)

set(COSIM_GEN_TEST_DEPENDS
  FileCheck
  cosim-gen-opt
  cosim-extract
)
if(TARGET CosimGenPlugin)
  list(APPEND COSIM_GEN_TEST_DEPENDS CosimGenPlugin)
endif()

add_lit_testsuite(check-cosim-gen 
  "Running the cosim generation regression tests"
  ${CMAKE_CURRENT_BINARY_DIR}
  DEPENDS ${COSIM_GEN_TEST_DEPENDS}
)
set_target_properties(check-cosim-gen PROPERTIES FOLDER "Tests")

add_lit_testsuites(COSIM_GEN ${CMAKE_CURRENT_SOURCE_DIR}
  DEPENDS ${COSIM_GEN_TEST_DEPENDS}
)
