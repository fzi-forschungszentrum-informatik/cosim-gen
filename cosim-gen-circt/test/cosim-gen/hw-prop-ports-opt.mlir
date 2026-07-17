// RUN: cosim-gen-opt --hw-subgraph=path=/b0/c0 %s | FileCheck %s

// Test hw-subgraph pass with port propagation
// This pass extracts a subgraph and propagates ports appropriately

// CHECK-NOT: hw.module @SimpleA
hw.module @SimpleA(in %x : i4, out y : i4) {
  %0 = comb.add %x, %x : i4
  %b0.y = hw.instance "b0" @SimpleB(x: %0: i4) -> (y: i4)
  %1 = comb.add %b0.y, %0 : i4
  %b1.y = hw.instance "b1" @SimpleB(x: %1: i4) -> (y: i4)
  %2 = comb.add %b1.y, %0 : i4
  hw.output %2 : i4
}

// CHECK-NOT: hw.module private @SimpleB
hw.module private @SimpleB(in %x : i4, out y : i4) {
  %c0.y0, %c0.y1 = hw.instance "c0" @SimpleC(x: %x: i4) -> (y0: i4, y1: i4)
  %1 = comb.add %c0.y0, %c0.y1 : i4
  %c1.y0, %c1.y1 = hw.instance "c1" @SimpleC(x: %1: i4) -> (y0: i4, y1: i4)
  %2 = comb.add %c1.y0, %c1.y1 : i4
  hw.output %2 : i4
}

// CHECK-LABEL: hw.module @SimpleC
// The extracted module should have proper port propagation
hw.module private @SimpleC(in %x : i4, out y0 : i4, out y1 : i4) {
  %0 = comb.add %x, %x : i4
  // After port propagation, UNUSED port is removed from @SimpleD
  %d.EO, %d.KO = hw.instance "d" @SimpleD(EI: %0: i4, KI: %x : i4) -> (EO: i4, KO: i4)
  %e.o0, %e.o1 = hw.instance "e" @SimpleE(i0: %0: i4, i1: %x : i4) -> (o0: i4, o1: i4)
  %1 = comb.add %d.EO, %d.KO : i4
  %c1_i4 = hw.constant 1 : i4
  %2 = comb.add %e.o0, %d.KO : i4
  hw.output %d.EO, %2 : i4, i4
}

// CHECK-LABEL: hw.module private @SimpleD
// After port propagation, the UNUSED port should be removed
hw.module private @SimpleD(in %EI : i4, in %KI : i4, out EO : i4, out KO : i4) {
  %0 = comb.add %EI, %KI : i4
  %1 = comb.mul %0, %EI : i4
  hw.output %0, %1: i4, i4
}

// CHECK-LABEL: hw.module private @SimpleE
hw.module private @SimpleE(in %i0 : i4, in %i1 : i4, out o0 : i4, out o1 : i4) {
  %d.EO, %d.KO = hw.instance "d" @SimpleD(EI: %i0: i4, KI: %i1 : i4) -> (EO: i4, KO: i4)
  hw.output %d.EO, %d.KO : i4, i4
}

