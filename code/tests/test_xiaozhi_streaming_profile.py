"""One optional pinned-upstream Xiaozhi streaming profile, no fake credentials."""
import importlib.util
import sys
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def configure_module():
    spec = importlib.util.spec_from_file_location(
        "desk_server_configure", ROOT / "laptop/server/configure.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def profile_env():
    return {
        "DASHSCOPE_API_KEY": "test-private-api-key",
        "VOLCENGINE_TTS_APPID": "test-private-app-id",
        "VOLCENGINE_TTS_ACCESS_TOKEN": "test-private-token",
        "VOLCENGINE_TTS_SPEAKER": "test-private-enabled-english-speaker",
    }


def test_explicit_streamed_voice_reuses_real_xiaozhi_provider_type_ids():
    module = configure_module()
    original = yaml.safe_load(
        (ROOT / "config/xiaozhi.local.example.yaml").read_text()
    )
    baseline = deepcopy(original)
    result = module.enable_streaming_voice(original, profile_env())
    assert result["selected_module"]["ASR"] == "AliyunBLStreamASR"
    assert result["selected_module"]["TTS"] == "HuoshanDoubleStreamTTSV2"
    assert result["ASR"]["AliyunBLStreamASR"]["type"] == "aliyunbl_stream"
    assert result["TTS"]["HuoshanDoubleStreamTTSV2"]["type"] == "huoshan_double_stream"
    assert result["TTS"]["HuoshanDoubleStreamTTSV2"]["resource_id"] == "seed-tts-2.0"
    # Provider-side PCM format is not the compressed head Opus wire bitrate.
    assert result["ASR"]["AliyunBLStreamASR"]["format"] == "pcm"
    assert result["ASR"]["AliyunBLStreamASR"]["sample_rate"] == 16000
    assert result["selected_module"]["LLM"] == original["selected_module"]["LLM"]
    assert result["selected_module"]["Intent"] == "function_call"
    assert result["selected_module"]["VAD"] == baseline["selected_module"]["VAD"]
    assert result["server"] == baseline["server"]
    assert result["Intent"] == baseline["Intent"]
    assert result["ASR"]["FunASR"] == baseline["ASR"]["FunASR"]
    assert result["TTS"]["CustomTTS"] == baseline["TTS"]["CustomTTS"]
    # Never mutate the default local FunASR, Ollama or Kokoro profile in place.
    assert original == baseline
    assert original["selected_module"]["ASR"] == "FunASR"
    assert original["selected_module"]["TTS"] == "CustomTTS"
    assert "HuoshanDoubleStreamTTSV2" not in original["TTS"]


@pytest.mark.parametrize("missing", [
    "DASHSCOPE_API_KEY", "VOLCENGINE_TTS_APPID",
    "VOLCENGINE_TTS_ACCESS_TOKEN", "VOLCENGINE_TTS_SPEAKER",
])
@pytest.mark.parametrize("value", [None, "", " \t\n"])
def test_streaming_profile_refuses_unconfigured_secrets(missing, value):
    module = configure_module()
    original = yaml.safe_load(
        (ROOT / "config/xiaozhi.local.example.yaml").read_text()
    )
    baseline = deepcopy(original)
    env = profile_env()
    if value is None:
        env.pop(missing)
    else:
        env[missing] = value
    with pytest.raises(ValueError, match=missing):
        module.enable_streaming_voice(original, env)
    assert original == baseline
    assert original["selected_module"]["ASR"] == "FunASR"


@pytest.mark.parametrize("address", ["not-an-ip", "127.0.0.1", "0.0.0.0", "::1"])
def test_configure_invalid_address(monkeypatch, capsys, address):
    module = configure_module()
    monkeypatch.setattr(sys, "argv", ["configure.py", "--server-ip", address])
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2
    assert "reachable LAN IPv4" in capsys.readouterr().err


@pytest.fixture
def configure_target(monkeypatch, tmp_path):
    module = configure_module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    template = tmp_path / "config/xiaozhi.local.example.yaml"
    template.parent.mkdir()
    template.write_text((ROOT / "config/xiaozhi.local.example.yaml").read_text())
    target = tmp_path / "laptop/server/build/xiaozhi/main/xiaozhi-server/data/.config.yaml"
    target.parent.parent.mkdir(parents=True)
    monkeypatch.setattr(sys, "argv", ["configure.py", "--server-ip", "192.168.1.10"])
    return module, target


def test_configure_rerun_preserves_file(configure_target, capsys):
    module, target = configure_target
    module.main()
    original = target.read_bytes()
    assert target.stat().st_mode & 0o777 == 0o600
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2
    assert "already exists" in capsys.readouterr().err
    assert target.read_bytes() == original


def test_configure_missing_provider_credentials(configure_target, monkeypatch, capsys):
    module, target = configure_target
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", [*sys.argv, "--streaming-profile", "aliyun-volcengine"])
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2
    assert "DASHSCOPE_API_KEY" in capsys.readouterr().err
    assert not target.exists()


def test_configure_streaming_cli_round_trip(configure_target, monkeypatch, capsys):
    module, target = configure_target
    baseline = yaml.safe_load((ROOT / "config/xiaozhi.local.example.yaml").read_text())
    padded_env = {
        "DASHSCOPE_API_KEY": "  test-private-cli-api-key \n",
        "VOLCENGINE_TTS_APPID": "\ttest-private-cli-app-id  ",
        "VOLCENGINE_TTS_ACCESS_TOKEN": "  test-private-cli-token\t",
        "VOLCENGINE_TTS_SPEAKER": "  test-private-cli-speaker  ",
    }
    for key, value in padded_env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(sys, "argv", [*sys.argv, "--streaming-profile", "aliyun-volcengine"])
    module.main()
    captured = capsys.readouterr()
    assert target.stat().st_mode & 0o777 == 0o600
    for secret_value in padded_env.values():
        stripped = secret_value.strip()
        assert stripped not in captured.out
        assert stripped not in captured.err

    written = yaml.safe_load(target.read_text())
    assert written["read_config_from_api"] is False
    assert written["server"]["websocket"] == "ws://192.168.1.10:8000/xiaozhi/v1/"
    assert written["server"]["auth"] == {"enabled": True, "allowed_devices": []}
    auth_key = written["server"]["auth_key"]
    assert isinstance(auth_key, str) and len(auth_key.strip()) >= 32
    assert auth_key != "LOCAL_RANDOM_SECRET"

    assert written["selected_module"]["ASR"] == "AliyunBLStreamASR"
    assert written["selected_module"]["TTS"] == "HuoshanDoubleStreamTTSV2"
    assert written["selected_module"]["LLM"] == baseline["selected_module"]["LLM"]
    assert written["selected_module"]["Intent"] == "function_call"
    assert written["selected_module"]["VAD"] == baseline["selected_module"]["VAD"]
    assert written["Intent"] == baseline["Intent"]
    assert written["ASR"]["FunASR"] == baseline["ASR"]["FunASR"]
    assert written["TTS"]["CustomTTS"] == baseline["TTS"]["CustomTTS"]
    assert written["ASR"]["AliyunBLStreamASR"]["api_key"] == "test-private-cli-api-key"
    assert written["ASR"]["AliyunBLStreamASR"]["model"] == "paraformer-realtime-v2"
    assert written["ASR"]["AliyunBLStreamASR"]["sample_rate"] == 16000
    assert (
        written["TTS"]["HuoshanDoubleStreamTTSV2"]["ws_url"]
        == "wss://openspeech.bytedance.com/api/v3/tts/bidirection"
    )
    assert written["TTS"]["HuoshanDoubleStreamTTSV2"]["appid"] == "test-private-cli-app-id"
    assert written["TTS"]["HuoshanDoubleStreamTTSV2"]["access_token"] == "test-private-cli-token"
    assert written["TTS"]["HuoshanDoubleStreamTTSV2"]["speaker"] == "test-private-cli-speaker"
