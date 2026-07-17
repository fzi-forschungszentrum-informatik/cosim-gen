//===----------------------------------------------------------------------===//
//
// Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#include "circt/Dialect/Comb/CombOps.h"
#include "mlir/IR/IRMapping.h"
#include "mlir/Pass/Pass.h"

#include "common/PathComp.h"
#include "cosimGen/HWOpt.h"
#include "cosimGen/PortTagging.h"

#include "llvm/Support/Debug.h"
#define DEBUG_TYPE "hw-opt-interfaces"

#include "cosimGen/Passes.h"

namespace circt::cosimGen {
#define GEN_PASS_DEF_HWMOVECOMBUP
#include "cosimGen/Passes.h.inc"

namespace {

struct HWMoveCombUpPass : impl::HWMoveCombUpBase<HWMoveCombUpPass> {
private:
  bool isMoveableOp(mlir::Operation *op) {
    return op->hasTrait<mlir::OpTrait::ConstantLike>() || llvm::isa<comb::ExtractOp>(op) ||
           llvm::isa<comb::ConcatOp>(op);
  }

  void getIgnorePorts(hw::HWModuleOp hwModule, SetVector<unsigned int> &ignorePorts) {
    auto portAttrs = hwModule.getAllPortAttrs();
    for (auto [portId, attr] : llvm::enumerate(portAttrs)) {
      auto attrDict = dyn_cast<DictionaryAttr>(portAttrs[portId]);
      if (attrDict.contains(UNUSED) || attrDict.contains(KEEP)) {
        ignorePorts.insert(portId);
      }
    }
  }

  bool isInPort(mlir::Value val) {
    auto op = val.getDefiningOp();
    if (!op)
      return true;
    if (auto inst = llvm::dyn_cast<hw::InstanceOp>(op))
      return true;
    return false;
  }

  bool isMoveableIn(hw::InstanceOp inst, mlir::Value val, llvm::SmallSetVector<mlir::Operation *, 16> &ops,
                    mlir::Value &src) {
    if (isInPort(val)) {
      if (ops.empty() || (src && (src != val)))
        return false;

      src = val;
      return true;
    }

    auto op = val.getDefiningOp();
    assert(op);

    if (!isMoveableOp(op))
      return false;

    if (!ops.insert(op)) {
      // Already processed this op - only return true if src is already set
      return src != nullptr;
    }

    for (mlir::Value oper : op->getOperands())
      if (!isMoveableIn(inst, oper, ops, src))
        return false;

    // After processing all operands, src must be set
    return src != nullptr;
  }

  void handleInputs(OpBuilder &builder, igraph::InstanceRecord *instRec, SetVector<unsigned int> &ignorePorts) {
    auto inst = instRec->getInstance<hw::InstanceOp>();
    auto instMod = instRec->getTarget()->getModule<hw::HWModuleOp>();
    auto *body = instMod.getBodyBlock();

    for (auto arg : body->getArguments()) {
      unsigned inputId = arg.getArgNumber();
      unsigned portId = instMod.getPortIdForInputId(inputId);
      if (ignorePorts.contains(portId))
        continue;

      if (inputId >= inst->getNumOperands()) {
        inst.emitError("hw-move-comb-up: instance has fewer operands than its target module '")
            << instMod.getModuleName() << "' has input ports - are they out of sync?";
        signalPassFailure();
        return;
      }

      llvm::SmallSetVector<mlir::Operation *, 16> allOps;
      mlir::Value src = nullptr;

      if (isMoveableIn(inst, inst.getOperand(inputId), allOps, src) && src) {
        inst.setOperand(inputId, src);

        auto blockArg = body->getArgument(inputId);
        auto newPort = instMod.getPort(portId);
        newPort.type = src.getType();
        instMod.modifyPorts({std::make_pair(inputId, newPort)}, {}, {inputId}, {});
        blockArg.setType(src.getType());

        llvm::SmallVector<mlir::Operation *> sortedOps(allOps.rbegin(), allOps.rend());
        builder.setInsertionPointToStart(instMod.getBodyBlock());
        mlir::IRMapping mapping;
        auto tmpOp = hw::ConstantOp::create(builder, blockArg.getLoc(), src.getType(), 0);
        auto tmpVal = tmpOp.getResult();
        mapping.map(src, tmpVal);

        mlir::Value firstVal;
        for (mlir::Operation *op : sortedOps) {
          auto *copyOp = builder.clone(*op, mapping);
          firstVal = copyOp->getResult(0);
        }

        blockArg.replaceAllUsesWith(firstVal);
        tmpVal.replaceAllUsesWith(blockArg);
        tmpOp.erase();
      }
    }
  }

  bool isSingleOutConnection(mlir::Value val) {
    if (val.getNumUses() != 1)
      return false;
    auto &use = *val.getUses().begin();
    auto *owner = use.getOwner();

    if (llvm::isa<hw::InstanceOp>(owner) || llvm::isa<hw::OutputOp>(owner))
      return true;

    return false;
  }

  bool collectOut(hw::InstanceOp inst, mlir::Value val, llvm::SmallSetVector<mlir::Operation *, 16> &ops,
                  mlir::Value &src) {
    if (val == src) {
      return true;
    }

    auto op = val.getDefiningOp();
    assert(op);

    if (!isMoveableOp(op))
      return false;

    if (!ops.insert(op))
      return true;

    for (mlir::Value oper : op->getOperands())
      if (!collectOut(inst, oper, ops, src))
        return false;

    return true;
  }

  bool isMoveableOut(hw::InstanceOp inst, mlir::Value srcVal, llvm::SmallSetVector<mlir::Operation *, 16> &ops,
                     mlir::Value &dst) {
    if (!srcVal.hasOneUse())
      return false;

    auto *nextOp = *srcVal.getUsers().begin();
    if (!isMoveableOp(nextOp))
      return false;
    assert(nextOp->getNumResults() == 1);
    dst = nextOp->getResult(0);
    ops.insert(nextOp);

    while (!isSingleOutConnection(dst)) {
      assert(nextOp->getNumResults() == 1);
      dst = nextOp->getResult(0);
      if (!dst.hasOneUse())
        return false;

      nextOp = *dst.getUsers().begin();
      if (!isMoveableOp(nextOp) || !ops.insert(nextOp))
        return false;
    };

    ops.clear();
    assert(dst != nullptr);
    assert(dst != srcVal);
    return collectOut(inst, dst, ops, srcVal);
  }

  void handleOutputs(OpBuilder &builder, igraph::InstanceRecord *instRec, SetVector<unsigned int> &ignorePorts) {
    auto inst = instRec->getInstance<hw::InstanceOp>();
    auto instMod = instRec->getTarget()->getModule<hw::HWModuleOp>();
    auto outputOp = cast<hw::OutputOp>(instMod.getBodyBlock()->getTerminator());

    for (auto &opop : outputOp->getOpOperands()) {
      unsigned outputId = opop.getOperandNumber();
      unsigned portId = instMod.getPortIdForOutputId(outputId);
      if (ignorePorts.contains(portId))
        continue;

      auto instVal = inst.getResult(outputId);
      llvm::SmallSetVector<mlir::Operation *, 16> allOps;
      mlir::Value dst = nullptr;

      if (isMoveableOut(inst, instVal, allOps, dst)) {
        auto outVal = outputOp->getOperand(outputId);

        auto newPort = instMod.getPort(portId);
        newPort.type = dst.getType();
        instMod.modifyPorts({}, {std::make_pair(outputId, newPort)}, {}, {outputId});

        llvm::SmallVector<mlir::Operation *> sortedOps(allOps.rbegin(), allOps.rend());
        builder.setInsertionPointToStart(instMod.getBodyBlock());
        mlir::IRMapping mapping;
        mapping.map(instVal, outVal);

        mlir::Value lastVal;
        for (mlir::Operation *op : sortedOps) {
          auto *copyOp = builder.clone(*op, mapping);
          lastVal = copyOp->getResult(0);
        }

        outputOp.setOperand(outputId, lastVal);

        builder.setInsertionPointAfter(inst);
        auto instRes = inst.getResult(outputId);
        auto dummyOp = hw::ConstantOp::create(builder, instRes.getLoc(), instRes.getType(), 0);
        auto dummyVal = dummyOp.getResult();
        instRes.replaceAllUsesWith(dummyVal);

        inst.getResult(outputId).setType(dst.getType());
        dst.replaceAllUsesWith(inst.getResult(outputId));

        assert(inst.getResult(outputId).getType() == outputOp.getOperand(outputId).getType());
      }
    }
  }

public:
  using impl::HWMoveCombUpBase<HWMoveCombUpPass>::HWMoveCombUpBase;

  void runOnOperation() final {
    hw::InstanceGraph &instGraph = getAnalysis<hw::InstanceGraph>();
    igraph::InstancePathCache instancePathCache(instGraph);
    OpBuilder builder(getOperation().getContext());

    auto searchPathResult = strPath2circtPath(instancePathCache, path);
    if (!searchPathResult) {
      llvm::errs() << "Error: " << llvm::toString(searchPathResult.takeError()) << "\n";
      signalPassFailure();
      return;
    }
    auto &searchPath = *searchPathResult;

    auto *instRec = getInstanceRecord(instancePathCache, searchPath);
    if (!instRec) {
      llvm::errs() << "Module path not found: " << path;
      signalPassFailure();
      return;
    }
    for (auto *otherRec : instRec->getTarget()->uses()) {
      if (otherRec == instRec || !otherRec->getInstance())
        continue;

      llvm::errs() << instRec->getTarget()->getModule().getModuleName()
                   << " has more then one instance - which is currently not supported\n";
      signalPassFailure();
      return;
    }

    SetVector<unsigned int> ignorePorts;
    getIgnorePorts(instRec->getTarget()->getModule<hw::HWModuleOp>(), ignorePorts);
    handleInputs(builder, instRec, ignorePorts);
    handleOutputs(builder, instRec, ignorePorts);
  }
};

} // namespace
} // namespace circt::cosimGen
