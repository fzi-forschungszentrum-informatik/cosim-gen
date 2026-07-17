//===----------------------------------------------------------------------===//
//
// Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#include "circt/Dialect/HW/HWInstanceGraph.h"
#include "circt/Dialect/HW/HWOps.h"
#include "circt/Dialect/SV/SVOps.h"
#include "circt/Dialect/Seq/SeqOps.h"
#include "mlir/Pass/Pass.h"

#include "common/PathComp.h"
#include "cosimGen/HWOpt.h"

#include "llvm/Support/Debug.h"
#define DEBUG_TYPE "hw-taint"

#include "cosimGen/Passes.h"

namespace circt::cosimGen {
#define GEN_PASS_DEF_HWTAINT
#include "cosimGen/Passes.h.inc"

namespace {

struct HWModuleIOTaint {
  llvm::SetVector<unsigned> input;
  llvm::SetVector<unsigned> output;
};
struct HWModuleTaint;
typedef std::shared_ptr<struct HWModuleTaint> HWTaintPtr;

struct HWModuleTaint {
  igraph::InstancePath path;
  igraph::InstanceRecord *instRec;
  // hw::HWModuleLike hwModule;
  struct HWModuleIOTaint taggedIO;
  struct HWModuleIOTaint unprocessedIO;
  HWTaintPtr parent;
  llvm::MapVector<hw::HWInstanceLike, HWTaintPtr> insts;
  bool keep;

  bool tagInput(unsigned i) {
    bool insert = taggedIO.input.insert(i);
    if (insert) {
      unprocessedIO.input.insert(i);
      LLVM_DEBUG(llvm::dbgs() << "\t" << getModule().getModuleName() << " tag input@" << i << ": "
                              << getModule().getInputName(i) << "\n");
    }
    return insert;
  }

  bool tagOutput(unsigned i) {
    bool insert = taggedIO.output.insert(i);
    if (insert) {
      unprocessedIO.output.insert(i);
      LLVM_DEBUG(llvm::dbgs() << "\t" << getModule().getModuleName() << " tag ouput@" << i << ": "
                              << getModule().getOutputName(i) << "\n");
    }
    return insert;
  }

  void clearUnprocessed() {
    unprocessedIO.input.clear();
    unprocessedIO.output.clear();
  }

  hw::HWModuleLike getModule() { return instRec->getTarget()->getModule<hw::HWModuleLike>(); }

  bool unprocessed() { return !keep && (!unprocessedIO.input.empty() || !unprocessedIO.output.empty()); }
};

struct HWTaintPass : impl::HWTaintBase<HWTaintPass> {
private:
  llvm::DenseSet<mlir::Operation *> deleteOp;
  llvm::DenseSet<mlir::Operation *> deletedOp;
  llvm::MapVector<igraph::InstancePath, HWTaintPtr> taggedInstances;
  llvm::MapVector<igraph::InstanceGraphNode *, llvm::SmallVector<HWTaintPtr>> taggedModules;
  // std::vector<struct HWModuleTaint> taggedModule;

public:
  using impl::HWTaintBase<HWTaintPass>::HWTaintBase;

  bool isPart(igraph::InstancePath &searchPath, igraph::InstancePath &instPath) {
    return pathCompare(searchPath, instPath) >= 0;
  }

  void tagAllIO(HWTaintPtr modT) {
    auto hwModule = modT->getModule();
    circt::hw::ModulePortInfo instPorts(hwModule.getPortList());
    for (auto [i, port] : llvm::enumerate(instPorts.getInputs())) {
      modT->tagInput(i);
    }
    for (auto [i, port] : llvm::enumerate(instPorts.getOutputs())) {
      modT->tagOutput(i);
    }

    hwModule.walk([&](Operation *op) {
      if (op->getNumResults() >= 1 && !op->getAttr(TAINTED)) {
        tainted_ops++;
        op->setAttr(TAINTED, BoolAttr::get(op->getContext(), true));
      }
    });
  }

  void initTaggedModule(igraph::InstancePathCache &instancePathCache, igraph::InstancePath &searchPath) {
    for (auto *node : instancePathCache.instanceGraph) {
      auto &instanceList = taggedModules[node];
      auto hwModule = node->getModule<hw::HWModuleLike>();

      for (auto path : instancePathCache.getAbsolutePaths(hwModule)) {
        igraph::InstanceRecord *instRec;
        auto opInst = path.empty() ? nullptr : path.leaf();
        bool found = false;
        for (auto *rec : node->uses()) {
          if (rec->getInstance() == opInst) {
            instRec = rec;
            found = true;
            break;
          }
        }
        assert(found);

        auto tgm = std::make_shared<HWModuleTaint>(
            HWModuleTaint{.path = path,
                          .instRec = instRec,
                          .taggedIO = {llvm::SetVector<unsigned>(), llvm::SetVector<unsigned>()},
                          .unprocessedIO = {llvm::SetVector<unsigned>(), llvm::SetVector<unsigned>()},
                          .parent = nullptr,
                          .insts = llvm::MapVector<hw::HWInstanceLike, HWTaintPtr>(),
                          .keep = isPart(searchPath, path)});
        taggedInstances[path] = tgm;

        if (tgm->keep) {
          LLVM_DEBUG(llvm::dbgs() << "Keep: " << tgm->path << "\n");
          tagAllIO(tgm);
          tgm->clearUnprocessed();
        }
        instanceList.push_back(tgm);
      }
    }

    for (auto *node : instancePathCache.instanceGraph) {
      auto hwModule = node->getModule<hw::HWModuleLike>();
      for (auto path : instancePathCache.getAbsolutePaths(hwModule)) {
        auto &tgm = taggedInstances[path];
        if (!path.empty()) {
          tgm->parent = taggedInstances[path.dropBack()];
        }

        for (auto *rec : *node) {
          auto instMod = rec->getTarget();
          if (instMod == nullptr)
            continue;

          for (auto instPath : instancePathCache.getAbsolutePaths(instMod->getModule())) {
            if (instPath.empty()) {
              continue;
            }
            if (instPath.dropBack() == path) {
              tgm->insts[rec->getInstance<hw::HWInstanceLike>()] = taggedInstances[instPath];
              break;
            }
          }
        }
      }
    }
  }

  void taintDrivers(HWTaintPtr modT, bool allTaged) {
    llvm::SmallVector<mlir::Value> drvs;
    llvm::SmallVector<mlir::Value> outputs;
    auto mod = modT->getModule();
    auto *body = mod.getBodyBlock();

    for (auto i : modT->unprocessedIO.input) {
      auto val = body->getArgument(i);
      drvs.push_back(val);
    }
    modT->unprocessedIO.input.clear();

    for (auto &[inst, instT] : modT->insts) {
      struct HWModuleIOTaint &ports = allTaged ? instT->taggedIO : instT->unprocessedIO;
      for (auto i : ports.output) {
        auto val = inst->getResult(i);
        outputs.push_back(val);
      }
    }

    llvm::DenseSet<Value> vistedVals;
    while (!drvs.empty()) {
      auto val = drvs.pop_back_val();
      if (!vistedVals.insert(val).second) {
        continue;
      }

      if (auto blockArg = llvm::dyn_cast<mlir::BlockArgument>(val)) {
        modT->tagInput(blockArg.getArgNumber());
      } else {
        auto defOp = val.getDefiningOp();
        assert(defOp);
        defOp->setAttr(TAINTED, BoolAttr::get(defOp->getContext(), true));
        for (auto res : defOp->getOperands()) {
          drvs.push_back(res);
        }
      }
    }

    while (!outputs.empty()) {
      auto val = outputs.pop_back_val();
      if (!vistedVals.insert(val).second) {
        continue;
      }

      for (mlir::OpOperand &opOperand : val.getUses()) {
        mlir::Operation *useOp = opOperand.getOwner();
        assert(useOp != nullptr);

        useOp->setAttr(TAINTED, BoolAttr::get(useOp->getContext(), true));

        if (auto inst = dyn_cast<hw::HWInstanceLike>(useOp)) {
          auto &instT = modT->insts[inst];
          instT->tagInput(opOperand.getOperandNumber());
        } else if (auto outop = dyn_cast<hw::OutputOp>(useOp)) {
          modT->tagOutput(opOperand.getOperandNumber());
        } else {
          for (auto res : useOp->getResults()) {
            outputs.push_back(res);
          }
        }
      }
    }
  }

  void taintSinks(HWTaintPtr modT, bool allTaged) {
    llvm::SmallVector<mlir::Value> sinks;
    auto mod = modT->getModule();
    auto *body = mod.getBodyBlock();
    hw::OutputOp outputOp = cast<hw::OutputOp>(body->getTerminator());

    for (auto i : modT->unprocessedIO.output) {
      auto val = outputOp.getOperand(i);
      // llvm::errs() << "\t\tTAINT SINK " << val2Str(val, mod) << " for " << mod.getOutputName(i) << "\n";
      sinks.push_back(val);
    }
    modT->unprocessedIO.output.clear();

    for (auto &[inst, instT] : modT->insts) {
      struct HWModuleIOTaint &ports = allTaged ? instT->taggedIO : instT->unprocessedIO;

      for (auto i : ports.input) {
        auto val = inst->getOperand(i);
        sinks.push_back(val);
      }
    }

    llvm::DenseSet<Value> vistedSinks;

    while (!sinks.empty()) {
      auto val = sinks.pop_back_val();
      if (!vistedSinks.insert(val).second) {
        continue;
      }

      if (auto blockArg = dyn_cast<BlockArgument>(val)) {
        modT->tagInput(blockArg.getArgNumber());
      } else if (auto result = dyn_cast<mlir::OpResult>(val)) {
        auto defOp = result.getOwner();
        assert(defOp != nullptr);

        defOp->setAttr(TAINTED, BoolAttr::get(defOp->getContext(), true));
        if (auto inst = dyn_cast<hw::HWInstanceLike>(defOp)) {
          auto &instT = modT->insts[inst];
          instT->tagOutput(result.getResultNumber());
        } else {
          for (auto in : defOp->getOperands()) {
            sinks.push_back(in);
          }
        }
      } else {
        assert(false);
      }
    }
  }

  void taintModule(hw::InstanceGraph &instGraph, HWTaintPtr modT) {
    auto hwModule = modT->getModule();
    LLVM_DEBUG(llvm::dbgs() << "\nTaint module " << hwModule.getModuleName() << "\n");
    bool propToParents;

    if (isa<hw::HWModuleOp>(hwModule)) {
      // /* Initial taint from module & insts IOs */
      taintDrivers(modT, true);
      modT->unprocessedIO.input.clear();
      taintSinks(modT, true);

      /* Prop changes back to parents if module got new IO from insts */
      propToParents = modT->unprocessed();

      while (modT->unprocessed()) {
        taintDrivers(modT, false);
        modT->unprocessedIO.input.clear();
        taintSinks(modT, false);
      }
    } else {
      LLVM_DEBUG(llvm::dbgs() << "\tOther module type => accept all\n");
      tagAllIO(modT);
      propToParents = modT->unprocessed();
      modT->clearUnprocessed();
    }

    /* Propagate to child modules */
    for (auto [nextInst, nextInstT] : modT->insts)
      if (nextInstT->unprocessed())
        taintModule(instGraph, nextInstT);

    /* Propagate to parent modules if module changed */
    if (propToParents && modT->parent != nullptr) {
      taintModule(instGraph, modT->parent);
    }

    assert(!modT->unprocessed());

    LLVM_DEBUG(llvm::dbgs() << "Return taint module " << hwModule.getModuleName() << "\n");
  }

  void runOnOperation() final {
    hw::InstanceGraph &instGraph = getAnalysis<hw::InstanceGraph>();
    igraph::InstancePathCache instancePathCache(instGraph);
    ModuleOp circuit = getOperation();
    OpBuilder opBuilder(circuit.getContext());
    auto searchPathResult = strPath2circtPath(instancePathCache, path);
    if (!searchPathResult) {
      llvm::errs() << "Error: " << llvm::toString(searchPathResult.takeError()) << "\n";
      signalPassFailure();
      return;
    }
    auto &searchPath = *searchPathResult;

    initTaggedModule(instancePathCache, searchPath);
    assert(taggedInstances.contains(searchPath));
    auto taintMod = taggedInstances[searchPath];

    auto taintParent = taintMod->parent;

    if (taintParent == nullptr) {
      llvm::errs()
          << "Path must have a parent module - root path '/' not supported. Use a path like '/module/instance'";
      signalPassFailure();
      return;
    }

    LLVM_DEBUG(llvm::dbgs() << "\n\n");
    LLVM_DEBUG(llvm::dbgs() << "=========HW TAINT===========\n");
    LLVM_DEBUG(llvm::dbgs() << "Path: " << searchPath << "\n");
    LLVM_DEBUG(llvm::dbgs() << "Parent: " << taintParent->getModule().getModuleName() << "\n");
    LLVM_DEBUG(llvm::dbgs() << "=============================\n");
    LLVM_DEBUG(llvm::dbgs() << "\n\n");

    taintModule(instGraph, taintParent);

    OpBuilder builder(getOperation().getContext());
    for (auto *node : instGraph) {
      removeUntaintedPorts(builder, instGraph, node);
    }

    circuit.walk([&](Operation *op) {
      if (op->getNumResults() >= 1 && !op->getAttr(TAINTED)) {
        untainted_ops++;
        op->setAttr(TAINTED, BoolAttr::get(op->getContext(), false));
      }
    });
  }

  void removeUntaintedPorts(OpBuilder &builder, hw::InstanceGraph &instGraph, igraph::InstanceGraphNode *node) {
    llvm::DenseSet<unsigned int> keepInputs, keepOutputs;
    SmallVector<unsigned int> earseInputs, earseOutputs;
    auto hwModule = node->getModule<hw::HWModuleLike>();
    auto mod = dyn_cast_or_null<hw::HWModuleOp>(hwModule.getOperation());
    if (mod == nullptr)
      return;
    auto *body = hwModule.getBodyBlock();
    if (body == nullptr)
      return;
    hw::OutputOp outputOp = cast<hw::OutputOp>(body->getTerminator());

    for (auto modT : taggedModules[node]) {
      assert(!modT->unprocessed());

      if (modT->keep)
        return;

      for (auto in : modT->taggedIO.input)
        keepInputs.insert(in);

      for (auto out : modT->taggedIO.output)
        keepOutputs.insert(out);
    }

    for (auto &arg : body->getArguments()) {
      auto id = arg.getArgNumber();
      if (!keepInputs.contains(id)) {
        earseInputs.push_back(id);
        ++untainted_inputs;
        LLVM_DEBUG(llvm::dbgs() << "Untainted input " << mod.getModuleName() << "@" << id << " " << mod.getInputName(id)
                                << "\n");
      }
    }

    for (auto &opoperand : outputOp->getOpOperands()) {
      auto id = opoperand.getOperandNumber();
      if (!keepOutputs.contains(id)) {
        earseOutputs.push_back(id);
        ++untainted_outputs;
        LLVM_DEBUG(llvm::dbgs() << "Remove untainted output " << mod.getModuleName() << "@" << id << " "
                                << mod.getOutputName(id) << "\n");
      }
    }

    llvm::sort(earseInputs);
    llvm::sort(earseOutputs);

    if (true) { // Remove ports
      mod.modifyPorts({}, {}, earseInputs, earseOutputs);

      for (auto id : llvm::reverse(earseInputs)) {
        auto blockArg = body->getArgument(id);
        replaceValueWithDummy(builder, blockArg);
        body->eraseArgument(id);
      }

      for (auto id : llvm::reverse(earseOutputs))
        outputOp->eraseOperand(id);

      for (auto use : llvm::make_early_inc_range(node->uses())) {
        auto inst = use->getInstance<hw::InstanceOp>();
        if (inst == nullptr)
          continue;

        SmallVector<mlir::Value> newInstInputs;
        for (auto &input : inst->getOpOperands()) {
          if (!llvm::is_contained(earseInputs, input.getOperandNumber())) {
            newInstInputs.push_back(input.get());
          }
        };

        builder.setInsertionPoint(inst);
        hw::InstanceOp newInst =
            hw::InstanceOp::create(builder, inst.getLoc(), hwModule, inst.getInstanceName(), newInstInputs);
        unsigned newPortId = 0;
        for (auto [i, output] : llvm::enumerate(inst->getResults())) {
          if (!llvm::is_contained(earseOutputs, i)) {
            output.replaceAllUsesWith(newInst.getResult(newPortId++));
          } else {
            replaceValueWithDummy(builder, output);
          }
        }

        assert(inst->use_empty());
        // ToDo: We might need to copy more attributes...
        newInst.setInnerSymAttr(inst.getInnerSymAttr());
        if (inst->getAttr(TAINTED))
          newInst->setAttr(TAINTED, inst->getAttr(TAINTED));
        instGraph.replaceInstance(inst, newInst);
        inst->erase();
      }
    } else {
      for (auto id : earseInputs) {
        auto blockArg = body->getArgument(id);
        replaceValueWithDummy(builder, blockArg);
      }

      for (auto id : earseOutputs) {
        replaceOperandWithDummy(builder, outputOp, id);
      }
    }
  }
};

} // namespace
} // namespace circt::cosimGen
