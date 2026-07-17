// RUN: cosim-gen-opt --hw-remove-sv %s | FileCheck %s

// Test hw-remove-sv pass with various SV constructs
// Note: sv.assert must be inside sv.always posedge region

// CHECK-LABEL: hw.module @AllSVConstructs
// sv.assert must be in a procedural region like sv.always posedge %clk { ... }
// Note: clock must be i1 type for sv.always posedge
hw.module @AllSVConstructs(in %clk : i1, in %cond : i1, in %x : i32, out y : i32) {
  sv.always posedge %clk {
    // CHECK-NOT: sv.assert
    %c1 = hw.constant 1 : i1
    sv.assert %c1, immediate
  }
  
  // Regular logic should remain
  %0 = comb.add %x, %x : i32
  hw.output %0 : i32
}

// CHECK-LABEL: hw.module @SVAlways
hw.module @SVAlways(in %clk : i1, in %x : i32, out y : i32) {
  // sv.always with content - should be removed
  // CHECK-NOT: sv.always
  // CHECK-NOT: sv.verbatim
  sv.always posedge %clk {
    sv.verbatim "x <= y;"
  }
  
  %0 = comb.mul %x, %x : i32
  hw.output %0 : i32
}
