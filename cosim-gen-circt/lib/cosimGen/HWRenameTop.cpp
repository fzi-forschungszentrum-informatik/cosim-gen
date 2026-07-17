//===----------------------------------------------------------------------===//
//
// Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#include "circt/Dialect/HW/HWInstanceGraph.h"
#include "circt/Dialect/HW/HWOps.h"
#include "circt/Dialect/Seq/SeqOps.h"
#include "mlir/Pass/Pass.h"
#include "llvm/Support/FileSystem.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/ToolOutputFile.h"

#include "llvm/Support/Debug.h"
#define DEBUG_TYPE "hw-rename-top"

#include "cosimGen/Passes.h"

namespace circt::cosimGen {
#define GEN_PASS_DEF_HWRENAMETOP
#include "cosimGen/Passes.h.inc"

namespace {

struct HWRenameTopPass : impl::HWRenameTopBase<HWRenameTopPass> {
public:
  using impl::HWRenameTopBase<HWRenameTopPass>::HWRenameTopBase;

  void runOnOperation() final {
    if (name == "") {
      llvm::errs() << "No name was supplied\n";
      signalPassFailure();
      return;
    }

    hw::InstanceGraph &instGraph = getAnalysis<hw::InstanceGraph>();
    auto tops = instGraph.getInferredTopLevelNodes();

    if (failed(tops)) {
      getOperation().emitError("No top module\n");
      signalPassFailure();
      return;
    }

    if (tops->size() != 1) {
      llvm::errs() << "Multiple top modules found (";
      llvm::errs() << tops->size() << "). Mark non-top modules as 'private' to disambiguate. Available top modules:";
      for (auto *node : *tops) {
        auto hwModule = node->getModule<hw::HWModuleLike>();
        llvm::errs() << "\n  - " << hwModule.getModuleName();
      }
      signalPassFailure();
      return;
    }

    auto top = tops->front()->getModule<hw::HWModuleLike>();
    top.setName(name);
  }
};

} // namespace
} // namespace circt::cosimGen
