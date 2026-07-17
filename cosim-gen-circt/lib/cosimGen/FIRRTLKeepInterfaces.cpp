//===----------------------------------------------------------------------===//
//
// Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#include "circt/Dialect/FIRRTL/AnnotationDetails.h"
#include "circt/Dialect/FIRRTL/FIRRTLAnnotations.h"
#include "circt/Dialect/FIRRTL/FIRRTLOps.h"

#include "llvm/Support/Debug.h"
#define DEBUG_TYPE "firrlt-keep-interfaces"

#include "cosimGen/Passes.h"

namespace circt::cosimGen {
#define GEN_PASS_DEF_FIRRTLKEEPINTERFACES
#include "cosimGen/Passes.h.inc"

namespace {

struct FIRRTLKeepInterfacesPass : impl::FIRRTLKeepInterfacesBase<FIRRTLKeepInterfacesPass> {

private:
  // Recurses into both BundleType and FVectorType so every ground-type leaf
  // (including individual vector elements, e.g. a `pins: {...}[8]` GPIO
  // array) gets its own dont-touch. A dont-touch on a whole vector - rather
  // than on each of its elements - blocks firtool's aggregate lowering from
  // subdividing that port at all ("port should be subdivided, but cannot
  // because of annotations on a vector").
  void getLeafTypes(firrtl::FIRRTLBaseType type, llvm::SmallVector<uint64_t> &fieldIds, uint64_t curId = 0) {
    if (auto bt = dyn_cast<firrtl::BundleType>(type)) {
      for (auto [i, el] : llvm::enumerate(bt.getElements()))
        getLeafTypes(el.type, fieldIds, curId + bt.getFieldID(i));
    } else if (auto vt = dyn_cast<firrtl::FVectorType>(type)) {
      for (uint64_t i = 0, e = vt.getNumElements(); i < e; ++i)
        getLeafTypes(vt.getElementType(), fieldIds, curId + vt.getFieldID(i));
    } else {
      fieldIds.push_back(curId);
    }
  }

  void addDontTouchToAllPorts(circt::firrtl::FModuleOp mod) {
    SmallVector<Attribute> annos;
    auto *context = mod.getContext();

    for (auto [i, portInfo] : llvm::enumerate(mod.getPortList())) {
      auto annoSet = firrtl::AnnotationSet::forPort(mod, i);
      auto firrtlType = cast<firrtl::FIRRTLType>(portInfo.type);

      if (auto baseType = dyn_cast<firrtl::FIRRTLBaseType>(firrtlType);
          baseType && (isa<firrtl::BundleType>(baseType) || isa<firrtl::FVectorType>(baseType))) {
        llvm::SmallVector<uint64_t> res;
        getLeafTypes(baseType, res);

        llvm::SmallVector<Attribute> fieldAnnos;
        for (auto anno : annoSet)
          fieldAnnos.push_back(anno.getAttr());

        auto dontTouchDict = mlir::DictionaryAttr::get(
            context, {mlir::NamedAttribute(mlir::StringAttr::get(context, "class"),
                                           mlir::StringAttr::get(context, firrtl::dontTouchAnnoClass))});
        firrtl::Annotation dontTouchAnno(dontTouchDict);

        // Add dontTouch annotation for each leaf field
        for (auto fieldId : res) {
          auto fAnno = firrtl::Annotation(dontTouchAnno, fieldId);
          fieldAnnos.push_back(fAnno.getAttr());
        }

        annos.push_back(ArrayAttr::get(mod.getContext(), fieldAnnos));
      } else {
        // Non-bundle types: just add dontTouch to the port
        annoSet.addDontTouch();
        annos.push_back(annoSet.getArrayAttr());
      }
    }
    mod.setPortAnnotations(annos);
  }

public:
  using impl::FIRRTLKeepInterfacesBase<FIRRTLKeepInterfacesPass>::FIRRTLKeepInterfacesBase;

  void runOnOperation() final {
    llvm::StringRef modNames = strModules;
    llvm::SmallVector<llvm::StringRef> modTokens;
    modNames.split(modTokens, ",");

    getOperation().walk([&](firrtl::FModuleOp mod) {
      if (modNames.contains(mod.getModuleName())) {
        LLVM_DEBUG(llvm::dbgs() << "Preserving ports of " << mod.getModuleName() << "\n");
        addDontTouchToAllPorts(mod);
      }
    });
  }
};

} // namespace
} // namespace circt::cosimGen
