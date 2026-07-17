// RUN: not cosim-extract --path=/does_not_exist --port=".*out.*" %s 2>&1 | FileCheck %s

// Error test: an unresolvable --path must produce a clean diagnostic and a
// non-zero exit, NOT crash. (Streaming an llvm::Error via operator<< without
// consuming it used to leak the error, so its destructor called
// fatalUncheckedError() and abort()ed with SIGABRT - printing the message a
// second time - instead of exiting cleanly. The leading "not" in the run
// line asserts the non-zero exit; the diagnostic below asserts the message.)

// The diagnostic names the bad path and lists the valid instance paths so
// the user can correct the typo.
// CHECK: Module path not found in design: /does_not_exist
// CHECK: Valid paths are:
// CHECK: /extracted

hw.module @top(in %in : i8, out result: i8) {
  %extracted.out = hw.instance "extracted" @ExtractedModule(in: %in: i8) -> (out: i8)
  hw.output %extracted.out : i8
}

hw.module private @ExtractedModule(in %in : i8, out out: i8) {
  %0 = comb.mul %in, %in : i8
  hw.output %0 : i8
}
