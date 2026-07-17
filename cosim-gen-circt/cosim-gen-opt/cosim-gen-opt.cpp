//===----------------------------------------------------------------------===//
//
// This file is licensed under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#include "circt/Support/Version.h"
#include "mlir/Pass/PassRegistry.h"
#include "mlir/Tools/mlir-opt/MlirOptMain.h"
#include "mlir/Transforms/Passes.h"
#include "llvm/Support/PrettyStackTrace.h"

#include "circt/InitAllDialects.h"
#include "mlir/InitAllDialects.h"

#include "cosimGen/Passes.h"

int main(int argc, char **argv) {
  llvm::setBugReportMsg("PLEASE report this cosim-gen-opt crash to the cosim-gen maintainers "
                        "and include the backtrace above.\n");

  mlir::DialectRegistry registry;
  mlir::registerAllDialects(registry);
  circt::registerAllDialects(registry);

  mlir::registerCSEPass();
  mlir::registerCanonicalizerPass();
  mlir::registerStripDebugInfoPass();
  mlir::registerSymbolDCEPass();

  circt::cosimGen::registerPasses();

  llvm::cl::AddExtraVersionPrinter([](llvm::raw_ostream &os) { os << circt::getCirctVersion() << '\n'; });

  return mlir::failed(mlir::MlirOptMain(argc, argv, "CIRCT standalone optimizer driver", registry));
}
