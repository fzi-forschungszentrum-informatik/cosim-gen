"""project.py's pure-config helpers: the extra_files basename-collision guard and the
generated Makefiles. No build deps - pure Python."""

import json

import pytest

from cosim.config import Config
from cosim.project import (
    _reject_basename_collisions,
    _render_qemu_makefile,
    _render_unit_makefile,
    _unit_spec,
)

CLOCK = {"kind": "clock", "name": "clock", "freq_mhz": 100}


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


def test_basename_collision_rejected(tmp_path):
    a = tmp_path / "a" / "bootrom.mem"
    a.parent.mkdir()
    a.write_text("one")
    b = tmp_path / "b" / "bootrom.mem"
    b.parent.mkdir()
    b.write_text("two")
    with pytest.raises(RuntimeError) as exc_info:
        _reject_basename_collisions([a, b])
    assert "bootrom.mem" in str(exc_info.value)


def test_same_file_listed_twice_is_fine(tmp_path):
    f = tmp_path / "bootrom.mem"
    f.write_text("one")
    _reject_basename_collisions([f, f])


def test_no_collision_is_fine(tmp_path):
    a = tmp_path / "a.mem"
    b = tmp_path / "b.mem"
    a.write_text("one")
    b.write_text("two")
    _reject_basename_collisions([a, b])
