// RUN: cosim-gen-opt --firrtl-keep-interfaces=mod=KeepThis,AlsoKeep %s | FileCheck %s

// Test firrtl-keep-interfaces pass
// This pass keeps interfaces for specified modules

// FIRRTL circuit requires a module with the same name as the circuit
firrtl.circuit "KeepThis" {
// CHECK-LABEL: firrtl.module @KeepThis
// The module should have the DontTouchAnnotation marker on ports
// CHECK: {class = "firrtl.transforms.DontTouchAnnotation"}
firrtl.module @KeepThis(in %x: !firrtl.uint<32>, out %y: !firrtl.uint<32>) {
  // This module's interfaces should be kept
  %0 = firrtl.wire : !firrtl.uint<32>
  firrtl.connect %0, %x : !firrtl.uint<32>, !firrtl.uint<32>
  firrtl.connect %y, %0 : !firrtl.uint<32>, !firrtl.uint<32>
}

// CHECK-LABEL: firrtl.module @OtherModule
// This module should not have the keep interface marker
firrtl.module @OtherModule(in %x: !firrtl.uint<32>, out %y: !firrtl.uint<32>) {
  %0 = firrtl.wire : !firrtl.uint<32>
  firrtl.connect %0, %x : !firrtl.uint<32>, !firrtl.uint<32>
  firrtl.connect %y, %0 : !firrtl.uint<32>, !firrtl.uint<32>
}

// CHECK-LABEL: firrtl.module @AlsoKeep
// CHECK: {class = "firrtl.transforms.DontTouchAnnotation"}
firrtl.module @AlsoKeep(in %a: !firrtl.uint<8>, in %b: !firrtl.uint<8>, out %y: !firrtl.uint<8>) {
  // Another module to keep
  %0 = firrtl.wire : !firrtl.uint<8>
  firrtl.connect %0, %a : !firrtl.uint<8>, !firrtl.uint<8>
  firrtl.connect %y, %0 : !firrtl.uint<8>, !firrtl.uint<8>
}

// CHECK-LABEL: firrtl.module @NoKeep
// No keep interface marker expected
firrtl.module @NoKeep(in %x: !firrtl.uint<16>, out %y: !firrtl.uint<16>) {
  // This module should not be marked
  %0 = firrtl.wire : !firrtl.uint<16>
  firrtl.connect %0, %x : !firrtl.uint<16>, !firrtl.uint<16>
  firrtl.connect %y, %0 : !firrtl.uint<16>, !firrtl.uint<16>
}
}
