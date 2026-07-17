"""cosim gen-config: derives a components[] list from a *.diplomacy.json,
scaffolding the rest of cosim.json when no output file exists yet."""

import json

from cosim.genconfig import gen_config

_DIPLOMACY = {
    "topDesign.uart": {
        "type": "MyUart",
        "labels": ["uart"],
        "signals": {
            "auto_clk_in_clock": {
                "dir": "BundleDefault", "type": "Clock", "config": {"Clock": {}},
            },
        },
    },
}


def test_gen_config_succeeds_on_fresh_output(tmp_path):
    """A freshly scaffolded cosim.json deliberately has a null freq_mhz (the
    user must fill it in - diplomacy has no notion of clock frequency) and an
    empty design.input/dts (gen-config only derives 'components', never the
    design's own input file) - neither gap should make gen_config report
    failure, since both are expected and reported via the printed notes."""
    diplomacy_path = tmp_path / "design.diplomacy.json"
    diplomacy_path.write_text(json.dumps(_DIPLOMACY))
    out = tmp_path / "cosim.json"

    rc = gen_config(diplomacy_path, out)

    assert rc == 0
    written = json.loads(out.read_text())
    assert written["design"]["input"] == ""
    assert written["components"][0]["interfaces"][0]["freq_mhz"] is None


def test_gen_config_reports_real_structural_bug(tmp_path):
    """A genuinely malformed classification (not one of the expected gaps
    above) must still be reported as a failure, not silently swallowed."""
    diplomacy_path = tmp_path / "design.diplomacy.json"
    diplomacy_path.write_text(json.dumps(_DIPLOMACY))
    out = tmp_path / "cosim.json"
    out.write_text(json.dumps({
        "design": {"input": "d.fir", "supported_backends": ["not-a-real-backend"]},
    }))

    rc = gen_config(diplomacy_path, out)

    assert rc == 1
