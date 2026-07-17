// RUN: cosim-gen-opt --hw-keep-ports="ports=TestMod=keep_in|keep_out;SecondMod=second_keep_out;InputOnlyMod=keep_input;MultiKeepMod=in_a|in_b|out_x|out_y" %s | FileCheck %s

// Test hw-keep-ports pass
// This pass tags ports matching a regex pattern to be kept during optimization
// Format: ports=moduleName=portRegex

// =============================================================================
// Test 1: Module with 2 inputs and 3 outputs
// This tests that argNum is correctly converted to absolute port index
// Inputs: argNum 0-1 map to absolute 0-1
// Outputs: argNum 0-2 map to absolute 2-4
// =============================================================================

// CHECK-LABEL: hw.module @TestMod
// CHECK-SAME: in %keep_in : i32 {keep}
// CHECK-SAME: in %remove_in : i32
// CHECK-SAME: out keep_out : i32 {keep}
// CHECK-SAME: out remove_out1 : i32
// CHECK-SAME: out remove_out2 : i32
hw.module @TestMod(in %keep_in : i32, in %remove_in : i32, out keep_out : i32, out remove_out1 : i32, out remove_out2 : i32) {
  %0 = comb.add %keep_in, %remove_in : i32
  hw.output %0, %0, %0 : i32, i32, i32
}

// =============================================================================
// Test 2: Module with 3 inputs and 2 outputs
// This tests output argNum 1 (second output) maps to absolute index 4
// Inputs: argNum 0-2 map to absolute 0-2
// Outputs: argNum 0-1 map to absolute 3-4
// =============================================================================

// CHECK-LABEL: hw.module @SecondMod
// CHECK-SAME: in %a : i32
// CHECK-SAME: in %b : i32
// CHECK-SAME: in %c : i32
// CHECK-SAME: out second_keep_out : i32 {keep}
// CHECK-SAME: out normal_out : i32
hw.module @SecondMod(in %a : i32, in %b : i32, in %c : i32, out second_keep_out : i32, out normal_out : i32) {
  %0 = comb.add %a, %b : i32
  %1 = comb.add %0, %c : i32
  hw.output %1, %1 : i32, i32
}

// =============================================================================
// Test 3: Module with 1 input and 1 output
// Tests basic single port keep
// =============================================================================

// CHECK-LABEL: hw.module @InputOnlyMod
// CHECK-SAME: in %keep_input : i32 {keep}
// CHECK-SAME: in %normal_input : i32
// CHECK-SAME: out result : i32
hw.module @InputOnlyMod(in %keep_input : i32, in %normal_input : i32, out result : i32) {
  %0 = comb.add %keep_input, %normal_input : i32
  hw.output %0 : i32
}

// =============================================================================
// Test 4: Module with multiple inputs and outputs to keep
// Tests regex matching multiple ports
// =============================================================================

// CHECK-LABEL: hw.module @MultiKeepMod
// CHECK-SAME: in %in_a : i32 {keep}
// CHECK-SAME: in %in_b : i32 {keep}
// CHECK-SAME: in %in_c : i32
// CHECK-SAME: out out_x : i32 {keep}
// CHECK-SAME: out out_y : i32 {keep}
// CHECK-SAME: out out_z : i32
hw.module @MultiKeepMod(in %in_a : i32, in %in_b : i32, in %in_c : i32, out out_x : i32, out out_y : i32, out out_z : i32) {
  %0 = comb.add %in_a, %in_b : i32
  %1 = comb.add %0, %in_c : i32
  hw.output %1, %1, %1 : i32, i32, i32
}
