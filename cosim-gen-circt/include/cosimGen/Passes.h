//===----------------------------------------------------------------------===//
//
// This file is licensed under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#ifndef COSIM_GEN_PASSES_H
#define COSIM_GEN_PASSES_H

#include "mlir/Pass/Pass.h"
#include <memory>

namespace circt {
namespace cosimGen {
#define GEN_PASS_DECL
#include "cosimGen/Passes.h.inc"

#define GEN_PASS_REGISTRATION
#include "cosimGen/Passes.h.inc"

} // namespace cosimGen
} // namespace circt

#endif
