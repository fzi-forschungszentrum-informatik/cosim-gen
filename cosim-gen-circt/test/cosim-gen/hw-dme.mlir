// RUN: cosim-gen-opt --hw-dme %s | FileCheck %s

// Test hw-dme (dead module elimination) pass
// This pass removes unused modules from the design

// =============================================================================
// Test 1: Basic dead module elimination
// =============================================================================

// CHECK-LABEL: hw.module @top
hw.module @top(out y : i32) {
  %inst.y = hw.instance "sub" @used_module() -> (y: i32)
  hw.output %inst.y : i32
}

// CHECK-LABEL: hw.module @used_module
hw.module @used_module(out y : i32) {
  %0 = hw.constant 42 : i32
  hw.output %0 : i32
}

// CHECK-NOT: hw.module private @unused_module
hw.module private @unused_module(out y : i32) {
  %0 = hw.constant 0 : i32
  hw.output %0 : i32
}

// CHECK-NOT: hw.module private @also_unused
hw.module private @also_unused(out y : i32) {
  %0 = hw.constant 1 : i32
  hw.output %0 : i32
}

// =============================================================================
// Test 2: Comprehensive dead module elimination scenarios
// =============================================================================

// CHECK-LABEL: hw.module @liveTop
hw.module @liveTop(in %x : i32, out y : i32) {
  // This instance chain should keep modules alive
  %inst.y = hw.instance "sub" @liveSub(x: %x: i32) -> (y: i32)
  hw.output %inst.y : i32
}

// CHECK-LABEL: hw.module @liveSub
hw.module @liveSub(in %x : i32, out y : i32) {
  %0 = comb.add %x, %x : i32
  hw.output %0 : i32
}

// CHECK-NOT: hw.module private @deadModule
hw.module private @deadModule(in %x : i32, out y : i32) {
  // This module is never instantiated - should be removed
  %0 = comb.mul %x, %x : i32
  hw.output %0 : i32
}

// CHECK-NOT: hw.module private @deadChain
hw.module private @deadChain(in %x : i32, out y : i32) {
  // Chain of dead modules
  %inst.y = hw.instance "dead" @deadChild(x: %x: i32) -> (y: i32)
  hw.output %inst.y : i32
}

// CHECK-NOT: hw.module private @deadChild
hw.module private @deadChild(in %x : i32, out y : i32) {
  %0 = comb.sub %x, %x : i32
  hw.output %0 : i32
}

// CHECK-LABEL: hw.module @sharedModule
hw.module @sharedModule(in %x : i32, out y : i32) {
  // This module is used by multiple parents - should be kept
  %0 = comb.or %x, %x : i32
  hw.output %0 : i32
}

// CHECK-LABEL: hw.module @parentA
hw.module @parentA(in %x : i32, out y : i32) {
  %inst.y = hw.instance "shared" @sharedModule(x: %x: i32) -> (y: i32)
  hw.output %inst.y : i32
}

// CHECK-LABEL: hw.module @parentB
hw.module @parentB(in %x : i32, out y : i32) {
  %inst.y = hw.instance "shared" @sharedModule(x: %x: i32) -> (y: i32)
  hw.output %inst.y : i32
}

// CHECK-NOT: hw.module private @privateDead
hw.module private @privateDead(in %x : i32, out y : i32) {
  // Private module that's not used - should be removed
  %0 = comb.and %x, %x : i32
  hw.output %0 : i32
}

// CHECK-LABEL: hw.module.extern @external
// External module should be kept (extern modules are never eliminated)
// Extern modules have no body - they are external declarations
hw.module.extern @external(in %x : i32, out y : i32)
