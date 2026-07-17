// RUN: cosim-gen-opt --hw-move-comb-up="path=/child" %s | FileCheck %s

// Test hw-move-comb-up pass
// This pass moves combinational logic up into the parent module

// CHECK-LABEL: hw.module @parent
hw.module @parent(in %x : i32, out y : i32) {
  %child.y = hw.instance "child" @child(x: %x: i32) -> (y: i32)
  hw.output %child.y : i32
}

// CHECK-LABEL: hw.module @child
hw.module @child(in %x : i32, out y : i32) {
  %0 = comb.add %x, %x : i32
  hw.output %0 : i32
}
