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
#include "cosimGen/PortTagging.h"

#include "llvm/Support/Debug.h"
#include "llvm/Support/Regex.h"
#define DEBUG_TYPE "hw-prop-ports-to-tlm"

#include "cosimGen/Passes.h"

namespace circt::cosimGen {
#define GEN_PASS_DEF_HWPROPPORTS2TLM
#include "cosimGen/Passes.h.inc"

namespace {

using PropPorts = circt::hw::ModulePortInfo;

struct HWPropPorts2TLMPass : impl::HWPropPorts2TLMBase<HWPropPorts2TLMPass> {
private:
  OpBuilder *opBuilder;
  llvm::Regex *portRegex;
  llvm::SetVector<hw::HWModuleLike> vistedModules;
  llvm::SetVector<hw::HWInstanceLike> vistedInsts;

  llvm::MapVector<hw::HWModuleLike, llvm::SetVector<hw::HWModuleOp>> moduleParents;

  void tagPropPorts(hw::HWModuleLike mod, PropPorts &ports) {
    SmallVector<unsigned int> portsIds;
    for (auto port : ports.getInputs()) {
      portsIds.push_back(mod.getPortIdForInputId(port.argNum));
    }
    for (auto port : ports.getOutputs()) {
      portsIds.push_back(mod.getPortIdForOutputId(port.argNum));
    }
    tagPorts(mod, portsIds, KEEP);
  }

  PropPorts getRelevantPorts(igraph::InstanceRecord *instRec) {
    hw::HWModuleLike mod = instRec->getTarget()->getModule<hw::HWModuleLike>();
    hw::InstanceOp inst = instRec->getInstance<hw::InstanceOp>();
    if (!inst) {
      LLVM_DEBUG(llvm::dbgs() << "Warning: No instance found in getRelevantPorts\n");
      return PropPorts(SmallVector<::circt::hw::PortInfo>());
    }

    auto parentNode = instRec->getParent();
    bool parentIsTop = true;
    for (auto *use : parentNode->uses()) {
      if (use->getInstance()) {
        parentIsTop = false;
        break;
      }
    }

    SmallVector<::circt::hw::PortInfo> ports;
    for (auto port : mod.getPortList()) {
      if (portRegex->match(port.getName())) {

        if (port.isInput()) {
          if (parentIsTop) {
            assert(port.argNum < inst->getNumOperands());
            if (auto blockArg = dyn_cast<mlir::BlockArgument>(inst->getOperand(port.argNum))) {
              LLVM_DEBUG(llvm::dbgs() << "\t - Skipping top input: " << port.getName() << "\n");
              continue;
            }
          }
          no_input++;
        } else if (port.isOutput()) {
          if (parentIsTop) {
            assert(port.argNum < inst->getNumResults());
            auto val = inst->getResult(port.argNum);
            bool skip = false;
            for (auto use : val.getUsers()) {
              if (auto output = dyn_cast<hw::OutputOp>(use)) {
                LLVM_DEBUG(llvm::dbgs() << "\t - Skipping top output: " << port.getName() << "\n");
                skip = true;
                break;
              }
            }
            if (skip)
              continue;
          }
          no_output++;
        } else {
          llvm::errs() << "Unknown direction of port " << port.getName() << "\n";
        }
        LLVM_DEBUG(llvm::dbgs() << "\t - Add:    " << port.getName() << "\n");
        ports.push_back(port);
      } else {
        LLVM_DEBUG(llvm::dbgs() << "\t - Ignore: " << port.getName() << "\n");
      }
    }

    return PropPorts(ports);
  }

  void rewireInst(hw::InstanceOp inst, PropPorts &propP, SmallVector<Value> &inputVals) {
    for (auto [i, port] : llvm::enumerate(propP.getInputs()))
      inst->setOperand(port.argNum, inputVals[i]);

    auto newOutputs = propP.getOutputs();
    for (auto val : inst->getOpResults()) {
      unsigned i = val.getResultNumber();
      bool contains = std::find_if(newOutputs.begin(), newOutputs.end(),
                                   [&i](const hw::PortInfo p) { return p.argNum == i; }) != newOutputs.end();

      if (replaceInstOuts && contains) {
        replaceValueWithDummy(*opBuilder, val);
      }
    }
  }

  hw::InstanceOp replaceInst(hw::InstanceOp inst, PropPorts &propP, SmallVector<Value> &inputVals,
                             hw::HWModuleLike newType) {
    for (auto input : inst.getInputs())
      inputVals.push_back(input);

    opBuilder->setInsertionPoint(inst);
    auto newInst = hw::InstanceOp::create(*opBuilder, inst.getLoc(), newType, inst.getInstanceName(), inputVals);
    newInst.setInnerSymAttr(inst.getInnerSymAttr());

    /* New outputs are in front of the old ones => offset the index of the old ones */
    unsigned outputOffset = std::distance(propP.getOutputs().begin(), propP.getOutputs().end());
    for (auto val : inst.getResults()) {
      auto uses = val.getUses();

      if (!uses.empty()) {
        unsigned argNumber = val.getResultNumber();
        mlir::Value replaceVal = newInst.getResult(outputOffset + argNumber);
        val.replaceAllUsesWith(replaceVal);
      }
    }

    inst.erase();
    return newInst;
  }

  std::string getNewPortName(circt::hw::InstanceOp fromInst, circt::hw::PortInfo port, bool hasParent) {
    std::string res;
    if (hasParent) {
      res = (fromInst.getInstanceName() + "." + port.getName()).str();
    } else {
      llvm::StringRef name = port.getName();
      size_t parts = name.count(".");
      if (parts > 2) {
        size_t pos = name.find_last_of('.');
        size_t snd = name.substr(0, pos).find_last_of('.');
        assert(pos != StringRef::npos && snd != StringRef::npos);
        res = name.substr(snd + 1);
      } else {
        res = name;
      }
    }
    return res;
  }

  void propPorts(hw::HWModuleLike target, hw::HWModuleOp parent, PropPorts propP, bool parentExtended = false) {
    LLVM_DEBUG(llvm::dbgs() << "//===-------------------------------------------===//\n"
                            << "Propagate ports from: " << target.getModuleName() << " insts in "
                            << parent.getModuleName() << " " << parent.getLoc() << "\n");

    vistedModules.insert(parent);
    auto parents = moduleParents[parent];
    bool hasParent = !parents.empty();

    SmallVector<hw::InstanceOp> insts;
    parent.walk([&](hw::InstanceOp pInst) {
      auto names = pInst.getReferencedModuleNamesAttr();
      assert(names.size() == 1);
      if (target.getModuleName() == cast<StringAttr>(names[0]).getValue()) {
        insts.push_back(pInst);
      }
    });

    SmallVector<::circt::hw::PortInfo> nextPorts;

    for (auto inst : insts) {
      LLVM_DEBUG(llvm::dbgs() << "\t\tReplace " << inst << "\n");
      vistedInsts.insert(inst);
      SmallVector<Value> inputVals;

      /* Extend inputs */
      for (auto [i, port] : llvm::enumerate(propP.getInputs())) {
        auto [name, val] = parent.insertInput(i, getNewPortName(inst, port, hasParent), port.type);
        LLVM_DEBUG(llvm::dbgs() << "\t\tAdded input: " << name << "\n");
        inputVals.push_back(val);
        nextPorts.push_back(parent.getPort(i));
      }
      unsigned parentOutputsOffset = parent.getNumInputPorts();

      hw::InstanceOp nextInst = inst;
      if (parentExtended) {
        LLVM_DEBUG(llvm::dbgs() << "\t\tReplaced");
        nextInst = replaceInst(inst, propP, inputVals, target);
      } else {
        LLVM_DEBUG(llvm::dbgs() << "\t\tRewired");
        rewireInst(inst, propP, inputVals);
      }
      LLVM_DEBUG(llvm::dbgs() << " inst: " << nextInst << "\n");

      /* Extend outputs */
      for (auto [i, port] : llvm::enumerate(propP.getOutputs())) {
        mlir::StringAttr nameAttr =
            mlir::StringAttr::get(nextInst.getContext(), getNewPortName(nextInst, port, hasParent));
        mlir::Value val = nextInst->getOpResult(port.argNum);
        parent.insertOutputs(i, {{nameAttr, val}});
        auto parentPort = parent.getPort(parentOutputsOffset + i);
        LLVM_DEBUG(llvm::dbgs() << "\t\tAdded output: \"" << parentPort.getName() << "\"\n");
        nextPorts.push_back(parentPort);
      }
    }

    LLVM_DEBUG(llvm::dbgs() << "\nResult:\n"
                            << parent << "\n//===-------------------------------------------===//\n\n");

    /* Goto parent */
    PropPorts nextPropPorts(nextPorts);
    tagPropPorts(parent, nextPropPorts);
    for (auto nextParent : moduleParents[parent]) {
      propPorts(parent, nextParent, nextPropPorts, true);
    }
  }

public:
  using impl::HWPropPorts2TLMBase<HWPropPorts2TLMPass>::HWPropPorts2TLMBase;

  void runOnOperation() final {
    hw::InstanceGraph &instGraph = getAnalysis<hw::InstanceGraph>();
    igraph::InstancePathCache instancePathCache(instGraph);
    OpBuilder opB(getOperation().getContext());
    opBuilder = &opB;

    llvm::Regex r = llvm::Regex(strRegex);
    portRegex = &r;

    auto searchPathResult = strPath2circtPath(instancePathCache, strPath);
    if (!searchPathResult) {
      // Path not found - this can happen if the module was already extracted by hw-subgraph
      // In this case, the target module is now the top-level module, so there's nothing to propagate
      // Just return silently - no error message needed
      LLVM_DEBUG(llvm::dbgs() << "Path " << strPath << " not found - module may already be top-level\n");
      // Consume the error to avoid LLVM's "unchecked Expected" assertion
      llvm::consumeError(searchPathResult.takeError());
      return;
    }
    auto &searchPath = *searchPathResult;
    auto *instRec = getInstanceRecord(instancePathCache, searchPath);

    // instRec can be null if the module is now top-level (no instance points to it)
    if (!instRec) {
      LLVM_DEBUG(llvm::dbgs() << "Instance record is null - module may already be top-level\n");
      return;
    }

    LLVM_DEBUG(llvm::dbgs() << "//===-------------------------------------------===//\nFind ports to propagate\n");
    auto ports = getRelevantPorts(instRec);
    LLVM_DEBUG(llvm::dbgs() << "//===-------------------------------------------===//\n\n");

    hw::HWModuleLike hwModule = instRec->getTarget()->getModule<hw::HWModuleLike>();

    // Protect the extraction target from later structural optimizations
    hwModule->setAttr(KEEP, BoolAttr::get(hwModule->getContext(), true));

    if (ports.size() == 0) {
      mlir::emitError(getOperation().getLoc())
          << "Couldn't find any matching port in " << hwModule.getModuleName() << "\n";
      signalPassFailure();
      return;
    }

    for (auto *node : instGraph) {
      for (auto *instRec : node->uses()) {
        if (!instRec->getInstance<hw::InstanceOp>()) /* Root node */
          continue;
        hw::HWModuleOp parent = instRec->getParent()->getModule<hw::HWModuleOp>();
        hw::HWModuleLike hwModule = instRec->getTarget()->getModule<hw::HWModuleLike>();
        if (!moduleParents.contains(hwModule))
          moduleParents.insert({hwModule, llvm::SetVector<hw::HWModuleOp>()});
        moduleParents[hwModule].insert(parent);
      }
    }

    tagPropPorts(hwModule, ports);
    for (auto parent : moduleParents[hwModule]) {
      propPorts(hwModule, parent, ports);
    }

    no_modules = vistedModules.size();
    no_insts = vistedInsts.size();
  };
};

} // namespace
} // namespace circt::cosimGen
