"""Locations of the non-python parts of the cosim engine (mk/, include/,
third_party/) relative to this repo checkout."""

from pathlib import Path

# cosim-gen-cli/cosim/paths.py -> cosim-gen-cli/
PACKAGE_ROOT = Path(__file__).resolve().parent
COSIM_ROOT = PACKAGE_ROOT.parent

MK_DIR = COSIM_ROOT / "mk"
INCLUDE_DIR = COSIM_ROOT / "include"
THIRD_PARTY_DIR = COSIM_ROOT / "third_party"
LIBSYSTEMCTLM_SOC_DIR = THIRD_PARTY_DIR / "libsystemctlm-soc"
