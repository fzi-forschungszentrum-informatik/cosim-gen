"""Resolve the external tool paths cosim needs: config value > environment
variable > well-known default install location > $PATH."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .config import ToolchainConfig

COSIM_GEN_BUILD_DIR = paths.COSIM_ROOT.parent / "cosim-gen-circt" / "build"
QEMU_BUILD_DIR = paths.COSIM_ROOT.parent / "qemu-fdt" / "build"

# name -> (env var, default candidate paths, alternative $PATH executable name)
_TOOL_SPECS: dict[str, tuple[str, list[Path], str]] = {
    "firtool": ("FIRTOOL", [], ""),
    "arcilator": ("ARCILATOR", [], ""),
    "opt": ("OPT", [], ""),
    "llc": ("LLC", [], ""),
    "cosim_extract": (
        "EXTRACT",
        [COSIM_GEN_BUILD_DIR / "bin" / "cosim-extract"],
        "",
    ),
    "cosim_gen_opt": (
        "COSIM_GEN_OPT",
        [COSIM_GEN_BUILD_DIR / "bin" / "cosim-gen-opt"],
        "",
    ),
    "cosim_plugin": (
        "COSIM_PLUGIN",
        [COSIM_GEN_BUILD_DIR / "lib" / "CosimGenPlugin.so"],
        "",
    ),
    "verilator": ("VERILATOR", [], ""),
    "dtc": ("DTC", [], ""),
    "qemu": (
        "QEMU",
        [QEMU_BUILD_DIR / "qemu-system-riscv64"],
        "qemu-system-riscv64",
    ),
}

_ENV_VAR_FOR: dict[str, str] = {
    **{name: spec[0] for name, spec in _TOOL_SPECS.items()},
    "systemc_include": "SYSTEMC_INCLUDE",
    "systemc_lib": "SYSTEMC_LIB",
}


def _resolve_one(
    name: str,
    cfg_value: str | None,
    env_var: str,
    defaults: list[Path],
    alt_name: str = "",
) -> Path | None:
    if cfg_value:
        p = Path(cfg_value).expanduser()
        return p if p.exists() else None
    if env_var and os.environ.get(env_var):
        p = Path(os.environ[env_var]).expanduser()
        return p if p.exists() else None
    for candidate in defaults:
        if candidate.exists():
            return candidate
    found = shutil.which(alt_name or name.replace("_", "-"))
    return Path(found) if found else None


def _resolve_dir(
    cfg_value: str | None, env_vars: list[str], defaults: list[Path]
) -> Path | None:
    """Like _resolve_one, but for a directory (no $PATH executable lookup) and
    checked against more than one candidate env var (e.g. COSIM_SYSTEMC and the
    conventional SYSTEMC_HOME)."""
    if cfg_value:
        p = Path(cfg_value).expanduser()
        return p if p.exists() else None
    for env_var in env_vars:
        if os.environ.get(env_var):
            p = Path(os.environ[env_var]).expanduser()
            return p if p.exists() else None
    for candidate in defaults:
        if candidate.exists():
            return candidate
    return None


def _pkg_config_systemc() -> tuple[Path | None, Path | None]:
    """Ask pkg-config for systemc's include/lib dirs, if a systemc.pc is
    installed on this system. Returns (include_dir, lib_dir), either/both None
    if pkg-config itself or a systemc module isn't found."""
    if shutil.which("pkg-config") is None:
        return None, None

    def _flag_paths(flag: str, prefix: str, extra_args: str = '') -> Path | None:
        try:
            out = subprocess.run(
                ["pkg-config", flag, extra_args, "systemc"],
                check=True, capture_output=True, text=True,
            )
        except (subprocess.CalledProcessError, OSError):
            return None
        for tok in out.stdout.split():
            if tok.startswith(prefix):
                return Path(tok[len(prefix):])
        return None

    return (
        _flag_paths("--cflags", "-I", "--keep-system-cflags"),
        _flag_paths("--libs", "-L", "--keep-system-libs"),
    )


@dataclass
class ResolvedToolchain:
    tools: dict[str, Path | None]

    def __getitem__(self, name: str) -> Path | None:
        return self.tools[name]

    def require(self, name: str) -> Path:
        p = self.tools.get(name)
        if p is None:
            env_var = _ENV_VAR_FOR.get(name, name.upper())
            raise RuntimeError(
                f"cosim: required tool '{name}' was not found. "
                f"Set toolchain.{name} in cosim.json, the {env_var} env var, "
                f"or install it on $PATH."
            )
        return p

    def missing(self) -> list[str]:
        return [name for name, p in self.tools.items() if p is None]


def resolve(cfg: ToolchainConfig) -> ResolvedToolchain:
    tools: dict[str, Path | None] = {}
    for name, (env_var, defaults, which_name) in _TOOL_SPECS.items():
        cfg_value = getattr(cfg, name, None)
        tools[name] = _resolve_one(name, cfg_value, env_var, defaults, which_name)

    pkg_include, pkg_lib = _pkg_config_systemc()
    prefix = _resolve_dir(cfg.systemc, ["COSIM_SYSTEMC", "SYSTEMC_HOME"], [])
    include_defaults = ([pkg_include] if pkg_include else []) + (
        [prefix / "include"] if prefix else []
    )
    lib_defaults = ([pkg_lib] if pkg_lib else []) + (
        [prefix / "lib"] if prefix else []
    )
    tools["systemc_include"] = _resolve_dir(
        cfg.systemc_include, ["SYSTEMC_INCLUDE"], include_defaults
    )
    tools["systemc_lib"] = _resolve_dir(
        cfg.systemc_lib, ["SYSTEMC_LIB"], lib_defaults
    )

    return ResolvedToolchain(tools=tools)


def doctor_report(cfg: ToolchainConfig) -> str:
    resolved = resolve(cfg)
    lines = ["cosim doctor: toolchain resolution"]
    for name, path in resolved.tools.items():
        status = str(path) if path else "NOT FOUND"
        lines.append(f"  {name:<15} {status}")
    missing = resolved.missing()
    if missing:
        lines.append("")
        lines.append(f"Missing: {', '.join(missing)}")
        lines.append(
            "Set the corresponding toolchain.<name> in cosim.json, an env var, or install on $PATH."
        )
    else:
        lines.append("")
        lines.append("All tools found.")
    return "\n".join(lines)
