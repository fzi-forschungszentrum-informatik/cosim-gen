// RUN: cosim-gen-opt --hw-rename-top=name=NewTop %s | FileCheck %s

// Test hw-rename-top pass
// This pass renames the top module to a specified name
// The pass uses CIRCT's getInferredTopLevelNodes() which requires exactly one top module

// =============================================================================
// Test: Top module renaming
// =============================================================================

// CHECK-LABEL: hw.module @NewTop
hw.module @OriginalTop (in %x : i32, out y : i32) {
  %0 = comb.add %x, %x : i32
  hw.output %0 : i32
}
