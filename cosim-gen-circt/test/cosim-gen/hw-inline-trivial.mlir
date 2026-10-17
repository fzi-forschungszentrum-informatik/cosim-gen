// RUN: cosim-gen-opt --split-input-file --hw-inline-trivial %s | FileCheck %s

// CHECK-LABEL: hw.module @top
// CHECK-NOT: hw.instance
// CHECK: hw.output %x : i32

// CHECK-LABEL: hw.module private @nonTrivial
// CHECK-NOT: hw.module @trivial

hw.module @top(in %x : i32, out y : i32) {
  %inst.y = hw.instance "trivial" @trivial(a: %x: i32) -> (y: i32)
  hw.output %inst.y : i32
}

hw.module private @nonTrivial(in %a : i32, out y : i32) {
  %0 = comb.add %a, %a : i32
  hw.output %0 : i32
}

hw.module private @trivial(in %a : i32, out y : i32) {
  hw.output %a : i32
}

module {
// @topWithTrivial inlines @trivialForward, resulting in direct forwarding
// CHECK-LABEL: hw.module @topWithTrivial
// CHECK: hw.output %x : i32
hw.module @topWithTrivial(in %x : i32, out y : i32) {
  hw.output %x : i32
}

// @trivialForward is inlined and removed (was private)
// CHECK-NOT: hw.module @trivialForward
hw.module private @trivialForward(in %a : i32, out y : i32) {
  hw.output %a : i32
}

// @multiInputTrivial inlines @multiTrivial
// CHECK-LABEL: hw.module @multiInputTrivial
// CHECK: hw.output %a, %b : i32, i32
hw.module @multiInputTrivial(in %a : i32, in %b : i32, out x : i32, out y : i32) {
  hw.output %a, %b : i32, i32
}

// @multiTrivial is inlined and removed (was private)
// CHECK-NOT: hw.module @multiTrivial
hw.module private @multiTrivial(in %a : i32, in %b : i32, out x : i32, out y : i32) {
  hw.output %a, %b : i32, i32
}

// @reorderTrivial inlines @reorderPorts  
// CHECK-LABEL: hw.module @reorderTrivial
// CHECK: hw.output %b, %a : i32, i32
hw.module @reorderTrivial(in %a : i32, in %b : i32, out x : i32, out y : i32) {
  hw.output %b, %a : i32, i32
}

// @reorderPorts is inlined and removed (was private)
// CHECK-NOT: hw.module @reorderPorts
hw.module private @reorderPorts(in %a : i32, in %b : i32, out x : i32, out y : i32) {
  hw.output %b, %a : i32, i32
}

// @chainOfTrivial - all chained trivial modules inlined
// CHECK-LABEL: hw.module @chainOfTrivial
// CHECK: hw.output %x : i32
hw.module @chainOfTrivial(in %x : i32, out y : i32) {
  hw.output %x : i32
}

// @constModule has logic - should NOT be inlined, becomes non-private
// CHECK-LABEL: hw.module @constModule
// CHECK: hw.constant 42
hw.module @constModule(in %x : i32, out y : i32) {
  %c42_i32 = hw.constant 42 : i32
  %0 = comb.add %x, %c42_i32 : i32
  hw.output %0 : i32
}

// @nonTrivialLogic has actual logic - should NOT be inlined, becomes non-private
// CHECK-LABEL: hw.module @nonTrivialLogic
// CHECK: comb.add
hw.module @nonTrivialLogic(in %x : i32, out y : i32) {
  %0 = comb.add %x, %x : i32
  hw.output %0 : i32
}
}

hw.module private @innerSymLeaf(in %a : i1, out b : i1) {
  %w = hw.wire %a sym @w : i1
  hw.output %w : i1
}

// CHECK-LABEL: hw.module @innerSymTop
// CHECK-DAG: hw.wire %a sym @{{[a-z_0-9]+}} name "u0/w"
// CHECK-DAG: hw.wire %a sym @{{[a-z_0-9]+}} name "u1/w"
hw.module @innerSymTop(in %a : i1, out x : i1, out y : i1) {
  %0 = hw.instance "u0" @innerSymLeaf(a: %a : i1) -> (b: i1)
  %1 = hw.instance "u1" @innerSymLeaf(a: %a : i1) -> (b: i1)
  hw.output %0, %1 : i1, i1
}

// CHECK-LABEL: hw.module @publicWrapper
// CHECK: hw.instance "c" @sharedChild
hw.module @publicWrapper(in %a : i1, out b : i1) {
  %0 = hw.instance "c" @sharedChild(a: %a: i1) -> (b: i1)
  hw.output %0 : i1
}

hw.module @otherUser(in %a : i1, out b : i1) {
  %0 = hw.instance "c" @sharedChild(a: %a: i1) -> (b: i1)
  %1 = comb.xor %0, %a : i1
  hw.output %1 : i1
}

// CHECK-LABEL: hw.module private @sharedChild
hw.module private @sharedChild(in %a : i1, out b : i1) {
  %0 = comb.and %a, %a : i1
  hw.output %0 : i1
}

emit.fragment @fragParent {
}
emit.fragment @fragChild {
}

// CHECK-LABEL: hw.module @fragmentTop
// CHECK-SAME: emit.fragments = [@fragChild, @fragParent]
hw.module @fragmentTop(in %a : i1, out b : i1) attributes {emit.fragments = [@fragParent]} {
  %0 = hw.instance "c" @fragmentChild(a: %a: i1) -> (b: i1)
  %1 = comb.xor %0, %a : i1
  hw.output %1 : i1
}

hw.module private @fragmentChild(in %a : i1, out b : i1) attributes {emit.fragments = [@fragChild]} {
  hw.output %a : i1
}

// -----

hw.module private @fieldSymbols(in %a: !hw.struct<x: i1, y: i1>, out b: !hw.struct<x: i1, y: i1>) {
  %0 = hw.wire %a sym [<@field,1,private>] : !hw.struct<x: i1, y: i1>
  %1 = hw.wire %0 sym [<@whole,0,private>, <@part,2,nested>] : !hw.struct<x: i1, y: i1>
  hw.output %1 : !hw.struct<x: i1, y: i1>
}

// CHECK-LABEL: hw.module @fieldSymbolTop
// CHECK: hw.wire %{{.*}} sym [<@field_0,1,private>]
// CHECK: hw.wire %{{.*}} sym [<@whole_0,0,private>, <@part_0,2,nested>]
hw.module @fieldSymbolTop(in %a: !hw.struct<x: i1, y: i1>, out b: !hw.struct<x: i1, y: i1>) {
  %0 = hw.wire %a sym [<@whole,0,public>, <@field,1,public>, <@part,2,public>] : !hw.struct<x: i1, y: i1>
  %1 = hw.instance "u" @fieldSymbols(a: %0: !hw.struct<x: i1, y: i1>) -> (b: !hw.struct<x: i1, y: i1>)
  hw.output %1 : !hw.struct<x: i1, y: i1>
}

// -----

hw.module @wrapper(in %a: !hw.struct<x: i1>, out b: !hw.struct<x: i1>) {
  %0 = hw.instance "u" @referencedChild(a: %a: !hw.struct<x: i1>) -> (b: !hw.struct<x: i1>)
  hw.output %0 : !hw.struct<x: i1>
}

// CHECK-LABEL: hw.module @referencedChild
// CHECK: hw.wire %a sym [<@whole,0,private>, <@field,1,nested>]
// CHECK: symbols = [#hw.innerNameRef<@referencedChild::@whole>, #hw.innerNameRef<@referencedChild::@field>]
hw.module private @referencedChild(in %a: !hw.struct<x: i1>, out b: !hw.struct<x: i1>) {
  %0 = hw.wire %a sym [<@whole,0,private>, <@field,1,nested>] : !hw.struct<x: i1>
  sv.verbatim "// {{0}} {{1}}" {symbols = [#hw.innerNameRef<@referencedChild::@whole>, #hw.innerNameRef<@referencedChild::@field>]}
  hw.output %0 : !hw.struct<x: i1>
}
