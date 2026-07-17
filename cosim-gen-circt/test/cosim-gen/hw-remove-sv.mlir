// RUN: cosim-gen-opt --hw-remove-sv %s | FileCheck %s

// Test hw-remove-sv pass
// This pass removes SystemVerilog assert/assume operations

// sv.assert must be in a procedural region like sv.always posedge %clk { ... }
// Note: clock must be i1 type for sv.always posedge
hw.module @ModuleWithSV(in %clk : i1, in %x : i1, out y : i1) {
  sv.always posedge %clk {
    // CHECK-NOT: sv.assert
    %c1 = hw.constant 1 : i1
    sv.assert %c1, immediate
  }

  // CHECK-LABEL: hw.module @ModuleWithSV
  %0 = comb.add %x, %x : i1
  hw.output %0 : i1
}
