//===- Passes.td - Cosim gen passes ------------------------*- tablegen -*-===//
//
// This file is licensed under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#ifndef COSIM_GEN_PASS
#define COSIM_GEN_PASS

include "mlir/Pass/PassBase.td"

def HWSubGraph : Pass<"hw-subgraph", "::mlir::ModuleOp"> {
  let summary = "Select a subgraph based on a instance path";
  let dependentDialects = ["circt::hw::HWDialect"];
  let options = [
    Option<"path", "path", "std::string", "",
     "Select a new top module by an instance path">
  ];
}

def HWTaint : Pass<"hw-taint", "::mlir::ModuleOp"> {
  let summary = "Delete parts not connected to subdesign";
  let dependentDialects = ["circt::hw::HWDialect"];
  let options = [
    Option<"path", "path", "std::string", "",
     "Select a module to taint">
  ];
  let statistics = [
    Statistic<"tainted_ops", "tainted-ops", "Number of tainted ops">,
    Statistic<"untainted_ops", "untainted-ops", "Number of untainted ops">,
    Statistic<"untainted_inputs", "untainted-inputs", "Number of untainted inputs">,
    Statistic<"untainted_outputs", "untainted-outputs", "Number of untainted outputs">,
  ];
}

def HWMarkComb : Pass<"hw-mark-comb", "::mlir::ModuleOp"> {
  let summary = "Delete parts not connected to subdesign";
  let dependentDialects = ["circt::hw::HWDialect"];
  let options = [
    Option<"path", "path", "std::string", "",
     "Select a new top module by an instance path">,
    Option<"strRegex", "port", "std::string", "\"*\"",
     "Regex of ports that need to be checked.">,
  ];
  let statistics = [
    Statistic<"markcombed_ops", "markcombed-ops", "Number of markcombed ops">,
    Statistic<"unmarkcombed_ops", "unmarkcombed-ops", "Number of unmarkcombed ops">,
    Statistic<"unmarkcombed_inputs", "unmarkcombed-inputs", "Number of unmarkcombed inputs">,
    Statistic<"unmarkcombed_outputs", "unmarkcombed-outputs", "Number of unmarkcombed outputs">,
  ];
}

def HWPropPorts2TLM : Pass<"hw-prop-ports-to-tlm", "::mlir::ModuleOp"> {
  let summary = "Propagate ports to tlm";
  let dependentDialects = ["circt::hw::HWDialect"];
  let options = [
    Option<"strPath", "path", "std::string", "",
     "Select a new top module by an instance path">,
    Option<"strRegex", "port", "std::string", "\"*\"",
     "Regex of ports that need to be rewired to the top module.">,
    Option<"replaceInstOuts", "replaceInstOuts", "bool", "true",
     "Replace the old outputs of the inst with constant values.">,
    Option<"keepTopPorts", "keepTopPorts", "bool", "false",
     "Keep ports if they are connected to the top module.">
  ];
  let statistics = [
    Statistic<"no_input", "input-ports", "Number of input port redirected">,
    Statistic<"no_output", "output-ports", "Number of output port redirected">,
    Statistic<"no_modules", "modules-changed", "Number of modules with changed interfaces">,
    Statistic<"no_insts", "inst-changed", "Number of instances with changed">,
  ];
}

def HWDme : Pass<"hw-dme", "::mlir::ModuleOp"> {
  let summary = "HW dead code elimation";
  let dependentDialects = ["circt::hw::HWDialect"];
}

//def HWRemoveSV : Pass<"hw-remove-sv", "hw::HWModuleOp"> {
def HWRemoveSV : Pass<"hw-remove-sv", "::mlir::ModuleOp"> {
  let summary = "Remove sv asserts and prints";
  let dependentDialects = ["circt::hw::HWDialect"];
}

def HWRemoveOM : Pass<"hw-remove-om", "::mlir::ModuleOp"> {
  let summary = "Remove om";
  let dependentDialects = ["circt::hw::HWDialect"];
}

def HWRemoveCustomAttr : Pass<"hw-remove-custom-attr", "hw::HWModuleOp"> {
  let summary = "Remove custom attributes";
  let dependentDialects = ["circt::hw::HWDialect"];
}

def HWInlineTrivial : Pass<"hw-inline-trivial", "::mlir::ModuleOp"> {
  let summary = "Inline modules with no logic";
  let dependentDialects = ["circt::hw::HWDialect"];
  let statistics = [
    Statistic<"inline_module", "inline-modules", "Number of inlined modules">,
  ];
}

def HWKeepPorts : Pass<"hw-keep-ports", "::mlir::ModuleOp"> {
  let summary = "Tag ports to be kept";
  let dependentDialects = ["circt::hw::HWDialect"];
  let options = [
    Option<"strRegex", "ports", "std::string", "", "Ports to keep">
  ];
}

def HWKeepPath : Pass<"hw-keep-path", "::mlir::ModuleOp"> {
  let summary = "Tag the modules along an instance path with module-level keep";
  let dependentDialects = ["circt::hw::HWDialect"];
  let options = [
    Option<"path", "path", "std::string", "",
     "Instance path whose module chain is protected from folding/inlining">
  ];
}

def HWReleaseKeep : Pass<"hw-release-keep", "::mlir::ModuleOp"> {
  let summary = "Drop the module-level keep tag from the modules along an instance path";
  let dependentDialects = ["circt::hw::HWDialect"];
  let options = [
    Option<"path", "path", "std::string", "",
     "Instance path whose module chain's keep tag is released">
  ];
}

def HWOptInterfaces : Pass<"hw-opt-interfaces", "::mlir::ModuleOp"> {
  let summary = "Remove unused inputs and propagate const outputs";
  let dependentDialects = ["circt::hw::HWDialect"];
  let options = [
    Option<"keepPorts", "keepPorts", "bool", "false",
     "Keep unused ports.">
  ];
  
  let statistics = [
    Statistic<"no_unused_ports", "unsed-ports-removed", "Number of removed unused ports">,
    Statistic<"no_rewired", "rewired-ports-removed", "Number of removed propagated ports">,
    Statistic<"no_modules", "modules-changed", "Number of modules with changed interfaces">,
    Statistic<"no_insts", "inst-changed", "Number of instances with changed">,
    Statistic<"no_del_ops", "unsed-ops", "Number of unsed ops">,
    Statistic<"no_del_modules", "unsed-modules", "Number of unsed modules">,
  ];
}


def HWMoveCombUp : Pass<"hw-move-comb-up", "::mlir::ModuleOp"> {
  let summary = "Remove unused inputs and propagate const outputs";
  let dependentDialects = ["circt::hw::HWDialect"];
  let options = [
    Option<"path", "path", "std::string", "",
     "Select a instance to move comb into">
  ];
}

def HWStateJson : Pass<"hw-state-json", "::mlir::ModuleOp"> {
  let summary = "HW state json file";
  let dependentDialects = ["circt::hw::HWDialect"];
  let options = [
    Option<"strPath", "path", "std::string", "", "Output path">
  ];
}

def HWMakefile : Pass<"hw-makefile", "::mlir::ModuleOp"> {
  let summary = "Create a metadata makefile";
  let dependentDialects = ["circt::hw::HWDialect"];
  let options = [
    Option<"strPath", "path", "std::string", "", "Output path">
  ];
}

def HWRenameTop : Pass<"hw-rename-top", "::mlir::ModuleOp"> {
  let summary = "Rename the top module";
  let dependentDialects = ["circt::hw::HWDialect"];
  let options = [
    Option<"name", "name", "std::string", "", "New top name">
  ];
}

//def FIRRTLKeepInterfaces : Pass<"firrtl-keep-interfaces", "firrtl::FModuleOp"> {
def FIRRTLKeepInterfaces : Pass<"firrtl-keep-interfaces", "mlir::ModuleOp"> {
  let summary = "FIRRTL keep interfaces for given modules";
  let dependentDialects = ["circt::firrtl::FIRRTLDialect"];
  let options = [
    Option<"strModules", "mod", "std::string", "",
     "Select a module to chipletify">
  ];
}

def FIRRTLRemoveInline : Pass<"firrtl-remove-inline", "mlir::ModuleOp"> {
  let summary = "Remove module inline attributes";
  let dependentDialects = ["circt::firrtl::FIRRTLDialect"];
}

#endif // COSIM_GEN_PASS
