//===----------------------------------------------------------------------===//
//
// This file is licensed under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#ifndef COSIM_GEN_PATHCOMP_H
#define COSIM_GEN_PATHCOMP_H

#include "circt/Dialect/HW/HWInstanceGraph.h"
#include "llvm/ADT/SmallVector.h"
#include "llvm/Support/Error.h"
#include <string>

namespace circt {
namespace cosimGen {

int pathCompare(const SmallVector<std::string> &searchPath, const igraph::InstancePath &instPath);
int pathCompare(const igraph::InstancePath &searchPath, const igraph::InstancePath &instPath);
SmallVector<std::string> parsePath(const std::string path);
std::string path2Str(const igraph::InstancePath path);

llvm::Expected<igraph::InstancePath> strPath2circtPath(igraph::InstancePathCache &instancePathCache, std::string path);
igraph::InstanceRecord *getInstanceRecord(hw::InstanceGraph &iG, std::string path);
igraph::InstanceRecord *getInstanceRecord(igraph::InstancePathCache &iPC, std::string path);
igraph::InstanceRecord *getInstanceRecord(igraph::InstancePathCache &instancePathCache,
                                          igraph::InstancePath &searchPath);

} // namespace cosimGen
} // namespace circt

#endif
