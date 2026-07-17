//===----------------------------------------------------------------------===//
//
// Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#include "cosimGen/PortTagging.h"

namespace circt {
namespace cosimGen {

static void setDfl(hw::HWModuleLike mod) {
  auto ctx = mod->getContext();
  auto dflAttr = DictionaryAttr::get(ctx, {});

  for (size_t portNum = 0, e = mod.getNumPorts(); portNum < e; ++portNum) {
    auto attrs = dyn_cast_or_null<DictionaryAttr>(mod.getPortAttrs(portNum));
    if (attrs)
      continue;
    mod.setPortAttrs(portNum, dflAttr);
  }
}

void tagPort(hw::HWModuleLike mod, unsigned int portNum, StringRef tag) {
  auto ctx = mod->getContext();

  auto tagAttr = StringAttr::get(ctx, tag);
  auto valAttr = UnitAttr::get(ctx);
  auto attrs = dyn_cast_or_null<DictionaryAttr>(mod.getPortAttrs(portNum));
  if (attrs)
    mod.setPortAttr(portNum, tagAttr, valAttr);
  else {
    auto attrDict = DictionaryAttr::get(ctx, {NamedAttribute(tagAttr, valAttr)});
    mod.setPortAttrs(portNum, attrDict);
  }

  setDfl(mod);
}

void tagPorts(hw::HWModuleLike mod, const SmallVector<unsigned int> &ports, StringRef tag) {
  auto ctx = mod->getContext();

  for (auto portNum : ports) {
    auto tagAttr = StringAttr::get(ctx, tag);
    auto valAttr = UnitAttr::get(ctx);
    auto attrs = dyn_cast_or_null<DictionaryAttr>(mod.getPortAttrs(portNum));
    if (attrs)
      mod.setPortAttr(portNum, tagAttr, valAttr);
    else {
      auto attrDict = DictionaryAttr::get(ctx, {NamedAttribute(tagAttr, valAttr)});
      mod.setPortAttrs(portNum, attrDict);
    }
  }

  setDfl(mod);
}

} // namespace cosimGen
} // namespace circt
