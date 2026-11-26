"""Keep the existing Xiaozhi ASR endpoints tolerant of mid-thought pauses."""

import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_local_and_streaming_endpointing_allow_breathing_pauses():
    spec = importlib.util.spec_from_file_location(
        "desk_endpoint_configure", ROOT / "laptop/server/configure.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    local = yaml.safe_load((ROOT / "config/xiaozhi.local.example.yaml").read_text())
    streaming = module.enable_streaming_voice(local, {
        "DASHSCOPE_API_KEY": "test",
        "VOLCENGINE_TTS_APPID": "test",
        "VOLCENGINE_TTS_ACCESS_TOKEN": "test",
        "VOLCENGINE_TTS_SPEAKER": "test",
    })
    vad = local["VAD"]["SileroVAD"]
    asr = streaming["ASR"]["AliyunBLStreamASR"]
    assert local["selected_module"]["VAD"] == "SileroVAD"
    assert vad["min_silence_duration_ms"] == 800
    assert asr["max_sentence_silence"] == 800
    assert asr["semantic_punctuation_enabled"] is False
    assert asr["multi_threshold_mode_enabled"] is False
    assert streaming["VAD"] == local["VAD"]
    # Do not trade slower interruption for a longer end-of-turn silence.
    assert (vad["threshold"], vad["threshold_low"]) == (0.5, 0.3)
