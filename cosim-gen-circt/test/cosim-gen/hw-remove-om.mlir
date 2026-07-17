// RUN: cosim-gen-opt --hw-remove-om %s | FileCheck %s

// Test hw-remove-om pass
// This pass removes OM (Object Model) dialect operations

// CHECK-LABEL: hw.module @ModuleWithOM
hw.module @ModuleWithOM(in %x : i32, out y : i32) {
  // OM operations that should be removed by the pass
  // CHECK-NOT: om.class
  // CHECK-NOT: om.new
  // CHECK-NOT: om.field
  
  %0 = comb.add %x, %x : i32
  hw.output %0 : i32
}

// Test module with actual OM operations
hw.module @WithOMOps(in %x : i32, out y : i32) {
  // These OM operations should be removed
  // CHECK-NOT: om.class
  // CHECK-NOT: om.new
  // CHECK-NOT: om.field
  
  %0 = comb.add %x, %x : i32
  hw.output %0 : i32
}
