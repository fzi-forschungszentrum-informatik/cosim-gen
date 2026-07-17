//===----------------------------------------------------------------------===//
//
// Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#include "circt/Dialect/HW/HWInstanceGraph.h"
#include "circt/Dialect/HW/HWOps.h"
#include "mlir/Pass/Pass.h"

#include "common/PathComp.h"

#include "llvm/Support/Debug.h"
#define DEBUG_TYPE "hw-subgraph"

#include "cosimGen/Passes.h"
#include <set>

namespace circt::cosimGen {
#define GEN_PASS_DEF_HWSUBGRAPH
#include "cosimGen/Passes.h.inc"

namespace {

struct HWSubGraphPass : impl::HWSubGraphBase<HWSubGraphPass> {
public:
  using impl::HWSubGraphBase<HWSubGraphPass>::HWSubGraphBase;

  void runOnOperation() final {
    igraph::InstancePathCache instancePathCache(getAnalysis<hw::InstanceGraph>());
    SmallVector<std::string> searchPath = parsePath(path);
    std::set<hw::HWModuleLike> toDel, subMod, newTLs;
    ModuleOp circuit = getOperation();

    circuit.walk([&](hw::HWModuleLike hwModule) {
      bool isPart = false;
      for (auto instPath : instancePathCache.getAbsolutePaths(hwModule)) {
        int r = pathCompare(searchPath, instPath);
        if (r >= 0) {
          isPart = true;
          if (r == 0)
            newTLs.insert(hwModule);
          else
            subMod.insert(hwModule);
        }
      }
      if (!isPart)
        toDel.insert(hwModule);
    });

    if (newTLs.size() == 1) {
      LLVM_DEBUG(llvm::dbgs() << "New top module " << path << " deleting " << toDel.size() << " modules keeping "
                              << subMod.size() << " submodules\n");

      auto newTL = *newTLs.begin();
      newTL.setPublic();

      for (auto m : toDel)
        m.erase();

    } else {
      auto diag = mlir::emitError(getOperation().getLoc()) << "Didn't find single new top module for: " << path << "\n"
                                                           << "Available paths are:\n";
      circuit.walk([&](hw::HWModuleLike hwModule) {
        for (auto instPath : instancePathCache.getAbsolutePaths(hwModule)) {
          diag.attachNote() << path2Str(instPath);
        }
      });
    }
  };
};

} // namespace
} // namespace circt::cosimGen
