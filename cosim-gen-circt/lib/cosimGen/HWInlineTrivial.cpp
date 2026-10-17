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
#include "circt/Dialect/HW/InnerSymbolNamespace.h"
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

struct PrefixingInliner : public mlir::InlinerInterface {
  StringRef prefix;
  mlir::AttrTypeReplacer &replacer;

  PrefixingInliner(MLIRContext *context, StringRef prefix, mlir::AttrTypeReplacer &replacer)
      : InlinerInterface(context), prefix(prefix), replacer(replacer) {}

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
      block.walk([&](Operation *op) {
        updateNames(op);
        replacer.replaceElementsIn(op);
      });
  }

  StringAttr updateName(StringAttr attr) const {
    if (attr.getValue().empty())
      return attr;
    return StringAttr::get(attr.getContext(), prefix + "/" + attr.getValue());
  }

  void updateNames(Operation *op) const {
    for (auto key : {"name", "instanceName"})
      if (auto name = op->getAttrOfType<StringAttr>(key))
        op->setAttr(key, updateName(name));
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
    if (hwOut->getNumOperands() == 0 && hwOut->getNumResults() == 0)
      return true;
    /* Skip big modules to save time */
    if (no_ops > 1000)
      return false;

    bool instFound = false;
    for (Operation &op : *mod.getBodyBlock()) {
      if (isa<hw::OutputOp, hw::WireOp, hw::ConstantOp, seq::ConstClockOp>(op))
        continue;

      if (isa<hw::InstanceOp>(op)) {
        if (instFound)
          return false;
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

  LogicalResult inlineInst(hw::InstanceOp inst, hw::HWModuleOp mod, bool isLastModuleUse,
                           hw::InnerSymbolNamespaceCollection &namespaces, StringAttr targetName = {}) {
    auto parentModule = inst->getParentOfType<hw::HWModuleOp>();
    if (!targetName)
      targetName = parentModule.getModuleNameAttr();
    auto &ns = namespaces[parentModule];

    // Fresh names in the parent, so inlining one module twice doesn't duplicate its inner symbols.
    DenseMap<StringAttr, StringAttr> oldToNewInnerSyms;
    mod.walk([&](Operation *op) {
      if (auto sym = op->getAttrOfType<hw::InnerSymAttr>(hw::InnerSymbolTable::getInnerSymbolAttrName()))
        for (auto prop : sym.getProps())
          oldToNewInnerSyms[prop.getName()] = StringAttr::get(&getContext(), ns.newName(prop.getName().getValue()));
    });
    mlir::AttrTypeReplacer replacer;
    replacer.addReplacement([&](hw::InnerSymPropertiesAttr attr) {
      auto name = oldToNewInnerSyms.lookup(attr.getName());
      return name ? hw::InnerSymPropertiesAttr::get(&getContext(), name, attr.getFieldID(), attr.getSymVisibility())
                  : attr;
    });
    replacer.addReplacement([&](hw::InnerRefAttr attr) -> std::pair<Attribute, WalkResult> {
      if (attr.getModule() != mod.getModuleNameAttr())
        return {attr, WalkResult::skip()};
      auto it = oldToNewInnerSyms.find(attr.getName());
      if (it == oldToNewInnerSyms.end())
        return {attr, WalkResult::skip()};
      return {hw::InnerRefAttr::get(targetName, it->second), WalkResult::skip()};
    });
    PrefixingInliner inliner(&getContext(), inst.getInstanceName(), replacer);
    mlir::InlinerConfig config;
    if (failed(mlir::inlineRegion(inliner, config.getCloneCallback(), &mod.getBody(), inst, inst.getOperands(),
                                  inst.getResults(), std::nullopt, !isLastModuleUse)))
      return inst.emitError("failed to inline '")
             << mod.getModuleName() << "' into instance '" << inst.getInstanceName() << "'";

    if (mod->hasAttr(emit::getFragmentsAttrName())) {
      llvm::SetVector<Attribute> fragments;
      for (auto module : {mod, parentModule})
        if (auto attrs = module->getAttrOfType<ArrayAttr>(emit::getFragmentsAttrName()))
          fragments.insert(attrs.begin(), attrs.end());
      parentModule->setAttr(emit::getFragmentsAttrName(), ArrayAttr::get(&getContext(), fragments.getArrayRef()));
    }

    return success();
  }

public:
  using impl::HWInlineTrivialBase<HWInlineTrivialPass>::HWInlineTrivialBase;

  void runOnOperation() final {
    auto &instanceGraph = getAnalysis<hw::InstanceGraph>();
    DenseSet<Operation *> handled;
    hw::InnerSymbolNamespaceCollection namespaces;

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
            if (failed(inlineInst(inst, mod, isLastModuleUse, namespaces)))
              return signalPassFailure();

            inst.erase();
            if (isLastModuleUse)
              mod->erase();
          } else {
            /* Keep public modules, but inline their sole child when unshared */
            hw::InstanceOp topInstOp;
            mod.walk([&](hw::InstanceOp op) { topInstOp = op; });
            if (topInstOp == nullptr)
              continue;

            auto *instNode = instanceGraph.lookup(topInstOp.getModuleNameAttr().getAttr());
            auto instMod = dyn_cast<hw::HWModuleOp>(instNode->getModule().getOperation());
            if (!instMod || instMod->getAttr(KEEP) || instNode->getNumUses() != 1)
              continue;
            if (failed(inlineInst(topInstOp, instMod, true, namespaces, instMod.getModuleNameAttr())))
              return signalPassFailure();
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
