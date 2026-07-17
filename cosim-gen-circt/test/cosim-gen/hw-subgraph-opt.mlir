// RUN: cosim-gen-opt --hw-subgraph=path=/b0/c %s | FileCheck %s

// CHECK-NOT: hw.module @SimpleA
hw.module @SimpleA(in %x : i4, out y : i4) {
  %b0.y = hw.instance "b0" @SimpleB(x: %x: i4) -> (y: i4)
  %b1.y = hw.instance "b1" @SimpleB(x: %b0.y: i4) -> (y: i4)
  hw.output %b1.y : i4
}

// CHECK-NOT: hw.module private @SimpleB
hw.module private @SimpleB(in %x : i4, out y : i4) {
  %c.y0, %c.y1 = hw.instance "c" @SimpleC(x: %x: i4) -> (y0: i4, y1: i4)
  hw.output %c.y0 : i4
}

// CHECK-LABEL: hw.module @SimpleC
hw.module private @SimpleC(in %x : i4, out y0 : i4, out y1 : i4) {
  %0 = comb.add %x, %x : i4
  %1 = comb.add %0, %0 : i4
  %d.EO = hw.instance "d" @SimpleD(EI: %1: i4) -> (EO: i4)
  %2 = comb.add %d.EO, %d.EO : i4
  hw.output %d.EO, %2 : i4, i4
}

// CHECK-LABEL: hw.module private @SimpleD
hw.module private @SimpleD(in %EI : i4, out EO : i4) {
  %0 = comb.add %EI, %EI : i4
  %1 = comb.mul %0, %EI : i4
  hw.output %1 : i4
}