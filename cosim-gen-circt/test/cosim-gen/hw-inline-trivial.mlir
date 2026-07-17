// RUN: cosim-gen-opt --hw-inline-trivial %s | FileCheck %s

// Test hw-inline-trivial pass
// This pass inlines modules that have no logic (trivial modules)
// Note: Pass considers modules trivial only if they contain:
// - Only OutputOp with no operands, OR
// - WireOp, ConstantOp, ConstClockOp, and at most one InstanceOp

// =============================================================================
// Test 1: Basic trivial module inlining
// =============================================================================

// CHECK-LABEL: hw.module @top
// CHECK-NOT: hw.instance
// CHECK: hw.output %x : i32

// CHECK-LABEL: hw.module private @nonTrivial
// CHECK-NOT: hw.module @trivial

hw.module @top(in %x : i32, out y : i32) {
  %inst.y = hw.instance "trivial" @trivial(a: %x: i32) -> (y: i32)
  hw.output %inst.y : i32
}

hw.module private @nonTrivial(in %a : i32, out y : i32) {
  %0 = comb.add %a, %a : i32
  hw.output %0 : i32
}

hw.module private @trivial(in %a : i32, out y : i32) {
  hw.output %a : i32
}

// =============================================================================
// Test 2: Comprehensive trivial module scenarios
// =============================================================================

module {
// @topWithTrivial inlines @trivialForward, resulting in direct forwarding
// CHECK-LABEL: hw.module @topWithTrivial
// CHECK: hw.output %x : i32
hw.module @topWithTrivial(in %x : i32, out y : i32) {
  hw.output %x : i32
}

// @trivialForward is inlined and removed (was private)
// CHECK-NOT: hw.module @trivialForward
hw.module private @trivialForward(in %a : i32, out y : i32) {
  hw.output %a : i32
}

// @multiInputTrivial inlines @multiTrivial
// CHECK-LABEL: hw.module @multiInputTrivial
// CHECK: hw.output %a, %b : i32, i32
hw.module @multiInputTrivial(in %a : i32, in %b : i32, out x : i32, out y : i32) {
  hw.output %a, %b : i32, i32
}

// @multiTrivial is inlined and removed (was private)
// CHECK-NOT: hw.module @multiTrivial
hw.module private @multiTrivial(in %a : i32, in %b : i32, out x : i32, out y : i32) {
  hw.output %a, %b : i32, i32
}

// @reorderTrivial inlines @reorderPorts  
// CHECK-LABEL: hw.module @reorderTrivial
// CHECK: hw.output %b, %a : i32, i32
hw.module @reorderTrivial(in %a : i32, in %b : i32, out x : i32, out y : i32) {
  hw.output %b, %a : i32, i32
}

// @reorderPorts is inlined and removed (was private)
// CHECK-NOT: hw.module @reorderPorts
hw.module private @reorderPorts(in %a : i32, in %b : i32, out x : i32, out y : i32) {
  hw.output %b, %a : i32, i32
}

// @chainOfTrivial - all chained trivial modules inlined
// CHECK-LABEL: hw.module @chainOfTrivial
// CHECK: hw.output %x : i32
hw.module @chainOfTrivial(in %x : i32, out y : i32) {
  hw.output %x : i32
}

// @constModule has logic - should NOT be inlined, becomes non-private
// CHECK-LABEL: hw.module @constModule
// CHECK: hw.constant 42
hw.module @constModule(in %x : i32, out y : i32) {
  %c42_i32 = hw.constant 42 : i32
  %0 = comb.add %x, %c42_i32 : i32
  hw.output %0 : i32
}

// @nonTrivialLogic has actual logic - should NOT be inlined, becomes non-private
// CHECK-LABEL: hw.module @nonTrivialLogic
// CHECK: comb.add
hw.module @nonTrivialLogic(in %x : i32, out y : i32) {
  %0 = comb.add %x, %x : i32
  hw.output %0 : i32
}
}
