// RUN: cosim-gen-opt --hw-remove-custom-attr %s | FileCheck %s

// Test hw-remove-custom-attr pass
// This pass removes custom attributes from HW modules and operations

// CHECK-LABEL: hw.module @top
// The keep and unused attributes should be removed
// CHECK-NOT: keep
// CHECK-NOT: unused
hw.module @top(in %x : i32, out y : i32) attributes {keep, unused} {
  %0 = comb.add %x, %x : i32
  // CHECK-NOT: tainted
  // CHECK-NOT: dummyConst
  // CHECK-NOT: graph_hide
  hw.output %0 : i32
}

// CHECK-LABEL: hw.module @WithMarker
// The graph_hide attribute should be removed
// CHECK-NOT: graph_hide
hw.module @WithMarker(in %a : i1, out b : i1) attributes {graph_hide} {
  %0 = comb.and %a, %a : i1
  hw.output %0 : i1
}
