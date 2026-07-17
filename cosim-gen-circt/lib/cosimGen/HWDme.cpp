//===----------------------------------------------------------------------===//
//
// Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#include "circt/Dialect/HW/HWInstanceGraph.h"
#include "mlir/Pass/Pass.h"

#include "llvm/Support/Debug.h"
#define DEBUG_TYPE "hw-dme"

#include "cosimGen/Passes.h"

namespace circt::cosimGen {
#define GEN_PASS_DEF_HWDME
#include "cosimGen/Passes.h.inc"

namespace {

struct HWDmePass : impl::HWDmeBase<HWDmePass> {
private:
public:
  using impl::HWDmeBase<HWDmePass>::HWDmeBase;

  void runOnOperation() final {
    bool found = false;
    hw::InstanceGraph &instGraph = getAnalysis<hw::InstanceGraph>();
    igraph::InstancePathCache instancePathCache(instGraph);

    do {
      found = false;
      for (auto *node : llvm::make_early_inc_range(instGraph)) {
        if (node->noUses()) {
          LLVM_DEBUG(llvm::dbgs() << "Delete module: "
                                  << cast<hw::HWModuleLike>(node->getModule().getOperation()).getModuleName() << "\n");
          auto module = node->getModule();
          instGraph.erase(node);
          module.erase();
          found = true;
        }
      }
    } while (found);
  }
};

} // namespace
} // namespace circt::cosimGen
