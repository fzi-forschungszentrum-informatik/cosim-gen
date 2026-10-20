"""Negative tests for cosim.json's 'interfaces' schema (cosim/config.py,
cosim/interfaces/). No build deps - pure Python dict -> Component.load(),
plus one full Config.load() round-trip through a real file."""

import json

import pytest

from cosim.codegen.typedio import build_typedIO
from cosim.config import Component, Config, DesignConfig, ToolchainConfig
from cosim.statejson import StateInfo, StateType
from cosim.toolchain import _TOOL_SPECS


def load(d, **kw):
    return Component.load(None, d, **kw)


def err(d, **kw):
    with pytest.raises(ValueError) as exc_info:
        load(d, **kw)
    return str(exc_info.value)


BASE = {"type": "X", "path": "p"}


def component(*interfaces, **extra):
    return {**BASE, "interfaces": list(interfaces), **extra}


CLOCK = {"kind": "clock", "name": "clock", "freq_mhz": 100}
RESET = {"kind": "reset", "name": "reset"}
BUS = {"kind": "tilelink", "prefix": "auto_control_xing_in", "dir": "slave"}
IRQ = {"kind": "interrupt", "name": "auto_int_xing_out_sync_0", "dir": "out"}
GPIO = {"kind": "gpio", "prefix": "auto_io_out_pins"}
UNCONNECTED = {"kind": "unconnected", "name": "sideband"}


# --- a valid config loads, as a control -------------------------------------

def test_valid_component_loads():
    c = load(component(CLOCK, RESET, BUS, IRQ, GPIO))
    assert c.clock.name == "clock"
    assert c.reset.name == "reset"
    assert len(c.interfaces) == 5
    assert c.io_regex == (
        "clock$|reset$|auto_control_xing_in.*$|"
        "auto_int_xing_out_sync_0$|auto_io_out_pins.*$"
    )


def test_valid_soc_rtl_loads():
    c = load({"interfaces": [CLOCK, RESET]}, require_type_path=False)
    assert c.clock.name == "clock"
    assert c.type is None


# --- component 'name': derived from path, not type -------------------------------

def test_name_defaults_to_paths_last_segment():
    c = load(component(CLOCK, path="topDesign/topMod/uartClockDomainWrapper/uart_0"))
    assert c.name == "uart_0"
    assert c.top_name == "uart_0_TOP"


def test_name_falls_back_to_type_with_no_slash_in_path():
    c = load(component(CLOCK, path="p"))
    assert c.name == "p"


def test_name_can_be_overridden_explicitly():
    c = load(component(CLOCK, path="topDesign/topMod/uart_0", name="my_uart"))
    assert c.name == "my_uart"


def test_soc_rtl_has_no_name():
    c = load({"interfaces": [CLOCK, RESET]}, require_type_path=False)
    assert c.name is None


# --- interfaces list shape ---------------------------------------------------

def test_missing_interfaces_key():
    msg = err(BASE)
    assert "'interfaces'" in msg


def test_interfaces_not_a_list():
    # Wrong type entirely (not just a malformed value of the right type), so
    # this raises TypeError
    with pytest.raises(TypeError) as exc_info:
        load({**BASE, "interfaces": {"kind": "clock", "name": "clock"}})
    assert "must be a list" in str(exc_info.value)


def terr(d, **kw):
    # Like err(), but for the interface-loading checks that raise TypeError
    # (wrong shape entirely) rather than ValueError (right shape, bad value).
    with pytest.raises(TypeError) as exc_info:
        load(d, **kw)
    return str(exc_info.value)


def test_interface_entry_not_an_object():
    msg = terr(component("not-a-dict"))
    assert "must be an object" in msg


def test_interface_entry_missing_kind():
    msg = terr(component({"name": "clock"}))
    assert "'kind'" in msg


def test_unknown_kind_rejected():
    msg = terr(component({"kind": "nope", "name": "x"}, RESET))
    assert "unknown interface kind 'nope'" in msg
    assert "tilelink" in msg  # the known-kinds list


def test_bare_bus_kind_rejected():
    msg = err(component(CLOCK, {"kind": "bus", "prefix": "p", "dir": "slave"}))
    assert "'bus' isn't a kind on its own" in msg
    assert "tilelink" in msg


def test_unknown_key_on_interface_rejected():
    msg = err(component({"kind": "clock", "name": "clock", "protocol": "oops"}))
    assert "unknown key(s)" in msg
    assert "protocol" in msg


# --- clock cardinality --------------------------------------------------------

def test_zero_clocks_rejected():
    msg = err(component(RESET))
    assert "at least one 'clock' interface" in msg
    assert "found none" in msg


def test_multiple_clocks_allowed():
    # Multiple clock domains are supported - each just needs its own
    # freq_mhz; the first declared is the anchor (c.clock).
    c = load(component(
        {"kind": "clock", "name": "c1", "freq_mhz": 100},
        {"kind": "clock", "name": "c2", "freq_mhz": 200},
    ))
    assert c.clock.name == "c1"
    assert [i.name for i in c.interfaces if i.KIND == "clock"] == ["c1", "c2"]


def test_clock_with_prefix_rejected():
    # 'prefix' isn't a known clock key at all (a clock is a single exact
    # port, declared via 'name') - caught as an unknown key before it would
    # ever reach a prefix-vs-name-specific message.
    msg = err(component({"kind": "clock", "prefix": "c"}))
    assert "unknown key(s)" in msg
    assert "'prefix'" in msg


def test_clock_freq_mhz_must_be_int():
    msg = terr(component({"kind": "clock", "name": "clock", "freq_mhz": "150"}))
    assert "freq_mhz must be an integer" in msg


def test_clock_missing_freq_mhz_rejected():
    # No project-wide rtl.freq_mhz fallback anymore - every clock must
    # declare its own.
    msg = err(component({"kind": "clock", "name": "clock"}))
    assert "missing required 'freq_mhz'" in msg


# --- reset cardinality ---------------------------------------------------------

def test_multiple_resets_allowed():
    # Multiple reset domains are supported, same as multiple clocks - the
    # first declared is the anchor (c.reset).
    c = load(component(CLOCK, {"kind": "reset", "name": "r1"}, {"kind": "reset", "name": "r2"}))
    assert c.reset.name == "r1"
    assert [i.name for i in c.interfaces if i.KIND == "reset"] == ["r1", "r2"]


def test_no_reset_is_fine():
    c = load(component(CLOCK))
    assert c.reset is None


def test_bus_without_reset_rejected():
    msg = err(component(CLOCK, BUS))
    assert "no 'reset' interface" in msg


def test_interrupt_without_reset_rejected():
    msg = err(component(CLOCK, IRQ))
    assert "no 'reset' interface" in msg


def test_bus_with_reset_is_fine():
    c = load(component(CLOCK, RESET, BUS))
    assert c.reset is not None


# --- bus interface -------------------------------------------------------------

def test_bus_with_name_rejected():
    msg = err(component(CLOCK, {"kind": "tilelink", "name": "bad", "dir": "slave"}))
    assert "uses 'name'" in msg
    assert "'prefix'" in msg


def test_bus_bad_dir_rejected():
    msg = err(component(CLOCK, {"kind": "tilelink", "prefix": "p", "dir": "weird"}))
    assert "dir must be 'slave' or 'master'" in msg


def test_bus_missing_prefix_rejected():
    msg = err(component(CLOCK, {"kind": "tilelink", "dir": "slave"}))
    assert "missing required field 'prefix'" in msg


def test_bus_carrying_compat_rejected():
    msg = err(component(CLOCK, {"kind": "tilelink", "prefix": "p", "dir": "slave", "compat": "x,y"}))
    assert "compat/path/interrupts" in msg


# --- interrupt / gpio prefix-xor-name -------------------------------------------

@pytest.mark.parametrize("kind", ["interrupt", "gpio"])
def test_wire_needs_exactly_one_of_prefix_or_name(kind):
    msg = err(component(CLOCK, {"kind": kind, "name": "n", "prefix": "p"}))
    assert "exactly one of 'prefix' or 'name'" in msg

    msg = err(component(CLOCK, {"kind": kind}))
    assert "exactly one of 'prefix' or 'name'" in msg


def test_interrupt_bad_dir_rejected():
    msg = err(component(CLOCK, {"kind": "interrupt", "name": "n", "dir": "sideways"}))
    assert "dir must be 'out' or 'in'" in msg


def test_interrupt_dir_defaults_to_out():
    c = load(component(CLOCK, RESET, {"kind": "interrupt", "name": "n"}))
    irq = c.interfaces[-1]
    assert irq.dir == "out"


# --- soc_rtl restrictions --------------------------------------------------------

@pytest.mark.parametrize("bad", [BUS, IRQ, GPIO])
def test_soc_rtl_rejects_non_clock_reset_kinds(bad):
    msg = err({"interfaces": [CLOCK, bad]}, require_type_path=False)
    assert "soc_rtl interface of kind" in msg
    assert "no QEMU bus/interrupt coupling path" in msg


def test_soc_rtl_rejects_compat():
    msg = err({"interfaces": [CLOCK], "compat": "sifive,uart0"}, require_type_path=False)
    assert "soc_rtl.compat" in msg


# --- io_regex ordering: kind order, not declaration order -----------------------

def test_io_regex_is_ordered_by_kind_not_declaration():
    # gpio and the bus both declared before clock/reset - the regex must still
    # come out clock, reset, bus, interrupt, gpio (Interface.ORDER), so a
    # prefix-matching gpio/interrupt can never shadow a bus's own leaf ports
    # depending on write order in cosim.json.
    c = load(component(GPIO, BUS, IRQ, RESET, CLOCK))
    assert c.io_regex == (
        "clock$|reset$|auto_control_xing_in.*$|"
        "auto_int_xing_out_sync_0$|auto_io_out_pins.*$"
    )


def _ports(*names):
    return [StateInfo(n, 0, 1, StateType.INPUT, None, None) for n in names]


def test_unconnected_port_stays_a_passthrough():
    c = load(component(CLOCK, RESET, UNCONNECTED))
    assert c.io_regex == "clock$|reset$|sideband$"
    assert [s.name for s in build_typedIO(c, _ports("clock", "reset", "sideband")).other] == ["sideband"]


def test_unconnected_missing_port_rejected():
    c = load(component(CLOCK, UNCONNECTED))
    with pytest.raises(ValueError, match="'sideband' not found"):
        build_typedIO(c, _ports("clock"))


# --- full Config.load() round-trip through a real file ---------------------------

def test_full_config_round_trip(tmp_path):
    cosim_json = {
        "design": {"input": "design.fir", "supported_backends": ["arcilator"]},
        "components": [component(CLOCK, RESET, BUS, IRQ)],
    }
    p = tmp_path / "cosim.json"
    p.write_text(json.dumps(cosim_json))
    cfg = Config.load(p)
    assert len(cfg.components) == 1
    assert cfg.components[0].type == "X"
    assert cfg.components[0].clock.name == "clock"
    assert cfg.design.supported_backends == ["arcilator"]


def test_full_config_rejects_colliding_component_names(tmp_path):
    # Two different types, but the same path basename - both would default to
    # the same 'name', so both would collide on build/components/<name>/,
    # `cosim run <name>`, etc. Must fail loudly at load time instead of one
    # silently shadowing the other.
    cosim_json = {
        "design": {"input": "design.fir", "supported_backends": ["arcilator"]},
        "components": [
            {**component(CLOCK, RESET, BUS, IRQ), "type": "A", "path": "topMod/uart_0"},
            {**component(CLOCK, RESET, BUS, IRQ), "type": "B", "path": "otherMod/uart_0"},
        ],
    }
    p = tmp_path / "cosim.json"
    p.write_text(json.dumps(cosim_json))
    with pytest.raises(ValueError) as exc_info:
        Config.load(p)
    assert "component name(s) collide" in str(exc_info.value)
    assert "uart_0" in str(exc_info.value)


def test_full_config_with_legacy_shape_fails_with_pointer(tmp_path):
    cosim_json = {
        "design": {"input": "design.fir", "supported_backends": ["arcilator"]},
        "components": [{
            "type": "X", "path": "p",
            "clock": {"name": "clock"}, "reset": {"name": "reset"},
        }],
    }
    p = tmp_path / "cosim.json"
    p.write_text(json.dumps(cosim_json))
    with pytest.raises(ValueError) as exc_info:
        Config.load(p)
    assert "interfaces" in str(exc_info.value)


def test_design_input_empty_string_rejected():
    with pytest.raises(ValueError) as exc_info:
        DesignConfig.load(None, {"input": "", "supported_backends": ["arcilator"]})
    assert "design.input must be a non-empty path" in str(exc_info.value)


# --- design.supported_backends ---------------------------------------------------

def test_supported_backends_default_to_verilator(tmp_path):
    d = DesignConfig.load(tmp_path, {"input": "d.fir"})
    assert d.supported_backends == ["verilator"]


@pytest.mark.parametrize("backends", [
    [], "arcilator", ["arcilator", "questasim"], ["arcilator", "arcilator"],
])
def test_supported_backends_rejected(backends):
    with pytest.raises(ValueError) as exc_info:
        DesignConfig.load(None, {"input": "d.fir", "supported_backends": backends})
    assert "design.supported_backends must be a non-empty list" in str(exc_info.value)


def test_supported_backends_valid(tmp_path):
    d = DesignConfig.load(tmp_path, {"input": "d.fir", "supported_backends": ["arcilator", "verilator"]})
    assert d.supported_backends == ["arcilator", "verilator"]


def test_extra_vsrcs_must_be_a_list(tmp_path):
    with pytest.raises(TypeError, match="extra_vsrcs must be a list"):
        DesignConfig.load(tmp_path, {"input": "d.fir", "extra_vsrcs": "ext.sv"})


def test_extra_vsrcs_rejected_with_arcilator():
    with pytest.raises(ValueError, match="extra_vsrcs isn't supported with the arcilator"):
        DesignConfig.load(None, {"input": "d.fir", "supported_backends": ["arcilator", "verilator"],
                                 "extra_vsrcs": ["ext.sv"]})


# --- top-level build/run defaults (jobs/sync_quantum/max_cycles/extra_args) -------

def test_top_level_defaults(tmp_path):
    cosim_json = {
        "design": {"input": "design.fir", "supported_backends": ["arcilator"]},
        "jobs": "4",
        "sync_quantum": 5000,
        "max_cycles": 100,
        "extra_args": ["+foo=1"],
        "trace": True,
        "cxxflags": ["-DFOO"],
        "verilator_args": ["--threads", "2"],
    }
    p = tmp_path / "cosim.json"
    p.write_text(json.dumps(cosim_json))
    cfg = Config.load(p)
    assert cfg.jobs == "4"
    assert cfg.sync_quantum == 5000
    assert cfg.max_cycles == 100
    assert cfg.extra_args == ["+foo=1"]
    assert cfg.trace is True
    assert cfg.cxxflags == ["-DFOO"]
    assert cfg.verilator_args == ["--threads", "2"]


def test_top_level_defaults_fall_back(tmp_path):
    cosim_json = {"design": {"input": "design.fir", "supported_backends": ["arcilator"]}}
    p = tmp_path / "cosim.json"
    p.write_text(json.dumps(cosim_json))
    cfg = Config.load(p)
    assert cfg.jobs is None
    assert cfg.sync_quantum == 1000
    assert cfg.max_cycles == 0
    assert cfg.extra_args == []
    assert cfg.trace is False
    assert cfg.ldlibs == []


def test_unit_options_inherit_unless_set():
    c = load(component(CLOCK, coverage=True, arcilator_args=["--x"], user_sim_cpp=True))
    assert c.coverage is True
    assert c.arcilator_args == ["--x"]
    assert c.trace is None
    assert c.user_sim_cpp is True


@pytest.mark.parametrize("key, value", [
    ("trace", "yes"), ("user_sim_cpp", 1), ("cxxflags", "-O2"),
    ("sync_quantum", "x"), ("max_cycles", 1.5), ("extra_srcs", "a.cpp"),
])
def test_unit_option_type_rejected(key, value):
    with pytest.raises(TypeError) as exc_info:
        load(component(CLOCK, **{key: value}))
    assert key in str(exc_info.value)


# --- toolchain ---------------------------------------------------------------

def test_every_tool_spec_has_a_toolchain_field():
    """Every tool toolchain.py knows how to resolve must be settable via
    toolchain.<name> in cosim.json, or ResolvedToolchain.require()'s "set
    toolchain.<name>" advice is false for that tool."""
    known = {f.name for f in ToolchainConfig.__dataclass_fields__.values()}
    missing = set(_TOOL_SPECS) - known
    assert not missing, f"_TOOL_SPECS has tool(s) with no matching ToolchainConfig field: {missing}"


def test_toolchain_accepts_every_tool_spec_key():
    d = {name: "/some/path" for name in _TOOL_SPECS}
    cfg = ToolchainConfig.load(d)
    for name in _TOOL_SPECS:
        assert getattr(cfg, name) == "/some/path"


# --- top-level cosim.json shape validation ---------------------------------------

def test_unknown_top_level_key_rejected(tmp_path):
    # A typo like "component" (for "components") must fail loudly, not be
    # silently ignored.
    cosim_json = {
        "design": {"input": "design.fir", "supported_backends": ["arcilator"]},
        "component": [],
    }
    p = tmp_path / "cosim.json"
    p.write_text(json.dumps(cosim_json))
    with pytest.raises(ValueError) as exc_info:
        Config.load(p)
    assert "unknown top-level key(s)" in str(exc_info.value)
    assert "'component'" in str(exc_info.value)


def test_non_object_top_level_rejected(tmp_path):
    p = tmp_path / "cosim.json"
    p.write_text(json.dumps(["not", "an", "object"]))
    with pytest.raises(TypeError) as exc_info:
        Config.load(p)
    assert "top level must be a JSON object" in str(exc_info.value)


def test_non_dict_design_section_rejected(tmp_path):
    p = tmp_path / "cosim.json"
    p.write_text(json.dumps({"design": "oops"}))
    with pytest.raises(TypeError) as exc_info:
        Config.load(p)
    assert "design must be an object" in str(exc_info.value)


def test_components_not_a_list_rejected(tmp_path):
    p = tmp_path / "cosim.json"
    p.write_text(json.dumps({
        "design": {"input": "d.fir", "supported_backends": ["arcilator"]},
        "components": {"type": "X"},
    }))
    with pytest.raises(TypeError) as exc_info:
        Config.load(p)
    assert "components must be a list" in str(exc_info.value)


def test_soc_rtl_not_an_object_rejected(tmp_path):
    p = tmp_path / "cosim.json"
    p.write_text(json.dumps({
        "design": {"input": "d.fir", "supported_backends": ["arcilator"]},
        "soc_rtl": [],
    }))
    with pytest.raises(TypeError) as exc_info:
        Config.load(p)
    assert "soc_rtl must be an object" in str(exc_info.value)
