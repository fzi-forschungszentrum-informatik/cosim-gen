//===----------------------------------------------------------------------===//
//
// Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#include "circt/Dialect/Emit/EmitOps.h"
#include "circt/Dialect/OM/OMOps.h"
#include "circt/Dialect/SV/SVOps.h"
#include "mlir/Pass/Pass.h"

#include "llvm/Support/Debug.h"
#define DEBUG_TYPE "hw-remove-sv"

#include "cosimGen/Passes.h"

namespace circt::cosimGen {
#define GEN_PASS_DEF_HWREMOVESV
#include "cosimGen/Passes.h.inc"

namespace {

struct HWRemoveSVPass : impl::HWRemoveSVBase<HWRemoveSVPass> {
private:
  SmallVector<mlir::Operation *> deleteOperation(SmallVector<mlir::Operation *> &deleteList) {
    DenseSet<mlir::Operation *> visited;
    SmallVector<mlir::Operation *> unused;

    while (!deleteList.empty()) {
      Operation *delOp = deleteList.pop_back_val();
      if (visited.contains(delOp))
        continue;

      SmallVector<mlir::Operation *> delOrder;
      SmallVector<mlir::Operation *> worklist;
      delOrder.push_back(delOp);
      worklist.push_back(delOp);

      while (!worklist.empty()) {
        mlir::Operation *wop = worklist.pop_back_val();

        for (Region &region : wop->getRegions()) {
          for (Block &block : region) {
            for (mlir::Operation &nestedOp : block) {
              delOrder.push_back(&nestedOp);
              worklist.push_back(&nestedOp);
            }
          }
        }

        for (mlir::Operation *user : wop->getUsers()) {
          worklist.push_back(user);
          delOrder.push_back(user);
        }
      }

      for (Operation *op : llvm::reverse(delOrder)) {
        if (!visited.insert(op).second)
          continue;

        for (auto val : op->getOperands())
          if (auto *nextOp = val.getDefiningOp())
            if (nextOp->use_empty())
              unused.push_back(nextOp);

        op->erase();
      }
    }

    llvm::erase_if(unused, [&](mlir::Operation *op) { return visited.contains(op); });
    return unused;
  }

  inline bool hasNonEmptyRegions(mlir::Operation *op) {
    for (Region &region : op->getRegions()) {
      for (Block &block : region) {
        if (!block.empty()) {
          return true;
        }
      }
    }
    return false;
  }

  void deleteUnused(SmallVector<mlir::Operation *> &deleteList) {
    while (!deleteList.empty()) {
      Operation *delOp = deleteList.pop_back_val();

      SmallVector<mlir::Operation *> worklist;
      worklist.push_back(delOp);

      while (!worklist.empty()) {
        mlir::Operation *wop = worklist.pop_back_val();

        if (isa<hw::OutputOp>(wop)) {
          LLVM_DEBUG(llvm::dbgs() << "Skipping hw::OutputOp: " << *wop << "\n");
          continue;
        }

        // First, collect all nested operations from regions
        if (hasNonEmptyRegions(wop)) {
          for (Region &region : wop->getRegions()) {
            for (Block &block : region) {
              for (mlir::Operation &nestedOp : llvm::make_early_inc_range(block)) {
                // Add nested ops to delete list if they're SV or become unused
                if (nestedOp.getDialect()->getNamespace() == "sv") {
                  worklist.push_back(&nestedOp);
                } else if (nestedOp.use_empty()) {
                  worklist.push_back(&nestedOp);
                }
              }
            }
          }
        }

        for (auto val : wop->getOperands())
          if (auto *nextOp = val.getDefiningOp())
            if (nextOp->use_empty())
              worklist.push_back(nextOp);

        // Only erase if the operation is safe to delete
        if (wop->use_empty() || wop->getDialect()->getNamespace() == "sv") {
          wop->erase();
        } else {
          LLVM_DEBUG(llvm::dbgs() << "Warning: Cannot erase operation with uses: " << *wop << "\n");
        }
      }
    }
  }

public:
  using impl::HWRemoveSVBase<HWRemoveSVPass>::HWRemoveSVBase;

  void runOnOperation() final {
    ::mlir::ModuleOp mod = getOperation();

    SmallVector<mlir::Operation *> toDel;

    mod.walk([&](Operation *op) {
      if (op->getDialect()->getNamespace() == "sv") {
        if (isa<sv::SVVerbatimModuleOp>(op))
          return;
        toDel.push_back(op);
      }
    });
    // mod.walk([&](emit::FragmentOp op) { toDel.push_back(op); });
    // mod.walk([&](emit::FileOp op) { toDel.push_back(op); });

    auto unused = deleteOperation(toDel);

    deleteUnused(unused);
  }
};

} // namespace
} // namespace circt::cosimGen
