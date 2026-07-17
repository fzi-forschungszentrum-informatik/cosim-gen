// RUN: cosim-extract --path=/extracted --port=".*" --remove-sv %s -o - | FileCheck %s

// Test cosim-extract's --remove-sv option: sv dialect asserts/prints left in
// the extracted module must be stripped, since arcilator (the lowering tool
// used on this path) cannot handle them.

// Input is driven from top's own port and combined with another instance's
// output via comb.add (not passed straight through, and not an operator with
// an absorbing element like `and`/`or` - which HWOptInterfaces would fold
// away entirely, together with the "extracted" instance, before the path
// is even looked up) so the extracted output isn't already trivially wired
// to a top-level output port before extraction runs - see
// cosim-extract-partial.mlir for why that matters.
hw.module @top(in %clk : i1, in %in : i1, out result: i1) {
  %extracted.out = hw.instance "extracted" @ExtractedModule(clk: %clk: i1, in: %in: i1) -> (out: i1)
  %other.out = hw.instance "other" @OtherModule(in: %in: i1) -> (out: i1)
  %sum = comb.add %extracted.out, %other.out : i1
  hw.output %sum : i1
}

// CHECK-LABEL: hw.module @ExtractedModule
hw.module private @ExtractedModule(in %clk : i1, in %in : i1, out out: i1) {
  sv.always posedge %clk {
    // CHECK-NOT: sv.assert
    sv.assert %in, immediate
  }
  hw.output %in : i1
}

hw.module private @OtherModule(in %in : i1, out out: i1) {
  %0 = comb.sub %in, %in : i1
  hw.output %0 : i1
}
