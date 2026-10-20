//===----------------------------------------------------------------------===//
//
// This file is licensed under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#ifndef HW_OPT_HW
#define HW_OPT_HW

#include "circt/Dialect/HW/HWOps.h"
#include "circt/Support/InstanceGraph.h"

#include "mlir/IR/AsmState.h"

#include <string>

namespace circt {
namespace cosimGen {

static constexpr llvm::StringRef KEEP = "keep";
static constexpr llvm::StringRef UNUSED = "unused";
static constexpr llvm::StringRef DUMMY_CONST = "dummyConst";
static constexpr llvm::StringRef TAINTED = "tainted";
static constexpr llvm::StringRef GRAPH_HIDE = "graph_hide";

void replaceOperandWithDummy(OpBuilder &builder, mlir::Operation *op, unsigned int operandId);
void replaceValueWithDummy(OpBuilder &builder, mlir::Value val);

size_t eraseUnused(hw::HWModuleOp hwModule, igraph::InstanceGraph *igraph = nullptr);
size_t eraseUnusedSimple(hw::HWModuleOp hwModule, igraph::InstanceGraph *igraph = nullptr);
size_t tryConstFold(hw::HWModuleOp hwModule, OpBuilder &builder);

} // namespace cosimGen
} // namespace circt

#endif
