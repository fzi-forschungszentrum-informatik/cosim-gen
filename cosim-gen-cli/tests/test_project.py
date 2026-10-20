"""project.py's pure-config helpers: the extra_files basename-collision guard and the
generated Makefiles. No build deps - pure Python."""

import json

import pytest

from cosim.config import Config, _reject_basename_collisions
from cosim.project import (
    _render_qemu_makefile,
    _render_unit_makefile,
    _unit_spec,
)

CLOCK = {"kind": "clock", "name": "clock", "freq_mhz": 100}
RESET = {"kind": "reset", "name": "reset"}


def _cfg(tmp_path, **extra):
    cosim_json = {
        "design": {"input": "d.fir", "supported_backends": ["arcilator"]},
        "components": [{"type": "U", "path": "top/u", "interfaces": [CLOCK],
                        "trace": True, "cxxflags": ["-DX=$1"], "user_sim_cpp": True}],
        **extra,
    }
    p = tmp_path / "cosim.json"
    p.write_text(json.dumps(cosim_json))
    return Config.load(p)


def test_unit_makefile_merges_component_over_top_level(tmp_path):
    cfg = _cfg(tmp_path, max_cycles=7, trace=False, ldlibs=["-lfoo"])
    mk = _render_unit_makefile(_unit_spec(cfg, cfg.components[0], False, tmp_path))
    assert "MAX_CYCLES := 7\n" in mk
    assert "TRACE := 1\n" in mk
    assert "EXTRA_CXXFLAGS := -DX=$$1\n" in mk
    assert "EXTRA_LDLIBS := -lfoo\n" in mk
    assert "GENERATE_SIM_CPP := 0\n" in mk


def test_qemu_makefile_from_cosim_json(tmp_path):
    cfg = _cfg(tmp_path, sync_quantum=50, qemu={"elfs": ["a.elf"], "extra_args": ["-d", "int"]})
    mk = _render_qemu_makefile(cfg)
    assert f"ELFS := {tmp_path}/a.elf\n" in mk
    assert "QEMU_EXTRA_ARGS := -d int\n" in mk
    assert "SYNC_QUANTUM := 50\n" in mk


def test_qemu_sync_quantum_overrides_top_level(tmp_path):
    cfg = _cfg(tmp_path, sync_quantum=50, qemu={"sync_quantum": 7})
    assert "SYNC_QUANTUM := 7\n" in _render_qemu_makefile(cfg)


def test_extra_vsrcs_in_unit_makefile(tmp_path):
    cfg = _cfg(tmp_path, design={"input": "d.fir", "extra_vsrcs": ["ext.sv"]})
    mk = _render_unit_makefile(_unit_spec(cfg, cfg.components[0], False, tmp_path))
    assert f"EXTRA_VSRCS := {tmp_path}/ext.sv\n" in mk


def test_basename_collision_rejected(tmp_path):
    a = tmp_path / "a" / "bootrom.mem"
    a.parent.mkdir()
    a.write_text("one")
    b = tmp_path / "b" / "bootrom.mem"
    b.parent.mkdir()
    b.write_text("two")
    with pytest.raises(ValueError) as exc_info:
        _reject_basename_collisions([a, b], "extra_files")
    assert "bootrom.mem" in str(exc_info.value)


def test_same_file_listed_twice_is_fine(tmp_path):
    f = tmp_path / "bootrom.mem"
    f.write_text("one")
    _reject_basename_collisions([f, f], "extra_files")


def test_no_collision_is_fine(tmp_path):
    a = tmp_path / "a.mem"
    b = tmp_path / "b.mem"
    a.write_text("one")
    b.write_text("two")
    _reject_basename_collisions([a, b], "extra_files")


def _unit_mk(tmp_path, **component_extra):
    cfg = _cfg(tmp_path, components=[{"type": "U", "path": "top/u", "interfaces": [CLOCK, RESET],
                                      **component_extra}])
    return _render_unit_makefile(_unit_spec(cfg, cfg.components[0], False, tmp_path / "build"))


def test_extra_srcs_in_unit_makefile(tmp_path):
    mk = _unit_mk(tmp_path, extra_srcs=["models/wire.cpp", "/abs/periph.cpp"])
    assert f"EXTRA_SRCS := {tmp_path}/models/wire.cpp /abs/periph.cpp\n" in mk


def test_extra_srcs_must_be_cpp(tmp_path):
    with pytest.raises(ValueError, match="must be a .cpp file"):
        _unit_mk(tmp_path, extra_srcs=["periph.cc"])


@pytest.mark.parametrize("src", ["sim.cpp", "u.cpp", "gen-arc-u.cpp"])
def test_extra_srcs_builtin_object_collision_rejected(tmp_path, src):
    with pytest.raises(ValueError, match="collides with the built-in"):
        _unit_mk(tmp_path, extra_srcs=[src])


def test_extra_srcs_basename_collision_rejected(tmp_path):
    with pytest.raises(ValueError, match="share the basename"):
        _unit_mk(tmp_path, extra_srcs=["a/wire.cpp", "b/wire.cpp"])
