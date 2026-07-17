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
#define DEBUG_TYPE "hw-makefile"

#include "cosimGen/Passes.h"

namespace circt::cosimGen {
#define GEN_PASS_DEF_HWMAKEFILE
#include "cosimGen/Passes.h.inc"

namespace {

struct HWMakefilePass : impl::HWMakefileBase<HWMakefilePass> {
private:
  static void createMakefile(llvm::raw_ostream &outputStream, hw::HWModuleLike &top) {
    outputStream << "TOP_MODULE := " << top.getModuleName() << "\n";
  }

  static LogicalResult writeMakefile(std::string pathOpt, hw::HWModuleLike &top) {
    std::error_code ec;
    llvm::ToolOutputFile outputFile(pathOpt, ec, llvm::sys::fs::OpenFlags::OF_None);
    if (ec) {
      llvm::errs() << "unable to open makefile: " << ec.message() << '\n';
      return failure();
    }

    createMakefile(outputFile.os(), top);

    outputFile.keep();
    return success();
  }

public:
  using impl::HWMakefileBase<HWMakefilePass>::HWMakefileBase;

  void runOnOperation() final {
    if (strPath == "") {
      llvm::errs() << "No path was supplied\n";
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
      getOperation().emitError("Multiple top modules\n");
      signalPassFailure();
      return;
    }

    auto top = tops->front()->getModule<hw::HWModuleLike>();
    if (failed(writeMakefile(strPath, top))) {
      signalPassFailure();
    }
  }
};

} // namespace
} // namespace circt::cosimGen
