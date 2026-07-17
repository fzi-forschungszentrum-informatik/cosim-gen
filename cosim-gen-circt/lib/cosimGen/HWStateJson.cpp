//===----------------------------------------------------------------------===//
//
// Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#include "circt/Dialect/HW/HWInstanceGraph.h"
#include "circt/Dialect/HW/HWOps.h"
#include "circt/Dialect/Seq/SeqOps.h"
#include "mlir/Pass/Pass.h"
#include "llvm/Support/FileSystem.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/ToolOutputFile.h"

#include "llvm/Support/Debug.h"
#define DEBUG_TYPE "hw-state-json"

#include "cosimGen/Passes.h"

namespace circt::cosimGen {
#define GEN_PASS_DEF_HWSTATEJSON
#include "cosimGen/Passes.h.inc"

namespace {

struct HWStateJsonPass : impl::HWStateJsonBase<HWStateJsonPass> {
private:
  static bool serializeModuleToJson(llvm::raw_ostream &outputStream, llvm::SmallVector<hw::HWModuleLike> &mods) {
    bool ok = true;
    llvm::json::OStream json(outputStream, 2);
    json.array([&] {
      for (hw::HWModuleLike &mod : mods) {
        auto portInfo = mod.getPortList();
        json.object([&] {
          json.attribute("name", mod.getModuleName());
          json.attribute("numStateBytes", 0);
          json.attribute("initialFnSym", "");
          json.attribute("finalFnSym", "");
          uint64_t offset = 0;
          json.attributeArray("states", [&] {
            for (const auto &port : portInfo) {
              if (hw::hasHWInOutType(port.type)) {
                mod.emitError("hw-state-json: port '") << port.getName() << "' is an inout port, which isn't supported";
                ok = false;
                continue;
              }
              auto bitWidth = llvm::TypeSwitch<::mlir::Type, int64_t>(port.type)
                                  .Case<seq::ClockType>([](seq::ClockType t) { return 1; })
                                  .Default([](::mlir::Type t) { return hw::getBitWidth(t); });
              if (bitWidth < 0) {
                mod.emitError("hw-state-json: port '") << port.getName() << "' has an unknown/unsized type";
                ok = false;
                bitWidth = 0;
              }

              json.object([&] {
                json.attribute("name", port.getName());
                json.attribute("offset", offset);
                json.attribute("numBits", bitWidth);
                json.attribute("type", port.dir == hw::ModulePort::Direction::Input ? "input" : "output");
              });
              offset += bitWidth;
            }
          });
        });
      }
    });
    return ok;
  }

  static LogicalResult generateJson(std::string pathOpt, llvm::SmallVector<hw::HWModuleLike> &mods) {
    std::error_code ec;

    if (pathOpt == "") {
      llvm::errs() << "No path was supplied\n";
      return failure();
    }

    llvm::ToolOutputFile outputFile(pathOpt, ec, llvm::sys::fs::OpenFlags::OF_None);
    if (ec) {
      llvm::errs() << "unable to open state file: " << ec.message() << '\n';
      return failure();
    }

    if (!serializeModuleToJson(outputFile.os(), mods))
      return failure();

    outputFile.keep();
    return success();
  }

public:
  using impl::HWStateJsonBase<HWStateJsonPass>::HWStateJsonBase;

  void runOnOperation() final {
    hw::InstanceGraph &instGraph = getAnalysis<hw::InstanceGraph>();

    llvm::SmallVector<hw::HWModuleLike> mods;
    auto tops = instGraph.getInferredTopLevelNodes();

    if (failed(tops)) {
      getOperation().emitError("No top module\n");
      signalPassFailure();
      return;
    }

    for (auto *mod : *tops) {
      mods.push_back(mod->getModule<hw::HWModuleLike>());
    }

    if (failed(generateJson(strPath, mods))) {
      signalPassFailure();
    }
  }
};

} // namespace
} // namespace circt::cosimGen
