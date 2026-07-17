//===----------------------------------------------------------------------===//
//
// Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#include "circt/Dialect/Emit/EmitOps.h"
#include "circt/Dialect/HW/HWInstanceGraph.h"
#include "circt/Dialect/HW/HWOps.h"
#include "circt/Dialect/Seq/SeqOps.h"
#include "cosimGen/HWOpt.h"
#include "mlir/IR/IRMapping.h"
#include "mlir/Pass/Pass.h"
#include "mlir/Transforms/Inliner.h"
#include "mlir/Transforms/InliningUtils.h"
#include "llvm/ADT/PostOrderIterator.h"

#include "llvm/Support/Debug.h"
#define DEBUG_TYPE "hw-inline-trivial"

#include "cosimGen/Passes.h"

namespace circt::cosimGen {
#define GEN_PASS_DEF_HWINLINETRIVIAL
#include "cosimGen/Passes.h.inc"

namespace {

/* Copied from FlattenModules.cpp */
struct PrefixingInliner : public mlir::InlinerInterface {
  StringRef prefix;
  PrefixingInliner(MLIRContext *context, StringRef prefix) : InlinerInterface(context), prefix(prefix) {}

  bool isLegalToInline(Region *dest, Region *src, bool wouldBeCloned, IRMapping &valueMapping) const override {
    return true;
  }
  bool isLegalToInline(Operation *op, Region *dest, bool wouldBeCloned, IRMapping &valueMapping) const override {
    return true;
  }
  void handleTerminator(Operation *op, mlir::ValueRange valuesToRepl) const override {
    assert(isa<hw::OutputOp>(op));
    for (auto [from, to] : llvm::zip(valuesToRepl, op->getOperands()))
      from.replaceAllUsesWith(to);
  }

  void processInlinedBlocks(iterator_range<Region::iterator> inlinedBlocks) override {
    for (Block &block : inlinedBlocks)
      block.walk([&](Operation *op) { updateNames(op); });
  }

  StringAttr updateName(StringAttr attr) const {
    if (attr.getValue().empty())
      return attr;
    return StringAttr::get(attr.getContext(), prefix + "/" + attr.getValue());
  }

  void updateNames(Operation *op) const {
    if (auto name = op->getAttrOfType<StringAttr>("name"))
      op->setAttr("name", updateName(name));
    if (auto name = op->getAttrOfType<StringAttr>("instanceName"))
      op->setAttr("instanceName", updateName(name));
    if (auto namesAttr = op->getAttrOfType<ArrayAttr>("names")) {
      SmallVector<Attribute> names(namesAttr.getValue().begin(), namesAttr.getValue().end());
      for (auto &name : names)
        if (auto nameStr = dyn_cast<StringAttr>(name))
          name = updateName(nameStr);
      op->setAttr("names", ArrayAttr::get(namesAttr.getContext(), names));
    }
  }
};

struct HWInlineTrivialPass : impl::HWInlineTrivialBase<HWInlineTrivialPass> {
private:
  bool isTrivial(hw::HWModuleOp mod) {
    if (!mod || mod->getAttr(KEEP))
      return false;

    auto body = mod.getBodyBlock();
    unsigned no_ops = body->getOperations().size();
    auto hwOut = body->getTerminator();
    if (hwOut->getNumOperands() == 0 && hwOut->getNumResults() == 0) {
      llvm::errs() << mod.getModuleName() << "\n";
      return true;
    }
    /* Skip big modules to save time */
    if (no_ops > 1000)
      return false;

    bool instFound = false;
    for (Operation &op : *mod.getBodyBlock()) {
      if (isa<hw::OutputOp>(op)) {
        continue;
      }

      if (isa<hw::WireOp>(op) || isa<hw::ConstantOp>(op) || isa<seq::ConstClockOp>(op)) {
        continue;
      }

      if (isa<hw::InstanceOp>(op)) {
        if (instFound) {
          return false;
        }
        instFound = true;
        continue;
      }

      if (auto tainted = dyn_cast_or_null<BoolAttr>(op.getAttr(TAINTED)))
        if (tainted.getValue() == false)
          continue;

      return false;
    }

    return true;
  }

  hw::HWModuleOp getModuleOp(hw::InstanceOp inst) {
    Operation *topLevelOp = inst->getParentOfType<mlir::ModuleOp>(); // or something similar
    SymbolTable symbolTable(topLevelOp);
    return symbolTable.lookup<hw::HWModuleOp>(inst.getModuleName());
  }

  bool inlineInst(hw::InstanceOp inst, hw::HWModuleOp mod, bool isLastModuleUse) {
    PrefixingInliner inliner(&getContext(), inst.getInstanceName());
    if (failed(mlir::inlineRegion(inliner, config.getCloneCallback(), &mod.getBody(), inst, inst.getOperands(),
                                  inst.getResults(), std::nullopt, !isLastModuleUse))) {
      inst.emitError("failed to inline '")
          << mod.getModuleName() << "' into instance '" << inst.getInstanceName() << "'";
      signalPassFailure();
      return true;
    }

    if (auto modFrag = mod->getAttr(emit::getFragmentsAttrName())) {
      auto parent = inst->getParentOfType<hw::HWModuleOp>();
      if (auto pFrag = mod->getAttr(emit::getFragmentsAttrName())) {
        llvm::SetVector<mlir::Attribute> uniqueAttrs;
        for (auto attr : cast<ArrayAttr>(modFrag))
          uniqueAttrs.insert(attr);
        for (auto attr : cast<ArrayAttr>(pFrag))
          uniqueAttrs.insert(attr);
        parent->setAttr(emit::getFragmentsAttrName(),
                        mlir::ArrayAttr::get(parent->getContext(), uniqueAttrs.getArrayRef()));
      } else {
        parent->setAttr(emit::getFragmentsAttrName(), modFrag);
      }
    }

    return false;
  }

public:
  using impl::HWInlineTrivialBase<HWInlineTrivialPass>::HWInlineTrivialBase;
  mlir::InlinerConfig config;

  void runOnOperation() final {
    auto &instanceGraph = getAnalysis<hw::InstanceGraph>();
    DenseSet<Operation *> handled;

    for (auto *startNode : llvm::make_early_inc_range(instanceGraph)) {
      if (handled.contains(startNode->getModule().getOperation()))
        continue;

      auto postOrder = llvm::post_order(startNode);
      for (igraph::InstanceGraphNode *node : llvm::make_early_inc_range(postOrder)) {
        if (!handled.insert(node->getModule().getOperation()).second)
          continue;

        auto mod = dyn_cast_or_null<hw::HWModuleOp>(node->getModule().getOperation());
        if (!isTrivial(mod))
          continue;

        unsigned numUsesLeft = node->getNumUses();
        if (numUsesLeft == 0)
          continue;

        LLVM_DEBUG(llvm::dbgs() << "Inlining trivial module " << mod.getModuleName() << "\n");
        ++inline_module;

        for (auto *instRecord : llvm::make_early_inc_range(node->uses())) {
          auto inst = dyn_cast_or_null<hw::InstanceOp>(instRecord->getInstance().getOperation());
          if (inst) {
            bool isLastModuleUse = --numUsesLeft == 0;
            if (inlineInst(inst, mod, isLastModuleUse)) {
              return;
            }

            inst.erase();
            if (isLastModuleUse) {
              mod->erase();
            }
          } else {
            /* Public module => We have to keep it. But we can inline the one instance if there is one */
            hw::InstanceOp topInstOp;
            mod.walk([&](hw::InstanceOp op) { topInstOp = op; });
            if (topInstOp == nullptr)
              continue;

            auto instMod = getModuleOp(topInstOp);
            if (inlineInst(topInstOp, instMod, true))
              return;
            // std::string newName = (mod.getName() + "_" + instMod.getModuleName()).str();
            // mod.setName(newName);
            mod.setName(instMod.getModuleName());

            topInstOp.erase();
            instMod->erase();
          }
        }
      }
    }
  }
};

} // namespace
} // namespace circt::cosimGen
