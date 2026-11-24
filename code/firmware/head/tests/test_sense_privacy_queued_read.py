"""Source regression for a PDM reader queued across a BOOT privacy change.

Physical microphone and network silence still require the assembled head trial.
"""

from pathlib import Path

CODEC = Path(__file__).resolve().parents[1] / "sense" / "sense_reference_codec.cc"


def _read():
    return CODEC.read_text().split("int SenseReferenceCodec::Read(", 1)[1].split(
        "int SenseReferenceCodec::Write(", 1
    )[0]


def test_queued_pdm_read_rechecks_consent_after_acquiring_reader_mutex():
    read = _read()
    after_lock = read.split("input_lock(input_read_mutex_);", 1)[1]
    before_pdm = after_lock.split("NoAudioCodecSimplexPdm::Read(", 1)[0]
    assert "if (microphone_privacy_muted_.load(std::memory_order_acquire) ||" in before_pdm
    assert "privacy_epoch != microphone_privacy_epoch_.load(" in before_pdm
    assert "return 0;" in before_pdm


def test_partial_pdm_read_erases_private_scratch_before_return():
    read = _read()
    failed = read.split("if (mic_read != frames) {", 1)[1].split("}", 1)[0]
    assert failed.index("std::fill_n(microphone_frame_.begin(), frames, 0);") < failed.index(
        "return 0;"
    )
