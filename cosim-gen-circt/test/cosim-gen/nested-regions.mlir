// RUN: cosim-gen-opt --hw-remove-sv %s | FileCheck %s

// CIRCT MLIR test file with nested regions and blocks
// Demonstrates various CIRCT constructs with multiple levels of nesting

// CHECK-LABEL: hw.module @IfElseLogic
// CHECK-NOT: sv.always
// CHECK-NOT: sv.if
// CHECK-NOT: sv.verbatim
module attributes {circt.lowering_options = "disallowLocalVariables"} {

  // hw.module with sv.if/sv.else inside sv.always demonstrating true nested regions with blocks
  // sv.if creates a region with blocks for if/else branches
  hw.module @IfElseLogic(in %clk: !seq.clock, in %cond: i1, in %a: i32, in %b: i32, in %c: i32, out y: i32) {
    %c0 = hw.constant 0 : i1
    %sum = comb.or %a, %b, %c : i32
    %diff = comb.and %a, %b, %c : i32
    %selected = comb.mux %c0, %sum, %diff : i32
    %reg = seq.firreg %selected clock %clk : i32
    // sv.always with sv.if/sv.else creates nested regions with blocks
    sv.always {
      sv.if %cond {
        
        sv.verbatim "`ifdef COND\n`endif"
        sv.if %cond {
          sv.verbatim "`ifdef COND\n`endif"
        }
      } else {
        sv.verbatim "`else\n`endif"
      }
    }
    hw.output %reg : i32
  }

  // CHECK-LABEL: hw.module @SimpleModule
  hw.module @SimpleModule(in %x: i32, out y: i32) {
    // Simple module without nested regions
    %0 = comb.add %x, %x : i32
    hw.output %0 : i32
  }

  // CHECK-LABEL: hw.module @WithClock
  hw.module @WithClock(in %clk: !seq.clock, in %x: i32, out y: i32) {
    // Module with clock and register
    %reg = seq.firreg %x clock %clk : i32
    %0 = comb.add %reg, %reg : i32
    hw.output %0 : i32
  }

} // module
