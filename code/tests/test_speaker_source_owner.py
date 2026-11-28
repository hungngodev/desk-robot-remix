"""Selected speaker has both mechanical and digital audio source owners.

This source contract is not device playback or acoustic calibration evidence.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_speaker_source_register_tracks_real_sense_i2s_and_fit_owners():
    register = json.loads(
        (ROOT / "docs/hardware/full-63-role-source-ownership.json").read_text()
    )
    speaker = register["pet_roles"]["speaker"]
    assert speaker["source"] == "docs/cad/remixes/speaker_rect_fit_gauge.scad"
    assert speaker["source_state"] == "speaker_fit_reference_only"
    assert (ROOT / speaker["source"]).is_file()
    assert (ROOT / speaker["host_test"]).is_file()

    secondary = speaker["secondary_implementation"]
    assert secondary["purpose"] == (
        "Sense digital I2S speaker output and resampling source"
    )
    assert secondary["source"] == (
        "code/firmware/head/sense/sense_reference_codec.cc"
    )
    assert secondary["host_test"] == "code/firmware/head/tests/test_sense.py"
    assert secondary["physical_qualification_guide"] == (
        "docs/guides/audio-barge-in.md"
    )
    assert secondary["physical_qualification_completed"] is False

    codec = (ROOT / secondary["source"]).read_text()
    tests = (ROOT / secondary["host_test"]).read_text()
    assert "NoAudioCodecSimplexPdm" in codec
    assert "kSpeakerRate" in codec
    assert "sense_reference_codec.cc" in tests
    assert (ROOT / secondary["physical_qualification_guide"]).is_file()
    assert "acoustic" in speaker["remaining_qualification"]
