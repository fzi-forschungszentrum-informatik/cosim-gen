// RUN: cosim-extract --path=/extracted --port=".*" --state-json=%t.json %s -o /dev/null
// RUN: FileCheck %s < %t.json

// Test cosim-extract's --state-json option: it should emit a JSON description
// of the extracted (now top-level) module's bit-level IO layout, matching the
// hw-state-json pass's format, so the tool can drive the same SystemC/QEMU
// wrapper generation the leon_vp Makefiles built around cosim-gen-opt
// --hw-state-json.

// Input is driven from top's own port and combined with another instance's
// output (not passed straight through) so the extracted output isn't already
// trivially wired to a top-level output port before extraction runs - see
// cosim-extract-partial.mlir for why that matters.
hw.module @top(in %in : i8, out result: i8) {
  %extracted.out = hw.instance "extracted" @ExtractedModule(in: %in: i8) -> (out: i8)
  %other.out = hw.instance "other" @OtherModule(in: %in: i8) -> (out: i8)
  %sum = comb.add %extracted.out, %other.out : i8
  hw.output %sum : i8
}

hw.module private @ExtractedModule(in %in : i8, out out: i8) {
  %0 = comb.add %in, %in : i8
  hw.output %0 : i8
}

hw.module private @OtherModule(in %in : i8, out out: i8) {
  %0 = comb.sub %in, %in : i8
  hw.output %0 : i8
}

// CHECK: "name": "ExtractedModule"
// CHECK: "states": [
// CHECK:   "name": "in"
// CHECK:   "offset": 0
// CHECK:   "numBits": 8
// CHECK:   "type": "input"
// CHECK:   "name": "out"
// CHECK:   "numBits": 8
// CHECK:   "type": "output"
