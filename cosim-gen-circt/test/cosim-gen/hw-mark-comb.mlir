// RUN: cosim-gen-opt --hw-mark-comb="path=/sub" %s | FileCheck %s

// Test hw-mark-comb pass
// This pass marks combinational logic and removes unmarked parts

// CHECK-LABEL: hw.module @top
hw.module @top(in %clk : !seq.clock, in %x : i32, out y : i32) {
  // Instance to comb_module should be kept
  // CHECK: hw.instance "sub" @comb_module
  %inst.y = hw.instance "sub" @comb_module(x: %x: i32) -> (y: i32)
  hw.output %inst.y : i32
}

// CHECK-LABEL: hw.module @comb_module
// CHECK: {graph_hide = true}
hw.module @comb_module(in %x : i32, out y : i32) {
  // Combinational logic that should be marked
  // The module should have the comb marker attribute
  %0 = comb.add %x, %x : i32
  %1 = comb.mul %0, %0 : i32
  hw.output %1 : i32
}

// CHECK-LABEL: hw.module @seq_module
hw.module @seq_module(in %clk : !seq.clock, in %x : i32, out y : i32) {
  // Sequential logic - marked with graph_hide since not in path
  %reg = seq.firreg %x clock %clk : i32
  hw.output %reg : i32
}

// CHECK-LABEL: hw.module @mixed_module
hw.module @mixed_module(in %clk : !seq.clock, in %x : i32, out y : i32) {
  // Module with both comb and seq logic
  %reg = seq.firreg %x clock %clk : i32
  %0 = comb.add %reg, %reg : i32
  hw.output %0 : i32
}

// CHECK-LABEL: hw.module @pureComb
hw.module @pureComb(in %a : i32, in %b : i32, out y : i32) {
  // Pure combinational module
  %0 = comb.add %a, %b : i32
  %1 = comb.mul %0, %0 : i32
  hw.output %1 : i32
}
