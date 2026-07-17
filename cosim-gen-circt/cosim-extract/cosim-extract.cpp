//===- cosim-extract.cpp - The cosim-extract utility ------------------------===//
//
// Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//
//
// This file implements 'cosim-extract', which extracts traceable ports from
// a hardware module and propagates them to the top level.
//
//===----------------------------------------------------------------------===//

#include "circt/InitAllDialects.h"
#include "circt/Support/Version.h"
#include "cosimGen/Passes.h"
#include "mlir/IR/AsmState.h"
#include "mlir/IR/BuiltinOps.h"
#include "mlir/InitAllDialects.h"
#include "mlir/Parser/Parser.h"
#include "mlir/Pass/PassManager.h"
#include "mlir/Support/FileUtilities.h"
#include "mlir/Support/Timing.h"
#include "mlir/Transforms/Passes.h"
#include "llvm/Support/InitLLVM.h"
#include "llvm/Support/MemoryBuffer.h"
#include "llvm/Support/SourceMgr.h"
#include "llvm/Support/ToolOutputFile.h"

using namespace mlir;
using namespace circt;
using namespace circt::cosimGen;

//===----------------------------------------------------------------------===//
// Command Line Arguments
//===----------------------------------------------------------------------===//

static llvm::cl::opt<std::string> inputFilename(llvm::cl::Positional, llvm::cl::desc("<input file>"),
                                                llvm::cl::init("-"));

static llvm::cl::opt<std::string> outputFilename("o", llvm::cl::desc("Output filename"),
                                                 llvm::cl::value_desc("filename"), llvm::cl::init("-"));

static llvm::cl::opt<std::string> modulePath("path",
                                             llvm::cl::desc("Module path for extraction passes. If omitted, the "
                                                            "whole design is kept as-is (no extraction/port "
                                                            "propagation) and only the shared cleanup pipeline "
                                                            "runs - this is how the whole, un-extracted design is "
                                                            "built as a pseudo-component"),
                                             llvm::cl::value_desc("path"), llvm::cl::init(""));

static llvm::cl::opt<std::string> portRegex("port", llvm::cl::desc("Port regex pattern for propagation"),
                                            llvm::cl::value_desc("regex"), llvm::cl::init(".*"));

static llvm::cl::opt<std::string> topName("top-name", llvm::cl::desc("New top module name"),
                                          llvm::cl::value_desc("name"));

static llvm::cl::opt<bool> verifyPasses("verify-each",
                                        llvm::cl::desc("Run the verifier after each transformation pass"),
                                        llvm::cl::init(true));

static llvm::cl::opt<bool> removeSV("remove-sv",
                                    llvm::cl::desc("Strip sv dialect asserts/prints at the end of the "
                                                   "pipeline (needed before lowering the result with "
                                                   "arcilator)"),
                                    llvm::cl::init(false));

static llvm::cl::opt<std::string> stateJsonPath("state-json",
                                                llvm::cl::desc("Emit a JSON description of the extracted module's "
                                                               "bit-level IO layout to this path"),
                                                llvm::cl::value_desc("path"), llvm::cl::init(""));

//===----------------------------------------------------------------------===//
// Main Tool Logic
//===----------------------------------------------------------------------===//

static void addCleanupTail(PassManager &pm) {
  pm.nest<hw::HWModuleOp>().addPass(createHWRemoveCustomAttr());

  if (!stateJsonPath.empty()) {
    HWStateJsonOptions stateJsonOpts;
    stateJsonOpts.strPath = stateJsonPath.getValue();
    pm.addPass(createHWStateJson(stateJsonOpts));
  }
  if (removeSV)
    pm.addPass(createHWRemoveSV());
}

static void buildTopPipeline(PassManager &pm) {
  pm.addPass(createCanonicalizerPass());
  pm.addPass(createCSEPass());
  pm.addPass(createHWDme());
  pm.addPass(createHWRemoveOM());
  pm.addPass(createHWOptInterfaces());

  addCleanupTail(pm);
}

static void buildExtractPipeline(PassManager &pm) {
  HWKeepPathOptions keepPathOpts;
  keepPathOpts.path = modulePath.getValue();
  pm.addPass(createHWKeepPath(keepPathOpts));

  // Initial canonicalization
  pm.addPass(createCanonicalizerPass());
  pm.addPass(createCSEPass());
  pm.addPass(createHWDme());
  pm.addPass(createHWRemoveOM());

  // Opt interfaces with keepPorts
  HWOptInterfacesOptions optOpts;
  optOpts.keepPorts = true;
  pm.addPass(createHWOptInterfaces(optOpts));

  // Propagate ports to TLM
  HWPropPorts2TLMOptions propOpts;
  propOpts.strPath = modulePath.getValue();
  propOpts.strRegex = portRegex.getValue();
  propOpts.replaceInstOuts = true;
  pm.addPass(createHWPropPorts2TLM(propOpts));

  // Taint the module
  HWTaintOptions taintOpts;
  taintOpts.path = modulePath.getValue();
  pm.addPass(createHWTaint(taintOpts));

  HWReleaseKeepOptions releaseOpts;
  releaseOpts.path = modulePath.getValue();
  pm.addPass(createHWReleaseKeep(releaseOpts));

  // Second round of canonicalization
  pm.addPass(createCanonicalizerPass());
  pm.addPass(createCSEPass());
  pm.addPass(createHWDme());

  // Opt interfaces and inline trivial
  pm.addPass(createHWOptInterfaces());
  pm.addPass(createHWInlineTrivial());

  // Third round of canonicalization
  pm.addPass(createCanonicalizerPass());
  pm.addPass(createCSEPass());
  pm.addPass(createHWDme());

  // Rename top module (if name specified)
  if (!topName.empty()) {
    HWRenameTopOptions renameOpts;
    renameOpts.name = topName.getValue();
    pm.addPass(createHWRenameTop(renameOpts));
  }

  addCleanupTail(pm);
}

static void buildPipeline(PassManager &pm) {
  if (modulePath.empty())
    buildTopPipeline(pm);
  else
    buildExtractPipeline(pm);
}

static LogicalResult processBuffer(MLIRContext &context, TimingScope &ts, llvm::SourceMgr &sourceMgr,
                                   llvm::ToolOutputFile &outputFile) {
  OwningOpRef<ModuleOp> module;
  {
    auto parserTimer = ts.nest("Parse MLIR input");
    module = parseSourceFile<ModuleOp>(sourceMgr, &context);
  }
  if (!module)
    return failure();

  PassManager pm(&context);
  pm.enableVerifier(verifyPasses);
  pm.enableTiming(ts);
  if (failed(applyPassManagerCLOptions(pm)))
    return failure();

  buildPipeline(pm);

  if (failed(pm.run(module.get())))
    return failure();

  auto outputTimer = ts.nest("Print MLIR output");
  module->print(outputFile.os());
  return success();
}

static LogicalResult executeCosimExtract(MLIRContext &context) {
  DefaultTimingManager tm;
  applyDefaultTimingManagerCLOptions(tm);
  auto ts = tm.getRootScope();

  std::string errorMessage;
  auto input = openInputFile(inputFilename, &errorMessage);
  if (!input) {
    llvm::errs() << errorMessage << "\n";
    return failure();
  }

  auto outputFile = openOutputFile(outputFilename, &errorMessage);
  if (!outputFile) {
    llvm::errs() << errorMessage << "\n";
    return failure();
  }

  llvm::SourceMgr sourceMgr;
  sourceMgr.AddNewSourceBuffer(std::move(input), llvm::SMLoc());
  SourceMgrDiagnosticHandler sourceMgrHandler(sourceMgr, &context);

  if (failed(processBuffer(context, ts, sourceMgr, *outputFile)))
    return failure();

  outputFile->keep();
  return success();
}

/// Main driver for the command. This sets up LLVM and MLIR, and parses
/// command line options before passing off to 'executeCosimExtract'.
int main(int argc, char **argv) {
  llvm::InitLLVM y(argc, argv);
  llvm::setBugReportMsg("PLEASE report this cosim-extract crash to the cosim-gen maintainers "
                        "and include the backtrace above.\n");

  // Register passes before parsing command-line options, so that they are
  // available for use with options like `--mlir-print-ir-before`.
  registerCSEPass();
  registerCanonicalizerPass();
  registerStripDebugInfoPass();
  registerSymbolDCEPass();
  circt::cosimGen::registerPasses();

  // Register any pass manager command line options.
  registerMLIRContextCLOptions();
  registerPassManagerCLOptions();
  registerDefaultTimingManagerCLOptions();
  registerAsmPrinterCLOptions();
  llvm::cl::AddExtraVersionPrinter([](llvm::raw_ostream &os) { os << circt::getCirctVersion() << '\n'; });

  llvm::cl::ParseCommandLineOptions(argc, argv, "cosim-extract - port extraction tool\n");

  DialectRegistry registry;
  mlir::registerAllDialects(registry);
  circt::registerAllDialects(registry);
  MLIRContext context(registry);

  return failed(executeCosimExtract(context));
}
