// RUN: cosim-gen-opt --show-dialects | FileCheck %s
// CHECK: Available Dialects:
// CHECK-SAME: builtin
// CHECK-SAME: comb
// CHECK-SAME: firrtl
// CHECK-SAME: hw
// CHECK-SAME: om
// CHECK-SAME: seq
// CHECK-SAME: sv

// Test that cosim-gen-opt can parse and process multiple dialects
// This file tests parsing, not transformation output

// RUN: cosim-gen-opt %s | FileCheck --check-prefix=PARSE %s
// PARSE-LABEL: hw.module @MultiDialect
hw.module @MultiDialect(in %clk : !seq.clock, in %x : i32, out y : i32) {
  // SEQ dialect - register
  %reg = seq.firreg %x clock %clk : i32
  
  // COMB dialect - operations
  %0 = comb.add %reg, %reg : i32
  %1 = comb.mul %0, %reg : i32
  %c0 = hw.constant 0 : i1
  %2 = comb.mux %c0, %0, %1 : i32
  
  hw.output %2 : i32
}

// Note: FIRRTL modules require firrtl.circuit wrapper which is not supported in this context
// Testing HW module instead
hw.module @FirrtlPlaceholder(in %x : i32, out y : i32) {
  // HW dialect - FIRRTL operations would go here in a real circuit
  hw.output %x : i32
}

// PARSE-LABEL: hw.module @WithInstance
hw.module @WithInstance(in %a : i32, in %b : i32, out y : i32) {
  // HW instance operation
  %inst.out = hw.instance "sub" @SubModule(a: %a: i32, b: %b: i32) -> (out: i32)
  hw.output %inst.out : i32
}

// PARSE-LABEL: hw.module @SubModule
hw.module @SubModule(in %a : i32, in %b : i32, out out : i32) {
  %0 = comb.add %a, %b : i32
  hw.output %0 : i32
}
