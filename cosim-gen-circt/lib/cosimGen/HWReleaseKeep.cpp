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
#include "cosimGen/HWOpt.h"

#include "llvm/Support/Debug.h"
#define DEBUG_TYPE "hw-release-keep"

#include "cosimGen/Passes.h"

namespace circt::cosimGen {
#define GEN_PASS_DEF_HWRELEASEKEEP
#include "cosimGen/Passes.h.inc"

namespace {

// Drops the module-level KEEP attribute from the modules along the extraction
// path. Per-port {keep} tags stay.
struct HWReleaseKeepPass : impl::HWReleaseKeepBase<HWReleaseKeepPass> {
public:
  using impl::HWReleaseKeepBase<HWReleaseKeepPass>::HWReleaseKeepBase;

  void runOnOperation() final {
    hw::InstanceGraph &instGraph = getAnalysis<hw::InstanceGraph>();
    igraph::InstancePathCache instancePathCache(instGraph);

    auto searchPathResult = strPath2circtPath(instancePathCache, path);
    if (!searchPathResult) {
      llvm::errs() << "Error: " << llvm::toString(searchPathResult.takeError()) << "\n";
      signalPassFailure();
      return;
    }
    auto &searchPath = *searchPathResult;

    for (auto inst : searchPath) {
      auto names = inst.getReferencedModuleNamesAttr();
      if (names.size() != 1)
        continue;
      auto modName = cast<StringAttr>(names[0]);
      auto *node = instGraph.lookupOrNull(modName);
      if (!node)
        continue;

      auto mod = node->getModule<hw::HWModuleLike>();
      if (mod->hasAttr(KEEP)) {
        LLVM_DEBUG(llvm::dbgs() << "\t - Release keep: " << mod.getModuleName() << "\n");
        mod->removeAttr(KEEP);
      }
    }
  }
};

} // namespace
} // namespace circt::cosimGen
