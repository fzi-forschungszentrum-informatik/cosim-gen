//===----------------------------------------------------------------------===//
//
// Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#include "circt/Dialect/Comb/CombOps.h"
#include "circt/Dialect/HW/HWInstanceGraph.h"
#include "circt/Dialect/HW/HWOps.h"
#include "circt/Dialect/SV/SVOps.h"
#include "circt/Dialect/Seq/SeqOps.h"
#include "cosimGen/HWOpt.h"
#include "cosimGen/PortTagging.h"
#include "mlir/IR/IRMapping.h"
#include "mlir/IR/Verifier.h"
#include "mlir/Pass/Pass.h"

#include "llvm/Support/Debug.h"
#define DEBUG_TYPE "hw-opt-interfaces"

#include "cosimGen/Passes.h"

namespace circt::cosimGen {
#define GEN_PASS_DEF_HWOPTINTERFACES
#include "cosimGen/Passes.h.inc"

namespace {

struct HWOptInterfacesPass : impl::HWOptInterfacesBase<HWOptInterfacesPass> {
private:
  llvm::SetVector<hw::HWModuleLike> processedModules;
  igraph::InstanceGraph *instGraph;

public:
  using impl::HWOptInterfacesBase<HWOptInterfacesPass>::HWOptInterfacesBase;

  bool isMoveableOp(mlir::Operation *op) {
    return op->hasTrait<mlir::OpTrait::ConstantLike>() || llvm::isa<comb::ExtractOp>(op) ||
           llvm::isa<comb::ConcatOp>(op);
  }

  hw::HWModuleLike getParentModule(mlir::Value val) {
    if (auto arg = dyn_cast<mlir::BlockArgument>(val)) {
      if (auto *block = arg.getOwner())
        if (auto *parentOp = block->getParentOp()) {
          if (auto mod = dyn_cast<hw::HWModuleLike>(parentOp))
            return mod;
          return parentOp->getParentOfType<hw::HWModuleLike>();
        }
    }

    if (auto *defOp = val.getDefiningOp()) {
      return defOp->getParentOfType<hw::HWModuleLike>();
    }

    return nullptr;
  }

  bool isMoveableDown(mlir::Value val) {
    if (auto arg = llvm::dyn_cast<mlir::BlockArgument>(val))
      return true;

    mlir::Operation *defOp = val.getDefiningOp();
    assert(defOp);
    if (!isMoveableOp(defOp))
      return false;

    llvm::SmallVector<mlir::Value> worklist(defOp->getOperands().begin(), defOp->getOperands().end());
    // std::optional<unsigned> foundPort;

    while (!worklist.empty()) {
      mlir::Value curVal = worklist.pop_back_val();

      if (auto arg = llvm::dyn_cast<mlir::BlockArgument>(curVal)) {
        // unsigned port = arg.getArgNumber();
        // if (foundPort && *foundPort != port)
        // return false;
        // foundPort = port;
        continue;
      }

      mlir::Operation *curOp = curVal.getDefiningOp();
      assert(curOp);
      if (!isMoveableOp(curOp))
        return false;

      for (mlir::Value operand : curOp->getOperands())
        worklist.push_back(operand);
    }
    return true;
  }

  bool isMoveableUp(hw::InstanceOp inst, mlir::Value val) {
    mlir::Operation *defOp = val.getDefiningOp();
    if (!defOp)
      return false;

    if (defOp == inst)
      return true;
    if (!isMoveableOp(defOp))
      return false;

    llvm::SmallVector<mlir::Value> worklist(defOp->getOperands().begin(), defOp->getOperands().end());
    while (!worklist.empty()) {
      mlir::Value curVal = worklist.pop_back_val();
      mlir::Operation *curOp = curVal.getDefiningOp();
      if (!curOp)
        return false;

      if (curOp == inst)
        continue;

      if (!isMoveableOp(curOp))
        return false;

      for (mlir::Value operand : curOp->getOperands())
        worklist.push_back(operand);
    }
    return true;
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

  void replaceNodeModule(OpBuilder &builder, igraph::InstanceGraphNode *node, llvm::SmallVector<unsigned int> &optIns,
                         llvm::SmallVector<unsigned int> &optOuts) {
    auto hwModule = dyn_cast<hw::HWModuleOp>(node->getModule().getOperation());
    auto *body = hwModule.getBodyBlock();
    hw::OutputOp outputOp = cast<hw::OutputOp>(body->getTerminator());

    llvm::sort(optIns);
    llvm::sort(optOuts);

    assert(std::adjacent_find(optIns.begin(), optIns.end()) == optIns.end() && "optIns contains duplicate IDs");
    assert(std::adjacent_find(optOuts.begin(), optOuts.end()) == optOuts.end() && "optOuts contains duplicate IDs");

    if (!keepPorts) {
      /* Change ports */
      hwModule.modifyPorts({}, {}, optIns, optOuts);

      /* Inverse order of ids, because all ids after change */
      /* Delete outputs before inputs due to u-turn uses */
      for (auto id : llvm::reverse(optOuts))
        outputOp->eraseOperand(id);

      for (auto id : llvm::reverse(optIns))
        body->eraseArgument(id);

    } else {
      /* Inputs already handled (unused or const val)*/
      /* Outputs replace all outs with dummy const  */
      for (auto id : optOuts)
        replaceOperandWithDummy(builder, outputOp, id);
    }
  }

  void replaceNodeInsts(OpBuilder &builder, igraph::InstanceGraphNode *node, SmallVector<unsigned int> &optIns,
                        SmallVector<unsigned int> &optOuts) {
    auto hwModule = dyn_cast<hw::HWModuleOp>(node->getModule().getOperation());

    for (auto use : llvm::make_early_inc_range(node->uses())) {
      auto inst = dyn_cast_or_null<hw::InstanceOp>(use->getInstance().getOperation());
      if (!inst)
        continue;
      no_insts++;

      if (!keepPorts) {
        /* Replace instances */
        SmallVector<mlir::Value> newInstInputs;
        for (auto &input : inst->getOpOperands()) {
          if (!llvm::is_contained(optIns, input.getOperandNumber())) {
            newInstInputs.push_back(input.get());
          }
        };

        builder.setInsertionPoint(inst);
        hw::InstanceOp newInst =
            hw::InstanceOp::create(builder, inst.getLoc(), hwModule, inst.getInstanceName(), newInstInputs);
        newInst.setInnerSymAttr(inst.getInnerSymAttr());

        unsigned newPortId = 0;
        for (auto [i, output] : llvm::enumerate(inst->getResults())) {
          if (!llvm::is_contained(optOuts, i)) {
            output.replaceAllUsesWith(newInst.getResult(newPortId++));
          } else {
            /* Old u-turn, old const out or unused */
            assert(output.use_empty());
          }
        }

        assert(inst->use_empty());
        instGraph->replaceInstance(inst, newInst);
        inst->erase();

        inst = newInst;

      } else {
        /* Keep ports: Just replace unused values with marked dummies */
        for (auto id : optIns)
          replaceOperandWithDummy(builder, inst, id);
      }

      if (inst->use_empty()) {
        // inst->setAttr(UNUSED, UnitAttr::get(curInst->getContext()));
        use->erase();
        inst->erase();
      }
    }
  }

  void tagUnusedPorts(igraph::InstanceGraphNode *node, SmallVector<unsigned int> &optIns,
                      SmallVector<unsigned int> &optOuts) {
    auto hwModule = dyn_cast<hw::HWModuleOp>(node->getModule().getOperation());
    SmallVector<unsigned int> portsIds;
    for (auto id : optIns) {
      portsIds.push_back(hwModule.getPortIdForInputId(id));
    }
    for (auto id : optOuts) {
      portsIds.push_back(hwModule.getPortIdForOutputId(id));
    }
    tagPorts(hwModule, portsIds, UNUSED);
  };

  void updateNode(OpBuilder &builder, igraph::InstanceGraphNode *node, SmallVector<unsigned int> &optIns,
                  SmallVector<unsigned int> &optOuts) {
    tagUnusedPorts(node, optIns, optOuts);
    replaceNodeModule(builder, node, optIns, optOuts);
    replaceNodeInsts(builder, node, optIns, optOuts);
  }

  bool removeUnusedPorts(OpBuilder &builder, igraph::InstanceGraphNode *node) {
    auto hwModule = node->getModule<hw::HWModuleOp>();
    auto *body = hwModule.getBodyBlock();
    SmallVector<unsigned int> unusedIns, unusedOuts;
    SetVector<unsigned int> ignorePorts;
    getIgnorePorts(hwModule, ignorePorts);

    for (auto arg : body->getArguments()) {
      unsigned inputId = arg.getArgNumber();
      unsigned portId = hwModule.getPortIdForInputId(inputId);
      if (ignorePorts.contains(portId))
        continue;

      if (arg.use_empty())
        unusedIns.push_back(inputId);
    }

    bool firstInst = true;
    for (auto *userRec : node->uses()) {
      auto instance = dyn_cast_or_null<hw::InstanceOp>(userRec->getInstance().getOperation());
      if (!instance)
        continue;

      for (auto result : instance->getOpResults()) {
        unsigned rId = result.getResultNumber();
        unsigned portId = hwModule.getPortIdForOutputId(rId);
        if (ignorePorts.contains(portId))
          continue;

        bool isUnusedHere = result.use_empty();

        if (firstInst) {
          if (isUnusedHere)
            unusedOuts.push_back(rId);
        } else {
          if (!isUnusedHere) {
            auto it = llvm::find(unusedOuts, rId);
            if (it != unusedOuts.end())
              unusedOuts.erase(it);
          }
        }
      }

      firstInst = false;
    }

    size_t unused_ports = unusedIns.size() + unusedOuts.size();
    if (unused_ports == 0)
      return false;
    no_unused_ports += unused_ports;

    for (auto uIn : unusedIns)
      LLVM_DEBUG(llvm::dbgs() << "\t- Found unused input@" << uIn << ": " << hwModule.getInputName(uIn) << "\n");
    for (auto uOut : unusedOuts)
      LLVM_DEBUG(llvm::dbgs() << "\t- Found unused output@" << uOut << ": " << hwModule.getOutputName(uOut) << "\n");

    updateNode(builder, node, unusedIns, unusedOuts);

    return true;
  }

  bool areEquivalentVals(mlir::Value lhs, Operation *lhsTgt, mlir::Value rhs, Operation *rhsTgt) {
    if (rhs == lhs)
      return true;

    if (lhs.getType() != rhs.getType())
      return false;

    auto *defOpA = lhs.getDefiningOp();
    auto *defOpB = rhs.getDefiningOp();
    if (!defOpA || !defOpB || (defOpA->getName() != defOpB->getName()))
      return false;

    /* Same constant input */
    if (auto constL = lhs.getDefiningOp<hw::ConstantOp>())
      if (auto constR = rhs.getDefiningOp<hw::ConstantOp>())
        if (constL.getValue() == constR.getValue())
          return true;

    /* Same inst uturn */
    if (auto instL = lhs.getDefiningOp<hw::InstanceOp>())
      if (auto instR = rhs.getDefiningOp<hw::InstanceOp>()) {
        auto lhsRes = dyn_cast<OpResult>(lhs);
        auto rhsRes = dyn_cast<OpResult>(rhs);
        if ((instL == lhsTgt) && (instR == rhsTgt) && (rhsRes.getResultNumber() == lhsRes.getResultNumber()))
          return true;
      }

    /* Same constant clock */
    if (auto constL = lhs.getDefiningOp<seq::ConstClockOp>())
      if (auto constR = rhs.getDefiningOp<seq::ConstClockOp>())
        if (constL.getValue() == constR.getValue())
          return true;

    llvm::errs() << "ToDo: Might be the same: \n" << lhs << "\n == \n" << rhs << "\n";
    /* ToDo: Check more complex scenarios */
    return false;
  }

  bool rewireModule(OpBuilder &builder, igraph::InstanceGraphNode *node) {
    auto hwModule = dyn_cast<hw::HWModuleOp>(node->getModule().getOperation());
    bool isTop = llvm::none_of(node->uses(), [](auto *use) { return use->getInstance(); });
    if (isTop || hwModule->getAttr(KEEP))
      return false;

    auto *body = hwModule.getBodyBlock();
    auto outputOp = cast<hw::OutputOp>(body->getTerminator());

    SmallVector<unsigned int> moveableIns, moveableOuts;
    SetVector<unsigned int> ignorePorts;
    getIgnorePorts(hwModule, ignorePorts);

    // Move all direct connection from the module up the their insts
    for (auto &opoutput : outputOp->getOpOperands()) {
      auto oId = opoutput.getOperandNumber();
      if (ignorePorts.contains(hwModule.getPortIdForOutputId(oId)))
        continue;

      auto val = opoutput.get();
      if (isMoveableDown(val)) {
        moveableOuts.push_back(oId);

        llvm::SmallSetVector<mlir::Operation *, 16> allOps;
        llvm::SmallVector<mlir::BlockArgument> allPorts;
        collectDependencies(val, allOps, allPorts);
        llvm::SmallVector<mlir::Operation *> sortedOps(allOps.rbegin(), allOps.rend());
        assert(sortedOps.size() + allPorts.size() > 0);

        for (auto use : llvm::make_early_inc_range(node->uses())) {
          auto inst = dyn_cast_or_null<hw::InstanceOp>(use->getInstance().getOperation());
          if (!inst)
            continue;

          mlir::Value lastResult;
          mlir::IRMapping mapping;
          builder.setInsertionPoint(inst);

          for (auto port : allPorts) {
            auto iId = port.getArgNumber();
            auto inVal = inst.getOperand(iId);
            lastResult = inVal;
            mapping.map(port, inVal);
          }

          for (mlir::Operation *op : sortedOps) {
            assert(op->getNumResults() == 1);
            auto *copyOp = builder.clone(*op, mapping);
            lastResult = copyOp->getResult(0);
          }

          assert(inst->getResult(oId).getType() == lastResult.getType());
          inst->getResult(oId).replaceAllUsesWith(lastResult);
        }
      }
    }

    SmallVector<mlir::Value> firstPotVals(hwModule.getNumInputPorts(), nullptr);
    hw::InstanceOp firstInst = nullptr;

    for (auto *instRec : node->uses()) {
      auto inst = dyn_cast_or_null<hw::InstanceOp>(instRec->getInstance().getOperation());
      if (inst == nullptr)
        continue;

      for (auto [i, opOp] : llvm::enumerate(inst->getOpOperands())) {
        auto opId = opOp.getOperandNumber();
        auto opVal = opOp.get();

        if (ignorePorts.contains(hwModule.getPortIdForInputId(opId)))
          continue;

        if (!firstInst) {
          if (isMoveableUp(inst, opVal)) {
            moveableIns.push_back(opId);
            firstPotVals[i] = opVal;
          }
        } else {
          auto firstVal = firstPotVals[i];
          if (firstVal)
            assert(firstVal.getType() == opVal.getType());

          if (firstVal && !areEquivalentVals(firstVal, firstInst, opVal, inst)) {
            firstPotVals[i] = nullptr;
            moveableIns.erase(llvm::find(moveableIns, opId));
          }
        }
      }

      if (!firstInst)
        firstInst = inst;
    }

    for (auto mIn : moveableIns)
      LLVM_DEBUG(llvm::dbgs() << "\t- Found moveable input@" << mIn << ": " << hwModule.getInputName(mIn) << "\n");

    for (auto iId : moveableIns) {
      assert(firstInst);
      builder.setInsertionPointToStart(hwModule.getBodyBlock());
      mlir::IRMapping mapping;

      llvm::SmallSetVector<mlir::Operation *, 16> allOps;
      llvm::SmallVector<mlir::OpResult> allPorts;
      collectDependenciesInsts(firstInst, firstInst.getOperand(iId), allOps, allPorts);
      llvm::SmallVector<mlir::Operation *> sortedOps(allOps.rbegin(), allOps.rend());
      assert(sortedOps.size() + allPorts.size() > 0);

      mlir::Value lastResult;
      auto outputOp = cast<hw::OutputOp>(body->getTerminator());
      for (auto port : allPorts) {
        auto oId = port.getResultNumber();
        auto inVal = outputOp.getOperand(oId);
        lastResult = inVal;
        mapping.map(port, inVal);

        assert(llvm::find(moveableOuts, oId) == moveableOuts.end());
      }

      for (mlir::Operation *op : sortedOps) {
        auto *copyOp = builder.clone(*op, mapping);
        lastResult = copyOp->getResult(0);
      }

      assert(body->getArgument(iId).getType() == lastResult.getType());
      assert(getParentModule(lastResult) == hwModule);
      body->getArgument(iId).replaceAllUsesWith(lastResult);
    }

    if ((moveableIns.size() + moveableOuts.size()) == 0)
      return false;

    updateNode(builder, node, moveableIns, moveableOuts);
    return true;
  }

  bool combinePorts(OpBuilder &builder, igraph::InstanceGraphNode *node) {
    auto hwModule = dyn_cast<hw::HWModuleOp>(node->getModule().getOperation());
    bool isTop = llvm::none_of(node->uses(), [](auto *use) { return use->getInstance(); });
    auto *body = hwModule.getBodyBlock();
    auto outputOp = cast<hw::OutputOp>(body->getTerminator());

    SmallVector<unsigned int> combinableIns, combinableOuts;
    SetVector<unsigned int> ignorePorts;
    getIgnorePorts(hwModule, ignorePorts);

    for (auto &opoutput : outputOp->getOpOperands()) {
      auto tId = opoutput.getOperandNumber();
      auto tVal = opoutput.get();
      if (isTop || ignorePorts.contains(hwModule.getPortIdForOutputId(tId)))
        continue;

      for (auto &other : outputOp->getOpOperands()) {
        auto oId = other.getOperandNumber();
        auto oVal = other.get();

        if (tId == oId)
          continue;

        /* Never combine away a {keep}/{unused} port - it must survive here */
        if (ignorePorts.contains(hwModule.getPortIdForOutputId(oId)))
          continue;

        if (tVal == oVal) {
          combinableOuts.push_back(oId);
          ignorePorts.insert(hwModule.getPortIdForOutputId(oId));

          for (auto *instRec : node->uses()) {
            auto inst = dyn_cast_or_null<hw::InstanceOp>(instRec->getInstance().getOperation());
            if (inst == nullptr)
              continue;

            assert(inst.getResult(oId).getType() == inst.getResult(tId).getType());
            inst.getResult(oId).replaceAllUsesWith(inst.getResult(tId));
          }
        }
      }
    }

    igraph::InstanceRecord *onlyInst = nullptr;
    for (auto *use : node->uses()) {
      auto inst = dyn_cast_or_null<hw::InstanceOp>(use->getInstance().getOperation());
      if (inst == nullptr)
        continue;
      if (!onlyInst) {
        onlyInst = use;
      } else {
        onlyInst = nullptr;
        break;
      }
    }

    if (onlyInst) {
      auto inst = dyn_cast_or_null<hw::InstanceOp>(onlyInst->getInstance().getOperation());
      for (auto [tId, tVal] : llvm::enumerate(inst.getResults())) {
        if (ignorePorts.contains(hwModule.getPortIdForOutputId(tId)))
          continue;

        for (auto [oId, oVal] : llvm::enumerate(inst.getResults())) {
          if (tId == oId)
            continue;

          /* Never combine away a {keep}/{unused} port */
          if (ignorePorts.contains(hwModule.getPortIdForOutputId(oId)))
            continue;

          if (tVal == oVal) {
            combinableOuts.push_back(oId);
            ignorePorts.insert(hwModule.getPortIdForOutputId(oId));

            assert(inst.getResult(oId).getType() == inst.getResult(tId).getType());
            inst.getResult(oId).replaceAllUsesWith(inst.getResult(tId));
          }
        }
      }

      for (auto [tId, tVal] : llvm::enumerate(inst.getOperands())) {
        if (ignorePorts.contains(hwModule.getPortIdForInputId(tId)))
          continue;

        for (auto [oId, oVal] : llvm::enumerate(inst.getOperands())) {
          if (tId == oId)
            continue;

          /* Never combine away a {keep}/{unused} port */
          if (ignorePorts.contains(hwModule.getPortIdForInputId(oId)))
            continue;

          if (tVal == oVal) {
            combinableIns.push_back(oId);
            ignorePorts.insert(hwModule.getPortIdForInputId(oId));

            assert(inst.getOperand(oId).getType() == inst.getOperand(tId).getType());

            assert(body->getArgument(tId).getType() == body->getArgument(oId).getType());
            body->getArgument(oId).replaceAllUsesWith(body->getArgument(tId));
            inst.setOperand(tId, inst.getOperand(oId));
          }
        }
      }
    }

    size_t rewired_ports = combinableIns.size() + combinableOuts.size();
    if (rewired_ports == 0)
      return false;
    no_rewired += rewired_ports;

    for (auto mIn : combinableIns)
      LLVM_DEBUG(llvm::dbgs() << "\t- Found combinable input@" << mIn << ": " << hwModule.getInputName(mIn) << "\n");
    for (auto mOut : combinableOuts)
      LLVM_DEBUG(llvm::dbgs() << "\t- Found combinable output@" << mOut << ": " << hwModule.getOutputName(mOut)
                              << "\n");

    updateNode(builder, node, combinableIns, combinableOuts);

    return true;
  }

  void collectDependencies(mlir::Value val, llvm::SmallSetVector<mlir::Operation *, 16> &ops,
                           llvm::SmallVector<mlir::BlockArgument> &ports) {
    if (auto port = dyn_cast<mlir::BlockArgument>(val)) {
      ports.push_back(port);
    } else if (auto op = val.getDefiningOp()) {
      if (!ops.insert(op))
        return;
      for (mlir::Value oper : op->getOperands())
        collectDependencies(oper, ops, ports);
    } else {
      assert(false);
    }
  }

  void collectDependenciesInsts(hw::InstanceOp inst, mlir::Value val, llvm::SmallSetVector<mlir::Operation *, 16> &ops,
                                llvm::SmallVector<mlir::OpResult> &ports) {
    // BlockArguments are valid - they come from parent module ports
    if (auto arg = dyn_cast<mlir::BlockArgument>(val))
      return;

    auto op = val.getDefiningOp();
    assert(op);

    if (op == inst) {
      auto oRes = dyn_cast<mlir::OpResult>(val);
      assert(oRes);
      ports.push_back(oRes);
      return;
    }

    assert(isMoveableOp(op));

    if (!ops.insert(op))
      return;

    for (mlir::Value oper : op->getOperands())
      collectDependenciesInsts(inst, oper, ops, ports);
  }

  bool optInterface(OpBuilder &builder, igraph::InstanceGraphNode *node) {
    auto hwModule = dyn_cast<hw::HWModuleOp>(node->getModule().getOperation());
    if (!hwModule)
      return false;
    LLVM_DEBUG(llvm::dbgs() << "=> Opt: " << hwModule.getModuleName() << "\n");

    tryConstFold(hwModule, builder);
    no_del_ops += eraseUnused(hwModule, instGraph);

    bool changed = false;
    changed |= removeUnusedPorts(builder, node);
    changed |= rewireModule(builder, node);
    changed |= combinePorts(builder, node);

    if (!changed)
      return false;

    LLVM_DEBUG(llvm::dbgs() << "=> Changed: " << hwModule.getModuleName() << "\n");

    processedModules.insert(hwModule);

    tryConstFold(hwModule, builder);
    no_del_ops += eraseUnused(hwModule, instGraph);

    for (auto use : llvm::make_early_inc_range(node->uses())) {
      auto inst = dyn_cast_or_null<hw::InstanceOp>(use->getInstance().getOperation());
      if (!inst)
        continue;
      assert(mlir::succeeded(mlir::verify(inst)));
    }
    assert(mlir::succeeded(mlir::verify(hwModule)));

    return true;
  }

  void optInterfaces(OpBuilder &builder) {
    bool changed;
    do {
      changed = false;
      for (auto *node : llvm::make_early_inc_range(*instGraph)) {
        if (optInterface(builder, node))
          changed = true;
      }
    } while (changed);
  }

  void cleanup() {
    bool found;
    do {
      found = false;
      for (auto *node : llvm::make_early_inc_range(*instGraph)) {
        if (node->noUses()) {
          auto hwModule = node->getModule<hw::HWModuleLike>();
          LLVM_DEBUG(llvm::dbgs() << "Deleting unused module " << hwModule.getModuleName() << "\n");
          processedModules.insert(hwModule);

          /* Delete all hier ops as well*/
          SmallVector<hw::HierPathOp, 8> toErase;
          for (auto hierPathOp : getOperation().getOps<hw::HierPathOp>()) {
            for (auto element : hierPathOp.getNamepath()) {
              auto inner = dyn_cast<hw::InnerRefAttr>(element);
              if (!inner)
                continue;

              auto targetMod = inner.getModule();
              if (targetMod == hwModule.getNameAttr()) {
                toErase.push_back(hierPathOp);
                break;
              }
            }
          }

          for (auto hierOp : toErase) {
            assert(hierOp.use_empty());
            hierOp.erase();
          }

          instGraph->erase(node);
          hwModule->erase();

          ++no_del_modules;
          found = true;
        }
      }
    } while (found);
  }

  void runOnOperation() final {
    OpBuilder builder(getOperation().getContext());
    hw::InstanceGraph &instGraphRef = getAnalysis<hw::InstanceGraph>();
    instGraph = &instGraphRef;

    optInterfaces(builder);

    cleanup();
    no_modules = processedModules.size();
    processedModules.clear();
  }
};

} // namespace
} // namespace circt::cosimGen
