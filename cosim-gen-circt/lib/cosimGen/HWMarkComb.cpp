//===----------------------------------------------------------------------===//
//
// Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#include "circt/Dialect/Comb/CombDialect.h"
#include "mlir/Pass/Pass.h"
#include "llvm/Support/Regex.h"

#include "common/PathComp.h"
#include "cosimGen/HWOpt.h"
#include "cosimGen/PortTagging.h"

#include "llvm/Support/Debug.h"
#define DEBUG_TYPE "hw-markcomb"

#include "cosimGen/Passes.h"

namespace circt::cosimGen {
#define GEN_PASS_DEF_HWMARKCOMB
#include "cosimGen/Passes.h.inc"

namespace {

struct HWModuleIOMarkComb {
  llvm::SetVector<unsigned> input;
  llvm::SetVector<unsigned> output;
};

struct HWModuleMarkComb;
typedef std::shared_ptr<struct HWModuleMarkComb> HWMarkCombPtr;

struct HWModuleMarkComb {
  igraph::InstancePath path;
  igraph::InstanceRecord *instRec;
  struct HWModuleIOMarkComb taggedIO;
  struct HWModuleIOMarkComb unprocessedIO;
  HWMarkCombPtr parent;
  llvm::MapVector<hw::HWInstanceLike, HWMarkCombPtr> insts;

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
  hw::HWInstanceLike getInstance() { return instRec->getInstance<hw::HWInstanceLike>(); }

  bool unprocessed() { return (!unprocessedIO.input.empty() || !unprocessedIO.output.empty()); }
};

struct HWMarkCombPass : impl::HWMarkCombBase<HWMarkCombPass> {
private:
  llvm::MapVector<igraph::InstancePath, HWMarkCombPtr> taggedInstances;
  llvm::MapVector<igraph::InstanceGraphNode *, llvm::SmallVector<HWMarkCombPtr>> taggedModules;

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

        auto tgm = std::make_shared<HWModuleMarkComb>(
            HWModuleMarkComb{.path = path,
                             .instRec = instRec,
                             .taggedIO = {llvm::SetVector<unsigned>(), llvm::SetVector<unsigned>()},
                             .unprocessedIO = {llvm::SetVector<unsigned>(), llvm::SetVector<unsigned>()},
                             .parent = nullptr,
                             .insts = llvm::MapVector<hw::HWInstanceLike, HWMarkCombPtr>()});
        taggedInstances[path] = tgm;
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

  inline void mark(mlir::Operation *op) {
    assert(op);
    op->setAttr(GRAPH_HIDE, BoolAttr::get(op->getContext(), false));
  }

  void tagAllOutputs(HWMarkCombPtr modT) {
    auto hwModule = modT->getModule();
    circt::hw::ModulePortInfo instPorts(hwModule.getPortList());
    // for (auto [i, port] : llvm::enumerate(instPorts.getInputs())) {
    //   modT->tagInput(i);
    // }
    for (auto [i, port] : llvm::enumerate(instPorts.getOutputs())) {
      modT->tagOutput(i);
    }
  }

  void markFirst(HWMarkCombPtr modT) {
    mark(modT->getInstance());

    if (!strRegex.hasValue()) {
      tagAllOutputs(modT);
      return;
    }

    llvm::Regex regex = llvm::Regex(strRegex);
    SmallVector<unsigned> portIds;

    for (auto port : modT->getModule().getPortList()) {
      if (regex.match(port.getName())) {
        LLVM_DEBUG(llvm::dbgs() << "\t - Add:    " << port.getName() << "\n");
        if (port.isInput()) {
          modT->tagInput(port.argNum);
        } else if (port.isOutput()) {
          modT->tagOutput(port.argNum);
        } else {
          assert(false);
        }
      } else {
        LLVM_DEBUG(llvm::dbgs() << "\t - Ignore: " << port.getName() << "\n");
      }
    }
  }

  void markCombBackwards(HWMarkCombPtr modT) {
    llvm::DenseSet<Value> vistedVals;
    llvm::SmallVector<mlir::Value> backProp;

    auto mod = modT->getModule();
    auto *body = mod.getBodyBlock();
    auto outOp = cast<hw::OutputOp>(body->getTerminator());

    for (auto i : modT->unprocessedIO.output) {
      mark(outOp);
      auto val = outOp->getOperand(i);
      // llvm::errs() << "\t\tMARKCOMB OUT " << val2Str(val, mod) << " for " << mod.getOutputName(i) << "\n";
      backProp.push_back(val);
    }
    modT->unprocessedIO.output.clear();

    for (auto &[inst, instT] : modT->insts) {
      struct HWModuleIOMarkComb &ports = instT->taggedIO;

      for (auto i : ports.input) {
        auto val = inst->getOperand(i);
        // llvm::errs() << "\t\tMARKCOMB INST IN " << val2Str(val, mod) << " from " <<
        // instT->getModule().getModuleName()
        //              << " " << instT->getModule().getInputName(i) << "\n";
        backProp.push_back(val);
      }
    }

    while (!backProp.empty()) {
      auto val = backProp.pop_back_val();
      if (!vistedVals.insert(val).second) {
        continue;
      }

      /* follow srcs */
      if (auto blockArg = llvm::dyn_cast<mlir::BlockArgument>(val)) {
        modT->tagInput(blockArg.getArgNumber());
      } else if (auto result = dyn_cast<mlir::OpResult>(val)) {
        auto defOp = result.getOwner();
        mark(defOp);
        if (auto inst = dyn_cast<hw::HWInstanceLike>(defOp)) {
          auto &instT = modT->insts[inst];
          instT->tagOutput(result.getResultNumber());
        } else {
          if (isa<comb::CombDialect>(defOp->getDialect()) || isa<hw::WireOp>(defOp)) {
            for (auto in : defOp->getOperands()) {
              // llvm::errs() << "\t\tFOLLOW SRC " << val2Str(in, mod) << "\n";
              backProp.push_back(in);
            }
          }
        }
      } else {
        assert(false);
      }
    }
  }
  void markCombForwards(HWMarkCombPtr modT) {
    llvm::DenseSet<Value> vistedVals;
    llvm::SmallVector<mlir::Value> forwardProp;
    auto mod = modT->getModule();
    auto *body = mod.getBodyBlock();

    for (auto i : modT->unprocessedIO.input) {
      auto val = body->getArgument(i);
      // llvm::errs() << "\t\tMARKCOMB IN " << val2Str(val, mod) << " for " << mod.getInputName(i) << "\n";
      forwardProp.push_back(val);
    }
    modT->unprocessedIO.input.clear();
    for (auto &[inst, instT] : modT->insts) {
      struct HWModuleIOMarkComb &ports = instT->taggedIO;
      for (auto i : ports.output) {
        auto val = inst->getResult(i);
        // llvm::errs() << "\t\tMARKCOMB INST OUT " << val2Str(val, mod) << " from " <<
        // instT->getModule().getModuleName()
        //              << " " << instT->getModule().getOutputName(i) << "\n";
        forwardProp.push_back(val);
      }
    }

    while (!forwardProp.empty()) {
      auto val = forwardProp.pop_back_val();
      if (!vistedVals.insert(val).second) {
        continue;
      }

      /* follow dsts */
      for (auto &opOp : val.getUses()) {
        auto useOp = opOp.getOwner();
        mark(useOp);
        if (auto inst = dyn_cast<hw::HWInstanceLike>(useOp)) {
          auto &instT = modT->insts[inst];
          instT->tagInput(opOp.getOperandNumber());
        } else if (auto outop = dyn_cast<hw::OutputOp>(useOp)) {
          modT->tagOutput(opOp.getOperandNumber());
        } else if (isa<comb::CombDialect>(useOp->getDialect()) || isa<hw::WireOp>(useOp)) {
          for (auto res : useOp->getResults()) {
            // llvm::errs() << "\t\tFOLLOW DRIVER " << val2Str(res, mod) << "\n";
            forwardProp.push_back(res);
          }
        }
      }
    }
  }

  void forwardModule(hw::InstanceGraph &instGraph, HWMarkCombPtr modT) {
    auto hwModule = modT->getModule();
    LLVM_DEBUG(llvm::dbgs() << "\nProcess forward " << hwModule.getModuleName() << "\n");

    if (isa<hw::HWModuleOp>(hwModule)) {
      markCombForwards(modT);
    } else {
      LLVM_DEBUG(llvm::dbgs() << "\tExternal module => accept outputs\n");
      tagAllOutputs(modT);
      modT->clearUnprocessed();
    }

    /* Propagate to child modules */
    for (auto [nextInst, nextInstT] : modT->insts)
      if (nextInstT->unprocessedIO.input.size())
        forwardModule(instGraph, nextInstT);

    /* Propagate to parent modules */
    if (modT->parent)
      forwardModule(instGraph, modT->parent);

    assert(!modT->unprocessedIO.input.size());

    LLVM_DEBUG(llvm::dbgs() << "Return forward module " << hwModule.getModuleName() << "\n");
  }

  void backwardModule(hw::InstanceGraph &instGraph, HWMarkCombPtr modT) {
    auto hwModule = modT->getModule();
    LLVM_DEBUG(llvm::dbgs() << "\nProcess backward " << hwModule.getModuleName() << "\n");

    if (isa<hw::HWModuleOp>(hwModule)) {
      markCombBackwards(modT);
    } else {
      LLVM_DEBUG(llvm::dbgs() << "\tExternal module => accept outputs\n");
      tagAllOutputs(modT);
      modT->clearUnprocessed();
    }

    /* Propagate to child modules */
    for (auto [nextInst, nextInstT] : modT->insts)
      if (nextInstT->unprocessedIO.output.size())
        backwardModule(instGraph, nextInstT);

    /* Propagate to parent modules */
    if (modT->parent)
      backwardModule(instGraph, modT->parent);

    assert(!modT->unprocessedIO.output.size());

    LLVM_DEBUG(llvm::dbgs() << "Return backward module " << hwModule.getModuleName() << "\n");
  }

  void markUntaggedHidden() {
    getOperation().walk([&](Operation *op) {
      if (op == getOperation())
        return;

      if (!op->getAttr(GRAPH_HIDE)) {
        unmarkcombed_ops++;
        op->setAttr(GRAPH_HIDE, BoolAttr::get(op->getContext(), true));
      } else {
        mark(op);
      }
    });

    for (auto &[node, modTs] : taggedModules) {
      llvm::SetVector<unsigned int> inputs, outputs;
      for (auto modT : modTs) {
        inputs.insert(modT->taggedIO.input.begin(), modT->taggedIO.input.end());
        outputs.insert(modT->taggedIO.output.begin(), modT->taggedIO.output.end());
      }

      auto mod = node->getModule<hw::HWModuleLike>();
      unsigned numInputs = mod.getNumInputPorts();
      unsigned numOutputs = mod.getNumOutputPorts();
      llvm::SmallVector<unsigned> untaggedPort;
      for (unsigned i = 0; i < numInputs; ++i) {
        if (!inputs.contains(i))
          untaggedPort.push_back(mod.getPortIdForInputId(i));
      }
      for (unsigned i = 0; i < numOutputs; ++i) {
        if (!outputs.contains(i))
          untaggedPort.push_back(mod.getPortIdForOutputId(i));
      }

      tagPorts(mod, untaggedPort, GRAPH_HIDE);
    }
  }

public:
  using impl::HWMarkCombBase<HWMarkCombPass>::HWMarkCombBase;

  void runOnOperation() final {
    taggedInstances.clear();
    taggedModules.clear();

    hw::InstanceGraph &instGraph = getAnalysis<hw::InstanceGraph>();
    igraph::InstancePathCache instancePathCache(instGraph);
    auto searchPathResult = strPath2circtPath(instancePathCache, path);
    if (!searchPathResult) {
      llvm::errs() << "Error: " << llvm::toString(searchPathResult.takeError()) << "\n";
      signalPassFailure();
      return;
    }
    auto &searchPath = *searchPathResult;

    initTaggedModule(instancePathCache, searchPath);
    assert(taggedInstances.contains(searchPath));
    auto markcombMod = taggedInstances[searchPath];
    auto markcombParent = markcombMod->parent;
    if (!markcombParent) {
      llvm::errs()
          << "Path must have a parent module - root path '/' not supported. Use a path like '/module/instance'";
      signalPassFailure();
      return;
    }

    LLVM_DEBUG(llvm::dbgs() << "\n\n");
    LLVM_DEBUG(llvm::dbgs() << "=========HW MARKCOMB===========\n");
    LLVM_DEBUG(llvm::dbgs() << "Path: " << searchPath << "\n");
    LLVM_DEBUG(llvm::dbgs() << "Parent: " << markcombParent->getModule().getModuleName() << "\n");
    LLVM_DEBUG(llvm::dbgs() << "=============================\n");
    LLVM_DEBUG(llvm::dbgs() << "\n\n");

    markFirst(markcombMod);
    forwardModule(instGraph, markcombParent);
    backwardModule(instGraph, markcombParent);
    markUntaggedHidden();
  }
};

} // namespace
} // namespace circt::cosimGen
