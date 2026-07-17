// RUN: cosim-gen-opt --hw-taint=path=/sub %s | FileCheck %s

// Test hw-taint pass
// This pass removes untainted ports from modules not connected to the specified subdesign

// The hw-taint pass removes untainted ports but does NOT eliminate entire modules.
// Module elimination should be done with hw-dme pass after hw-taint.

// CHECK-LABEL: hw.module @top
hw.module @top(in %x : i32, out y : i32) {
  %inst.y = hw.instance "sub" @connected_module(x: %x: i32) -> (y: i32)
  hw.output %inst.y : i32
}

// CHECK-LABEL: hw.module @connected_module
hw.module @connected_module(in %x : i32, out y : i32) {
  %0 = comb.add %x, %x : i32
  hw.output %0 : i32
}

// Note: unconnected_module is NOT removed by hw-taint pass
// The pass only removes untainted ports within modules
// Use hw-dme after hw-taint to remove entire unused modules
hw.module @unconnected_module(in %x : i32, out y : i32) {
  %0 = comb.mul %x, %x : i32
  hw.output %0 : i32
}
