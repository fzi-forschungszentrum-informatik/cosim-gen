// RUN: cosim-extract --path=/extracted --port=".*out.*" %s -o - | FileCheck %s

// Test cosim-extract tool with subgraph extraction
// This test verifies that:
// 1. Only the selected subgraph is kept
// 2. Unused modules are removed
// 3. Ports are properly propagated

// =============================================================================
// Test: Subgraph extraction - select only /extracted instance
// =============================================================================
//
// The extraction target (/extracted) is protected from folding/inlining only
// UNTIL hw-taint runs; after that it's optimized like anything else. Here the
// trivial `top` wrapper gets inlined into the target, so ExtractedModule
// becomes the new (public) top, keeping its child instance. The unselected
// NotExtractedModule / UnusedSibling are removed.

// Inputs are driven from top's own port (not a constant) so the extracted
// logic isn't itself constant-foldable - see cosim-extract-foldable.mlir for
// the fully-foldable case.
hw.module @top(in %in : i8, out result: i8) {
  %extracted.out = hw.instance "extracted" @ExtractedModule(in: %in: i8) -> (out: i8)

  // This instance is NOT part of the selected subgraph - should be removed
  %not_extracted.out = hw.instance "not_extracted" @NotExtractedModule(in: %in: i8) -> (out: i8)

  %sum = comb.add %extracted.out, %not_extracted.out : i8
  hw.output %sum : i8
}

// The target becomes the new top (top inlined into it), child preserved.
// CHECK-LABEL: hw.module @ExtractedModule(in %in : i8, out out : i8)
// CHECK: hw.instance "extracted/child" @ChildModule
hw.module private @ExtractedModule(in %in : i8, out out: i8) {
  %0 = comb.add %in, %in : i8
  %child.y = hw.instance "child" @ChildModule(x: %0: i8) -> (y: i8)
  hw.output %child.y : i8
}

// Child of extracted module - should also be kept
// CHECK-LABEL: hw.module private @ChildModule(in %x : i8, out y : i8)
hw.module private @ChildModule(in %x : i8, out y: i8) {
  %0 = comb.mul %x, %x : i8
  hw.output %0 : i8
}

// CHECK-NOT: hw.module @NotExtractedModule
// This module is NOT part of the selected subgraph - should be removed
hw.module private @NotExtractedModule(in %in : i8, out out: i8) {
  %0 = comb.sub %in, %in : i8
  hw.output %0 : i8
}

// CHECK-NOT: hw.module @UnusedSibling
// This module is also not part of the subgraph - should be removed
hw.module private @UnusedSibling(in %in : i8, out out: i8) {
  %0 = comb.divu %in, %in : i8
  hw.output %0 : i8
}
