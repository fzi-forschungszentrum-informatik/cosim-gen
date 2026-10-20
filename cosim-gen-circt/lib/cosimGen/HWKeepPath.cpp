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
#define DEBUG_TYPE "hw-keep-path"

#include "cosimGen/Passes.h"

namespace circt::cosimGen {
#define GEN_PASS_DEF_HWKEEPPATH
#include "cosimGen/Passes.h.inc"

namespace {

// Tags every module along the instance path with a module-level KEEP attribute,
// so the first opt pass keeps the path intact for extraction.
struct HWKeepPathPass : impl::HWKeepPathBase<HWKeepPathPass> {
public:
  using impl::HWKeepPathBase<HWKeepPathPass>::HWKeepPathBase;

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

    auto *ctx = getOperation().getContext();
    for (auto inst : searchPath) {
      auto names = inst.getReferencedModuleNamesAttr();
      if (names.size() != 1)
        continue;
      auto modName = cast<StringAttr>(names[0]);
      auto *node = instGraph.lookupOrNull(modName);
      if (!node)
        continue;

      auto mod = node->getModule<hw::HWModuleLike>();
      LLVM_DEBUG(llvm::dbgs() << "\t - Keep module: " << mod.getModuleName() << "\n");
      mod->setAttr(KEEP, BoolAttr::get(ctx, true));
    }
  }
};

} // namespace
} // namespace circt::cosimGen
