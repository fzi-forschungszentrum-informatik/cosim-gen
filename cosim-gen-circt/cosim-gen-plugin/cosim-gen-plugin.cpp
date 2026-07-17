//===----------------------------------------------------------------------===//
//
// This file is licensed under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#include "mlir/Tools/Plugins/DialectPlugin.h"
#include "mlir/Tools/Plugins/PassPlugin.h"
#include "llvm/Config/llvm-config.h"
#include "llvm/Support/Compiler.h"

#include "circt/Dialect/Comb/CombDialect.h"
#include "circt/Dialect/Emit/EmitDialect.h"
#include "circt/Dialect/FIRRTL/FIRRTLDialect.h"
#include "circt/Dialect/HW/HWDialect.h"
#include "circt/Dialect/OM/OMDialect.h"
#include "circt/Dialect/SV/SVDialect.h"
#include "circt/Dialect/Seq/SeqDialect.h"

#include "cosimGen/Passes.h"

extern "C" LLVM_ATTRIBUTE_WEAK mlir::DialectPluginLibraryInfo mlirGetDialectPluginInfo() {
  return {
      MLIR_PLUGIN_API_VERSION, "cosim-gen", LLVM_VERSION_STRING, [](mlir::DialectRegistry *registry) {
        registry
            ->insert<circt::firrtl::FIRRTLDialect, circt::comb::CombDialect, circt::hw::HWDialect,
                     circt::seq::SeqDialect, circt::sv::SVDialect, circt::om::OMDialect, circt::emit::EmitDialect>();
        circt::cosimGen::registerPasses();
      }};
}

extern "C" LLVM_ATTRIBUTE_WEAK mlir::PassPluginLibraryInfo mlirGetPassPluginInfo() {
  return {MLIR_PLUGIN_API_VERSION, "cosim-gen-Passes", LLVM_VERSION_STRING,
          []() { circt::cosimGen::registerPasses(); }};
}
