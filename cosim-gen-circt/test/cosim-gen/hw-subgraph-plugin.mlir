// RUN: circt-opt %s --load-dialect-plugin=%cosim_gen_libs/CosimGenPlugin%shlibext --pass-pipeline="builtin.module(hw-subgraph{path=/b0/c})" | FileCheck %s

// CHECK-NOT: hw.module @SimpleA
hw.module @SimpleA(in %x: i4, out y: i4) {
  %0 = hw.instance "b0" @SimpleB(x: %x: i4) -> (y: i4)
  %1 = hw.instance "b1" @SimpleB(x: %0: i4) -> (y: i4)
  hw.output %1 : i4
}

// CHECK-NOT: hw.module private @SimpleB
hw.module private @SimpleB(in %x: i4, out y: i4) {
  %0 = hw.instance "c" @SimpleC(x: %x: i4) -> (y: i4)
  hw.output %0 : i4
}

// CHECK-LABEL: hw.module @SimpleC
hw.module private @SimpleC(in %x: i4, out y: i4) {
  %0 = hw.instance "d" @SimpleD(x: %x: i4) -> (y: i4)
  hw.output %0 : i4
}

// CHECK-LABEL: hw.module private @SimpleD
hw.module private @SimpleD(in %x: i4, out y: i4) {
  %0 = comb.add %x, %x : i4
  %1 = comb.mul %0, %x : i4
  hw.output %1 : i4
}