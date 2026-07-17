//===----------------------------------------------------------------------===//
//
// Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#include "mlir/Pass/Pass.h"

#include "common/PathComp.h"
#include "cosimGen/HWOpt.h"
#include "cosimGen/PortTagging.h"

#include "llvm/Support/Debug.h"
#include "llvm/Support/Regex.h"
#define DEBUG_TYPE "hw-keep-ports"

#include "cosimGen/Passes.h"

namespace circt::cosimGen {
#define GEN_PASS_DEF_HWKEEPPORTS
#include "cosimGen/Passes.h.inc"

namespace {

struct HWKeepPortsPass : impl::HWKeepPortsBase<HWKeepPortsPass> {
public:
  using impl::HWKeepPortsBase<HWKeepPortsPass>::HWKeepPortsBase;

  void runOnOperation() final {
    hw::InstanceGraph &instGraph = getAnalysis<hw::InstanceGraph>();
    // igraph::InstancePathCache instancePathCache(instGraph);
    auto design = getOperation();

    llvm::StringRef params = strRegex;
    llvm::SmallVector<llvm::StringRef> paramTokens;
    params.split(paramTokens, ";");

    for (auto pairStr : paramTokens) {
      llvm::SmallVector<llvm::StringRef> pairToken;
      pairStr.split(pairToken, "=");
      if (pairToken.size() != 2) {
        llvm::errs() << "Improper format for: " << pairStr << "\nRequired format: modName1=regex1;modName2=regex2\n";
        signalPassFailure();
        return;
      }

      mlir::StringAttr modName = mlir::StringAttr::get(design.getContext(), pairToken[0]);
      auto modNode = instGraph.lookupOrNull(modName);
      llvm::Regex regex = llvm::Regex(pairToken[1]);

      if (!modNode) {
        llvm::errs() << "Module " << modName << "not found!\n";
        signalPassFailure();
        return;
      }

      hw::HWModuleLike mod = modNode->getModule<hw::HWModuleLike>();
      SmallVector<unsigned> portIds;
      for (auto port : mod.getPortList()) {
        if (regex.match(port.getName())) {
          LLVM_DEBUG(llvm::dbgs() << "\t - Add:    " << port.getName() << "\n");
          if (port.isInput()) {
            portIds.push_back(mod.getPortIdForInputId(port.argNum));
          } else if (port.isOutput()) {
            portIds.push_back(mod.getPortIdForOutputId(port.argNum));
          } else {
            mod.emitError("hw-keep-ports: port '") << port.getName() << "' has an unsupported direction (inout)";
            signalPassFailure();
            return;
          }
        } else {
          LLVM_DEBUG(llvm::dbgs() << "\t - Ignore: " << port.getName() << "\n");
        }
      }

      if (portIds.empty()) {
        llvm::errs() << "No ports found!\n";
        signalPassFailure();
        return;
      }
      tagPorts(mod, portIds, KEEP);
    }
  }
};

} // namespace
} // namespace circt::cosimGen
