"""project.py: the extra_files basename-collision guard, the generated Makefiles and the
crash handling of coupled runs. No build deps."""

import json
import subprocess

import pytest

from cosim import project
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


@pytest.fixture
def fake_run(tmp_path, monkeypatch):
    """Runs `_run_coupled` with sh scripts standing in for QEMU and the one sim."""
    monkeypatch.setattr(project, "_SIM_SHUTDOWN_GRACE_S", 0.3)
    real_popen = subprocess.Popen

    def run(qemu_sh, sim_sh, *, wait_for_qemu=False):
        def popen(cmd, **kw):
            if "run-qemu-coupled" in cmd:
                machine_path = next(a.split("=", 1)[1] for a in cmd if a.startswith("MACHINE_PATH="))
                log = tmp_path / "build" / "run.log"
                log.parent.mkdir(exist_ok=True)
                with log.open("w") as output:
                    p = real_popen(["sh", "-c", f"echo $$ > {machine_path}/qemu.pid; {qemu_sh}"],
                                   cwd=tmp_path, stdout=output, stderr=subprocess.STDOUT)
                if wait_for_qemu:
                    p.wait(timeout=5)
                return p
            return real_popen(["sh", "-c", sim_sh], cwd=tmp_path, **kw)
        monkeypatch.setattr(project.subprocess, "Popen", popen)
        cfg = _cfg(tmp_path)
        return project._run_coupled(cfg, {"qemu": "qemu"}, tmp_path / "build", tmp_path / "x.dtb",
                                    ["u"], "verilator")
    return run


def test_sim_crash_stops_qemu(fake_run):
    with pytest.raises(RuntimeError, match="crashed:\n\nu "):
        fake_run("exec sleep 30", "sleep 0.3; exit 3")


def test_sim_stopping_cleanly_is_no_crash(fake_run):
    assert fake_run("sleep 0.6", "sleep 0.3; exit 0") == 0


def test_sim_failing_as_qemu_exits_is_no_crash(fake_run):
    assert fake_run("touch qemu-stopped; sleep 0.2",
                    "while [ ! -e qemu-stopped ]; do sleep 0.01; done; exit 1") == 0


@pytest.mark.parametrize("wait_for_qemu", [False, True])
def test_sim_crash_causing_successful_qemu_exit_reported(fake_run, wait_for_qemu):
    with pytest.raises(RuntimeError, match="crashed:\n\nu "):
        fake_run("while [ ! -e sim-failed ]; do sleep 0.01; done; echo 'rp: Disconnected clk=0 ns'",
                 "sleep 0.3; touch sim-failed; exit 3", wait_for_qemu=wait_for_qemu)


def test_clean_sim_disconnect_is_no_crash(fake_run):
    assert fake_run("while [ ! -e sim-done ]; do sleep 0.01; done; echo 'rp: Disconnected clk=0 ns'",
                    "sleep 0.3; touch sim-done; exit 0") == 0


def test_sim_failing_at_startup_reported(fake_run):
    with pytest.raises(RuntimeError, match="crashed:\n\nu "):
        fake_run("exec sleep 30", "exit 3")
