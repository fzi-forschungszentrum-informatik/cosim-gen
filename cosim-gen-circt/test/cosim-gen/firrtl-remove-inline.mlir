// RUN: cosim-gen-opt --firrtl-remove-inline %s | FileCheck %s

// Test firrtl-remove-inline pass
// This pass removes inline annotations from FIRRTL modules

// CHECK: firrtl.circuit
// FIRRTL circuit requires a module with the same name as the circuit
firrtl.circuit "top" {
// CHECK-LABEL: firrtl.module @top
// Module with inline annotation - should be removed
firrtl.module @top(in %x: !firrtl.uint<32>, out %y: !firrtl.uint<32>)
  attributes {annotations = [{class = "firrtl.transforms.InlineAnnotation"}]} {
  %0 = firrtl.wire : !firrtl.uint<32>
  firrtl.connect %0, %x : !firrtl.uint<32>
  firrtl.connect %y, %0 : !firrtl.uint<32>
}

// CHECK-LABEL: firrtl.module @withInline
// Module with inline annotation - should be removed
firrtl.module @withInline(in %x: !firrtl.uint<8>, out %y: !firrtl.uint<8>)
  attributes {annotations = [{class = "firrtl.transforms.InlineAnnotation"}]} {
  %0 = firrtl.wire : !firrtl.uint<8>
  firrtl.connect %0, %x : !firrtl.uint<8>
  firrtl.connect %y, %0 : !firrtl.uint<8>
}

// CHECK-LABEL: firrtl.module @noInline  
// Module without inline annotation - should remain unchanged
firrtl.module @noInline(in %x: !firrtl.uint<16>, out %y: !firrtl.uint<16>) {
  %0 = firrtl.wire : !firrtl.uint<16>
  firrtl.connect %0, %x : !firrtl.uint<16>
  firrtl.connect %y, %0 : !firrtl.uint<16>
}

// CHECK-LABEL: firrtl.module @nested
// Nested module with inline annotation - should be removed
firrtl.module @nested(in %a: !firrtl.uint<4>, in %b: !firrtl.uint<4>, out %y: !firrtl.uint<4>)
  attributes {annotations = [{class = "firrtl.transforms.InlineAnnotation"}]} {
  %0 = firrtl.wire : !firrtl.uint<4>
  firrtl.connect %0, %a : !firrtl.uint<4>
  firrtl.connect %y, %0 : !firrtl.uint<4>
}
}
