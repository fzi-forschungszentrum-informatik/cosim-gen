// RUN: cosim-extract --path=/partial --port="^y$" %s -o - | FileCheck %s

// Test cosim-extract tool with partial port extraction
// This test verifies that:
// 1. Only ports matching the regex are propagated
// 2. Non-matching ports are not propagated

// =============================================================================
// Test: Partial port extraction - only 'y' output port matches regex "^y$"
// =============================================================================
//
// Only the 'y' output matches "^y$", so only 'y' is propagated up as a new
// traceable port. After hw-taint the trivial `top` wrapper is inlined into
// the target, so PartialModule becomes the new top. Its port list gains the
// propagated 'y' (front) alongside top's own 'result'/'z_out' outputs; 'z' is
// NOT propagated as a separate port (it didn't match the regex).

// Input is driven from top's own port (not a constant).
hw.module @top(in %in : i8, out result: i8, out z_out: i8) {
  %partial.y, %partial.z = hw.instance "partial" @PartialModule(in: %in: i8) -> (y: i8, z: i8)

  // 'y' output matches "^y$" regex - will be propagated
  // 'z' output does not match "^y$" regex - will NOT be propagated
  // Combine y and z (rather than passing y straight through to top's own
  // output) so 'y' isn't already trivially wired to a top-level output port
  // before extraction runs - HWPropPorts2TLM treats a port already directly
  // connected to top's output as nothing left to propagate.
  %sum = comb.add %partial.y, %partial.z : i8
  hw.output %sum, %partial.z : i8, i8
}

// PartialModule becomes the new top. The propagated 'y' port is present; there
// is no separately-propagated 'z' port (only top's own result/z_out outputs).
// CHECK-LABEL: hw.module @PartialModule(in %in : i8, out y : i8, out result : i8, out z_out : i8)
hw.module private @PartialModule(in %in : i8, out y: i8, out z: i8) {
  %y_val = comb.mul %in, %in : i8
  %z_val = comb.divu %in, %in : i8
  hw.output %y_val, %z_val : i8, i8
}
