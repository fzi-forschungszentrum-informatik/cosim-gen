//===----------------------------------------------------------------------===//
//
// Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#include "circt/Dialect/Emit/EmitOps.h"
#include "mlir/Pass/Pass.h"

#include "cosimGen/HWOpt.h"

#include "llvm/Support/Debug.h"
#define DEBUG_TYPE "hw-remove-sv"

#include "cosimGen/Passes.h"

namespace circt::cosimGen {
#define GEN_PASS_DEF_HWREMOVECUSTOMATTR
#include "cosimGen/Passes.h.inc"

namespace {

struct HWRemoveCustomAttrPass : impl::HWRemoveCustomAttrBase<HWRemoveCustomAttrPass> {
private:
public:
  using impl::HWRemoveCustomAttrBase<HWRemoveCustomAttrPass>::HWRemoveCustomAttrBase;

  void runOnOperation() final {
    auto mod = getOperation();

    mod.walk([&](mlir::Operation *op) {
      op->removeAttr(KEEP);
      op->removeAttr(UNUSED);
      op->removeAttr(DUMMY_CONST);
      op->removeAttr(TAINTED);
      op->removeAttr(GRAPH_HIDE);
    });

    // Per-port attributes
    static constexpr llvm::StringRef customPortTags[] = {KEEP, UNUSED, DUMMY_CONST, TAINTED, GRAPH_HIDE};
    for (size_t portNum = 0, e = mod.getNumPorts(); portNum < e; ++portNum) {
      auto attrs = dyn_cast_or_null<DictionaryAttr>(mod.getPortAttrs(portNum));
      if (!attrs || attrs.empty())
        continue;

      SmallVector<NamedAttribute> kept;
      for (auto namedAttr : attrs)
        if (!llvm::is_contained(customPortTags, namedAttr.getName().getValue()))
          kept.push_back(namedAttr);

      if (kept.size() != attrs.size())
        mod.setPortAttrs(portNum, DictionaryAttr::get(mod->getContext(), kept));
    }
  }
};

} // namespace
} // namespace circt::cosimGen
