cmake_minimum_required(VERSION 3.20.0)
project(cosim-gen-opt LANGUAGES CXX C)

set(CMAKE_BUILD_WITH_INSTALL_NAME_DIR ON)

set(CMAKE_CXX_STANDARD 17 CACHE STRING "C++ standard to conform to")
set(CMAKE_CXX_STANDARD_REQUIRED YES)

find_package(CIRCT REQUIRED CONFIG)

set(LLVM_RUNTIME_OUTPUT_INTDIR ${CMAKE_BINARY_DIR}/bin)
set(LLVM_LIBRARY_OUTPUT_INTDIR ${CMAKE_BINARY_DIR}/lib)
set(MLIR_BINARY_DIR ${CMAKE_BINARY_DIR})

list(APPEND CMAKE_MODULE_PATH "${CIRCT_CMAKE_DIR}")
list(APPEND CMAKE_MODULE_PATH "${MLIR_CMAKE_DIR}")
list(APPEND CMAKE_MODULE_PATH "${LLVM_CMAKE_DIR}")

include(TableGen)
include(AddLLVM)
include(AddMLIR)
set(CIRCT_BUILD_TOOLS ON)
include(AddCIRCT)
include(HandleLLVMOptions)

set(COSIM_GEN_SOURCE_DIR ${CMAKE_CURRENT_SOURCE_DIR})
set(COSIM_GEN_BINARY_DIR ${CMAKE_CURRENT_BINARY_DIR})

include_directories(${LLVM_INCLUDE_DIRS})
include_directories(${MLIR_INCLUDE_DIRS})
include_directories(${CIRCT_INCLUDE_DIRS})
include_directories(${COSIM_GEN_SOURCE_DIR}/include)
include_directories(${COSIM_GEN_BINARY_DIR}/include)
link_directories(${LLVM_BUILD_LIBRARY_DIR})
link_directories(${CIRCT_LIBRARY_DIRS})
# HandleLLVMOptions (above) already defines _GLIBCXX_USE_CXX11_ABI
string(REPLACE "-D_GLIBCXX_USE_CXX11_ABI=1" "" LLVM_DEFINITIONS_DEDUPED "${LLVM_DEFINITIONS}")
add_definitions(${LLVM_DEFINITIONS_DEDUPED})

option(COSIM_GEN_INCLUDE_TESTS
  "Generate build targets for the CIRCT standalone tests." ON)

add_subdirectory(include)
add_subdirectory(lib)
add_subdirectory(cosim-gen-opt)
add_subdirectory(cosim-extract)
set(COSIM_GEN_HAS_PLUGIN OFF)
if(NOT WIN32 AND TARGET cosim-gen-opt)
  add_subdirectory(cosim-gen-plugin)
  set(COSIM_GEN_HAS_PLUGIN ON)
endif()
if(COSIM_GEN_INCLUDE_TESTS)
  add_subdirectory(test)
endif()
