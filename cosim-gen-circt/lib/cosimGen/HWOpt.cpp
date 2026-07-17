//===----------------------------------------------------------------------===//
//
// Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#include "cosimGen/HWOpt.h"

#include "circt/Dialect/Seq/SeqOps.h"
#include "mlir/Interfaces/SideEffectInterfaces.h"

#include "llvm/Support/Debug.h"
#define DEBUG_TYPE "hw-opt"

namespace circt {
namespace cosimGen {

static mlir::Value createDummyValue(OpBuilder &builder, mlir::Value val) {
  auto valType = val.getType();
  mlir::Operation *cOp = (isa<seq::ClockType>(valType))
                             ? seq::ConstClockOp::create(builder, val.getLoc(), seq::ClockConst::Low)
                             : hw::ConstantOp::create(builder, val.getLoc(), valType, 0);
  cOp->setAttr(DUMMY_CONST, UnitAttr::get(cOp->getContext()));
  return cOp->getResult(0);
}

void replaceOperandWithDummy(OpBuilder &builder, mlir::Operation *op, unsigned int operandId) {
  builder.setInsertionPoint(op);
  auto opVal = op->getOperand(operandId);
  auto cVal = createDummyValue(builder, opVal);
  op->setOperand(operandId, cVal);
}

void replaceValueWithDummy(OpBuilder &builder, mlir::Value val) {
  if (val.getNumUses() > 0) {
    if (auto ba = dyn_cast<BlockArgument>(val)) {
      auto block = ba.getOwner();
      assert(block != nullptr);
      builder.setInsertionPointToStart(block);
    } else {
      auto *op = val.getDefiningOp();
      assert(op != nullptr);
      builder.setInsertionPoint(op);
    }
    auto cVal = createDummyValue(builder, val);
    val.replaceAllUsesWith(cVal);
  }
}

static void deleteInst(igraph::InstanceGraph *igraph, igraph::InstanceOpInterface inst) {
  bool found = false;
  for (Attribute targetNameAttr : inst.getReferencedModuleNamesAttr()) {
    auto *node = igraph->lookup(cast<StringAttr>(targetNameAttr));
    for (auto *use : node->uses()) {
      if (use->getInstance() == inst) {
        assert(!found);
        found = true;
        use->erase();
        break;
      }
    }
  }
  assert(found);
}

static size_t eraseUnusedSet(llvm::SmallDenseSet<mlir::Operation *> &toDel, igraph::InstanceGraph *igraph) {
  // llvm::SmallDenseSet<mlir::Operation *> &deletedOps;
  size_t no_del_ops = 0;

  while (!toDel.empty()) {
    auto it = toDel.begin();
    auto eraseOp = *it;
    toDel.erase(it);
    if (eraseOp == nullptr)
      continue;
    assert(eraseOp->use_empty());

    if (igraph) {
      if (auto inst = dyn_cast<igraph::InstanceOpInterface>(eraseOp)) {
        deleteInst(igraph, inst);
      }
    }

    SmallVector<mlir::Operation *> nextOps;
    for (auto val : eraseOp->getOperands())
      if (auto *nextOp = val.getDefiningOp())
        nextOps.push_back(nextOp);

    eraseOp->erase();
    no_del_ops++;

    for (auto *nextOp : nextOps)
      if (nextOp->use_empty())
        toDel.insert(nextOp);
  }

  return no_del_ops;
}

size_t eraseUnusedSimple(hw::HWModuleOp hwModule, igraph::InstanceGraph *igraph) {
  llvm::SmallDenseSet<mlir::Operation *> toDel;
  hwModule.walk([&](Operation *op) {
    if ((!isa<hw::InstanceOp>(op) && op->getNumResults() < 1) || isa<hw::OutputOp, hw::HWModuleLike>(op))
      return;

    if (op->use_empty())
      toDel.insert(op);
  });

  return eraseUnusedSet(toDel, igraph);
}

size_t eraseUnused(hw::HWModuleOp hwModule, igraph::InstanceGraph *igraph) {
  llvm::SmallDenseSet<mlir::Operation *> toDel;
  size_t res = 0;

  auto terminator = cast<hw::OutputOp>(hwModule.getBodyBlock()->getTerminator());
  llvm::SmallDenseSet<mlir::Operation *> used = {terminator, hwModule};
  llvm::SmallDenseSet<mlir::Operation *> next = {terminator};

  // Add all operations with symbols
  hwModule.walk([&](Operation *op) {
    if (!used.contains(op)) {
      if (auto symOp = dyn_cast<hw::InnerSymbolOpInterface>(op)) {
        if (symOp.getInnerSymAttr()) {
          used.insert(op);
          next.insert(op);
        }
      } else {
        auto ns = op->getDialect()->getNamespace();
        if (ns == "sv" || ns == "sim") {
          used.insert(op);
          next.insert(op);
        }
      }
    }
  });

  while (!next.empty()) {
    auto it = next.begin();
    auto *op = *it;
    next.erase(it);
    for (auto val : op->getOperands()) {
      auto defOp = val.getDefiningOp();
      if (defOp == nullptr || !used.insert(defOp).second)
        continue;

      if (!isa<seq::FirRegOp>(defOp))
        if (auto memOp = dyn_cast<mlir::MemoryEffectOpInterface>(defOp)) {
          if (!memOp.hasNoEffect()) {
            for (auto use : defOp->getUsers()) {
              next.insert(use);
              used.insert(use);
            }
            // llvm::SmallVector<mlir::SideEffects::EffectInstance<mlir::MemoryEffects::Effect>> effects;
            // memOp.getEffects(effects);
          }
        }
      next.insert(defOp);
    }
  }

  hwModule.walk([&](Operation *op) {
    if (!used.contains(op)) {
      res++;
      toDel.insert(op);
      op->dropAllUses();
      op->dropAllReferences();
      if (igraph) {
        if (auto inst = dyn_cast<igraph::InstanceOpInterface>(op)) {
          deleteInst(igraph, inst);
        }
      }
      op->erase();
    }
  });
  toDel.clear();

  return res;
}

static bool potentiallyFoldable(mlir::Operation *op) { return (op != nullptr && op->getNumResults() == 1); }

static size_t tryFold(OpBuilder &builder, llvm::SmallDenseSet<mlir::Operation *> &toFold) {
  size_t no_of_folds = 0;

  while (!toFold.empty()) {
    auto it = toFold.begin();
    auto op = *it;
    toFold.erase(op);
    assert(op != nullptr);

    builder.setInsertionPoint(op);
    SmallVector<mlir::Value> results;
    if (succeeded(builder.tryFold(op, results)) && !results.empty()) {
      LLVM_DEBUG(llvm::dbgs() << "\tFold successful: " << *op << "\n");
      no_of_folds++;

      SmallVector<mlir::Operation *> nextOps;
      for (auto *nextOp : op->getUsers())
        if (potentiallyFoldable(nextOp))
          toFold.insert(nextOp);

      /* Replace op */
      assert(results.size() == op->getNumResults());
      op->replaceAllUsesWith(results);
    }
  }

  return no_of_folds;
};

size_t tryConstFold(hw::HWModuleOp hwModule, OpBuilder &builder) {
  llvm::SmallDenseSet<mlir::Operation *> potenialFolds;

  hwModule.walk([&](hw::ConstantOp constOp) {
    for (auto *op : constOp->getUsers())
      if (potentiallyFoldable(op))
        potenialFolds.insert(op);
  });

  return tryFold(builder, potenialFolds);
}

} // namespace cosimGen
} // namespace circt
