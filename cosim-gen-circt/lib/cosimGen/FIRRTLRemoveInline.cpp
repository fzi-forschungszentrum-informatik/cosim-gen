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
#define DEBUG_TYPE "firrlt-remove-inline"

#include "cosimGen/Passes.h"

namespace circt::cosimGen {
#define GEN_PASS_DEF_FIRRTLREMOVEINLINE
#include "cosimGen/Passes.h.inc"

namespace {

struct FIRRTLRemoveInlinePass : impl::FIRRTLRemoveInlineBase<FIRRTLRemoveInlinePass> {
public:
  using impl::FIRRTLRemoveInlineBase<FIRRTLRemoveInlinePass>::FIRRTLRemoveInlineBase;

  void runOnOperation() final {
    getOperation().walk([&](firrtl::FModuleOp mod) {
      // Remove inline annotation if present
      if (firrtl::AnnotationSet::hasAnnotation(mod, firrtl::inlineAnnoClass)) {
        llvm::SmallVector<circt::firrtl::Annotation> filteredAnnos;
        auto annos = firrtl::AnnotationSet(mod);
        for (const auto &anno : annos)
          if (!anno.isClass(firrtl::inlineAnnoClass))
            filteredAnnos.push_back(anno);

        annos = circt::firrtl::AnnotationSet(filteredAnnos, mod->getContext());
        annos.applyToOperation(mod);
      }
    });
  }
};

} // namespace
} // namespace circt::cosimGen
