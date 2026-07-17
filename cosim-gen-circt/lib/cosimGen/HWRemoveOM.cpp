//===----------------------------------------------------------------------===//
//
// Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#include "circt/Dialect/Emit/EmitOps.h"
#include "circt/Dialect/HW/HWOps.h"
#include "circt/Dialect/HW/HierPathCache.h"
#include "circt/Dialect/OM/OMOps.h"
#include "circt/Dialect/SV/SVOps.h"
#include "mlir/Pass/Pass.h"

#include "llvm/Support/Debug.h"
#define DEBUG_TYPE "hw-remove-sv"

#include "cosimGen/Passes.h"

namespace circt::cosimGen {
#define GEN_PASS_DEF_HWREMOVEOM
#include "cosimGen/Passes.h.inc"

namespace {

struct HWRemoveOMPass : impl::HWRemoveOMBase<HWRemoveOMPass> {
public:
  using impl::HWRemoveOMBase<HWRemoveOMPass>::HWRemoveOMBase;

  void runOnOperation() final {
    ::mlir::ModuleOp mod = getOperation();

    mod.walk([&](om::ClassOp op) { op->erase(); });
    mod.walk([&](hw::HierPathOp op) { op->erase(); });
    mod.walk([&](sv::VerbatimOp op) {
      for (auto sym : op.getSymbols()) {
        if (llvm::isa<hw::InnerRefAttr>(sym)) {
          op->erase();
          return;
        }
      }
    });
  }
};

} // namespace
} // namespace circt::cosimGen
