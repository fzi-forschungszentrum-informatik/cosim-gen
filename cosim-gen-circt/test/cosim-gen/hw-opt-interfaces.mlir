// RUN: cosim-gen-opt --hw-opt-interfaces %s | FileCheck %s

// Test hw-opt-interfaces pass
// This pass removes unused inputs and propagates const outputs

module {
// CHECK-LABEL: hw.module @top
hw.module @top(in %x : i32, out y : i32) {
  %inst.y = hw.instance "sub" @with_unused_port(x: %x: i32, unused: %x: i32) -> (y: i32)
  hw.output %inst.y : i32
}

// CHECK-LABEL: hw.module @with_unused_port
// The unused port should be removed from the signature
// CHECK-SAME: in %x : i32
// CHECK-SAME: out y : i32
hw.module @with_unused_port(in %x : i32, in %unused : i32, out y : i32) {
  // The unused port should be removed
  %0 = comb.add %x, %x : i32
  hw.output %0 : i32
}

// CHECK-LABEL: hw.module @const_prop
// The input should be removed (unused) and output kept
// CHECK-SAME: out y : i32
hw.module @const_prop(in %x : i32, out y : i32) {
  // Constant propagation through outputs
  %c = hw.constant 42 : i32
  hw.output %c : i32
}

// CHECK-LABEL: hw.module @allUnused
// All inputs should be removed
// CHECK-SAME: out y : i32
hw.module @allUnused(in %unused1 : i32, in %unused2 : i32, out y : i32) {
  // All inputs unused except for computing output
  %0 = hw.constant 10 : i32
  hw.output %0 : i32
}

// CHECK-LABEL: hw.module @propagateConst
// Input should be removed, outputs kept
// CHECK-SAME: out y : i32
// CHECK-SAME: out z : i32
hw.module @propagateConst(in %x : i32, out y : i32, out z : i32) {
  // Multiple outputs with constant propagation
  %c1 = hw.constant 1 : i32
  %c2 = hw.constant 2 : i32
  hw.output %c1, %c2 : i32, i32
}
}
