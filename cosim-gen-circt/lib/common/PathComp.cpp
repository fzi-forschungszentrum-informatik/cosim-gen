//===----------------------------------------------------------------------===//
//
// Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#include "common/PathComp.h"
#include "llvm/Support/Error.h"

namespace circt {
namespace cosimGen {

int pathCompare(const SmallVector<std::string> &searchPath, const igraph::InstancePath &instPath) {
  const size_t tlTokens = searchPath.size();
  const size_t instTokens = instPath.size();
  const size_t vMax = std::min(tlTokens, instTokens);

  for (size_t i = 0; i < vMax; ++i) {
    if (searchPath[i] != instPath[i].getInstanceName().str()) {
      return i - tlTokens;
    }
  }
  return instTokens - tlTokens;
}

int pathCompare(const igraph::InstancePath &searchPath, const igraph::InstancePath &instPath) {
  const size_t tlTokens = searchPath.size();
  const size_t instTokens = instPath.size();
  const size_t vMax = std::min(tlTokens, instTokens);

  for (size_t i = 0; i < vMax; ++i) {
    if (searchPath[i] != instPath[i]) {
      return i - tlTokens;
    }
  }
  return instTokens - tlTokens;
}

SmallVector<std::string> parsePath(const std::string path) {
  SmallVector<std::string> tokens;
  std::string tmp;
  std::stringstream ss(path);
  while (getline(ss, tmp, '/')) {
    if (tmp != "")
      tokens.push_back(tmp);
  }
  return tokens;
}

std::string path2Str(const igraph::InstancePath path) {
  std::stringstream ss;
  for (unsigned i = 0, n = path.size(); i < n; ++i) {
    ss << "/" << path[i].getInstanceName().str();
  }
  return ss.str();
}

circt::igraph::InstanceRecord *getInstanceRecord(igraph::InstancePathCache &instancePathCache,
                                                 igraph::InstancePath &searchPath) {
  size_t noTokens = searchPath.size();
  if (noTokens == 0) {
    return *instancePathCache.instanceGraph.getInferredTopLevelNodes()->front()->uses().begin();
  }

  for (circt::igraph::InstanceGraphNode *node : instancePathCache.instanceGraph) {
    auto hwModule = node->getModule<hw::HWModuleLike>();
    auto instPaths = instancePathCache.getAbsolutePaths(hwModule);
    for (auto instPath : instPaths) {
      if (searchPath == instPath) {
        for (auto rec : node->uses()) {
          auto inst = rec->getInstance<hw::HWInstanceLike>();

          // Thats just the public marker
          if (!inst)
            continue;

          auto instName = inst.getInstanceName();
          auto targetName = searchPath[noTokens - 1].getInstanceName();
          if (instName != targetName)
            continue;

          // Verify parent module matches (only if path has more than one token)
          if (noTokens > 1) {
            auto parent = rec->getParent();
            if (!parent) {
              llvm::errs() << "Parent is null for instance " << targetName.str() << "\n";
              continue;
            }
            auto parentModule = parent->getModule<hw::HWModuleLike>();
            auto parentToken = searchPath[noTokens - 2];
            auto names = parentToken.getReferencedModuleNamesAttr();
            if (names.size() != 1) {
              llvm::errs() << "Expected 1 name in parent token, got " << names.size() << "\n";
              continue;
            }
            if (!parentModule || parentModule.getModuleName() != cast<StringAttr>(names[0]).getValue())
              continue;
          }
          return rec;
        }
        llvm::errs() << "Something went wrong - no matching instance record found for path\n";
        return nullptr;
      }
    }
  }

  return nullptr;
}

llvm::Expected<igraph::InstancePath> strPath2circtPath(igraph::InstancePathCache &instancePathCache, std::string path) {
  SmallVector<std::string> searchPath = parsePath(path);

  for (circt::igraph::InstanceGraphNode *node : instancePathCache.instanceGraph) {
    for (auto instPath : instancePathCache.getAbsolutePaths(node->getModule<hw::HWModuleLike>())) {
      if (pathCompare(searchPath, instPath) == 0) {
        return instPath;
      }
    }
  }

  // Path not found - build error message with available paths
  // Don't print to stderr here - let the caller decide how to handle the error
  std::string errMsg;
  llvm::raw_string_ostream os(errMsg);
  os << "Module path not found in design: " << path << "\nValid paths are:\n";
  for (auto *node : instancePathCache.instanceGraph) {
    auto hwModule = node->getModule();
    os << "\tModule " << hwModule.getModuleName() << ":\n";
    for (auto path : instancePathCache.getAbsolutePaths(hwModule)) {
      os << "\t\t- ";
      if (path.empty())
        os << "/";
      else
        for (auto token : path)
          os << "/" << token.getInstanceName();
      os << "\n";
    }
  }
  return llvm::createStringError(llvm::inconvertibleErrorCode(), errMsg);
}

igraph::InstanceRecord *getInstanceRecord(igraph::InstancePathCache &iPC, std::string path) {
  auto searchPathResult = cosimGen::strPath2circtPath(iPC, path);
  if (!searchPathResult) {
    llvm::errs() << "Error: " << llvm::toString(searchPathResult.takeError()) << "\n";
    return nullptr;
  }
  auto *instRec = cosimGen::getInstanceRecord(iPC, *searchPathResult);
  return instRec;
}

igraph::InstanceRecord *getInstanceRecord(hw::InstanceGraph &iG, std::string path) {
  igraph::InstancePathCache instancePathCache(iG);
  return getInstanceRecord(instancePathCache, path);
}

} // namespace cosimGen
} // namespace circt
