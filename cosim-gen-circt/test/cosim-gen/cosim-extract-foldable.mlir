// RUN: cosim-extract --path=/extracted --port=".*out.*" %s -o - | FileCheck %s

// Regression test for the "completely foldable" case: the extraction
// target's entire logic is compile-time constant (its only input is fed a
// literal hw.constant at its sole call site, and its body is pure arithmetic
// on that input, 10*10 = 100).
//
// The extract module is protected from folding only until hw-taint runs;
// after taint it's optimized like anything else. So here the whole subgraph
// legitimately folds end to end: rewireModule hoists the constant in, the
// body folds to hw.constant 100, and the now-trivial module is inlined away.
// The final result is just the top module emitting the constant. (Folding
// BEFORE taint would have crashed prop-ports/taint by dissolving the --path
// target - that's what the pre-taint protection prevents.)

// =============================================================================
// Test: Extraction target is fully constant-driven and folds away post-taint
// =============================================================================

// The whole design collapses to a single constant on the top module.
// CHECK-LABEL: hw.module @top(out out : i8)
// CHECK-NEXT: %[[C:.+]] = hw.constant 100 : i8
// CHECK-NEXT: hw.output %[[C]] : i8
hw.module @top(out result: i8) {
  %c10 = hw.constant 10 : i8
  %extracted.out = hw.instance "extracted" @ExtractedModule(in: %c10: i8) -> (out: i8)

  // This instance is NOT part of the selected subgraph - should be removed
  %not_extracted.out = hw.instance "not_extracted" @NotExtractedModule(in: %c10: i8) -> (out: i8)

  %sum = comb.add %extracted.out, %not_extracted.out : i8
  hw.output %sum : i8
}

// Everything below folds away - no module survives besides the folded top.
// CHECK-NOT: hw.module private @ExtractedModule
// CHECK-NOT: hw.module @NotExtractedModule
// CHECK-NOT: comb.mul
hw.module private @ExtractedModule(in %in : i8, out out: i8) {
  %0 = comb.mul %in, %in : i8
  hw.output %0 : i8
}

hw.module private @NotExtractedModule(in %in : i8, out out: i8) {
  %0 = comb.divu %in, %in : i8
  hw.output %0 : i8
}
