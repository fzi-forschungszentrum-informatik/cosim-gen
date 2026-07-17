//===----------------------------------------------------------------------===//
//
// This file is licensed under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#ifndef COMMON_PORT_TAGGING_H
#define COMMON_PORT_TAGGING_H

#include "circt/Dialect/HW/HWOps.h"
#include "llvm/ADT/SmallVector.h"
#include <string>

namespace circt {
namespace cosimGen {

void tagPort(hw::HWModuleLike mod, unsigned int portId, StringRef annon);
void tagPorts(hw::HWModuleLike mod, const SmallVector<unsigned int> &ports, StringRef tag);

} // namespace cosimGen
} // namespace circt

#endif
