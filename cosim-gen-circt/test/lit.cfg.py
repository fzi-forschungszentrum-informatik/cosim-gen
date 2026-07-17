# -*- Python -*-

import os

import lit.formats
from lit.llvm import llvm_config

config.name = "COSIM_GEN"
config.test_format = lit.formats.ShTest(execute_external=False)
config.suffixes = [".mlir"]
config.test_source_root = os.path.dirname(__file__)
config.test_exec_root = os.path.join(config.cosim_gen_obj_root, "test")

config.substitutions.append(("%PATH%", config.environment["PATH"]))
config.substitutions.append(("%shlibext", config.llvm_shlib_ext))
config.substitutions.append(
    ("%cosim_gen_libs", config.cosim_gen_libs_dir))

llvm_config.with_system_environment(["HOME", "INCLUDE", "LIB", "TMP", "TEMP"])
llvm_config.use_default_substitutions()

config.excludes = ["Inputs", "CMakeLists.txt", "README.txt", "LICENSE.txt"]

tool_dirs = [
    config.cosim_gen_tools_dir,
    config.circt_tools_dir,
    config.llvm_tools_dir,
]
tools = [
    "cosim-gen-opt",
    "cosim-extract",
]
if config.cosim_gen_has_plugin:
  tools.append("circt-opt")

llvm_config.add_tool_substitutions(tools, tool_dirs)

if not config.cosim_gen_has_plugin:
  config.available_features.add("no-cosim-gen-plugin")
