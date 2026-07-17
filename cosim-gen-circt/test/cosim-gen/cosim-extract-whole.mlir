// RUN: cosim-extract --state-json=%t.json --remove-sv %s -o - | FileCheck %s
// RUN: FileCheck --check-prefix=JSON %s < %t.json

// Test cosim-extract with no --path: this is how the whole, un-extracted
// design is built (a IS_COMPONENT=0 component in component.mk has no --path to
// extract by, so cosim-extract runs only its shared cleanup pipeline - see
// buildWholePipeline in cosim-extract.cpp) instead of the extraction
// pipeline. --state-json/--remove-sv still apply with no --path.

// CHECK-LABEL: hw.module @top
// CHECK-NOT: sv.assert
hw.module @top(in %clk : i1, in %in : i8, out result: i8) {
  %c0_i8 = hw.constant 0 : i8
  %nonzero = comb.icmp ne %in, %c0_i8 : i8
  sv.always posedge %clk {
    sv.assert %nonzero, immediate
  }
  %0 = comb.mul %in, %in : i8
  hw.output %0 : i8
}

// JSON: "name": "top"
// JSON: "name": "clk"
// JSON: "name": "in"
// JSON: "name": "result"
