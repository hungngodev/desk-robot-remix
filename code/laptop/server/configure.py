"""Write a private local-only provider configuration without printing credentials."""

import argparse
import ipaddress
import os
import secrets
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def enable_streaming_voice(config: dict, env: dict[str, str]) -> dict:
    """Select adapters already present in pinned xinnan Xiaozhi server.

    This uses upstream AliyunBLStreamASR and HuoshanDoubleStreamTTSV2.
    It does not add an audio transport or a native speech-to-speech model.
    Secrets stay in the local chmod 0600 YAML, never in the git repository.
    """
    keys = {
        "DASHSCOPE_API_KEY": "Aliyun realtime speech API key",
        "VOLCENGINE_TTS_APPID": "Volcengine speech app ID",
        "VOLCENGINE_TTS_ACCESS_TOKEN": "Volcengine speech token",
        "VOLCENGINE_TTS_SPEAKER": "an activated Volcengine speaker ID",
    }
    missing = [key for key in keys if not env.get(key, "").strip()]
    if missing:
        raise ValueError(
            "Streaming profile needs private environment variables: "
            + ", ".join(missing)
        )
    config = dict(config)
    config["selected_module"] = dict(config["selected_module"])
    config["selected_module"]["ASR"] = "AliyunBLStreamASR"
    config["selected_module"]["TTS"] = "HuoshanDoubleStreamTTSV2"
    config["ASR"] = dict(config["ASR"])
    config["ASR"]["AliyunBLStreamASR"] = {
        "type": "aliyunbl_stream",
        "api_key": env["DASHSCOPE_API_KEY"].strip(),
        "model": "paraformer-realtime-v2",
        "format": "pcm",
        "sample_rate": 16000,
        "disfluency_removal_enabled": False,
        "semantic_punctuation_enabled": False,
        "max_sentence_silence": 800,
        "multi_threshold_mode_enabled": False,
        "punctuation_prediction_enabled": True,
        "inverse_text_normalization_enabled": True,
    }
    config["TTS"] = dict(config["TTS"])
    config["TTS"]["HuoshanDoubleStreamTTSV2"] = {
        "type": "huoshan_double_stream",
        "ws_url": "wss://openspeech.bytedance.com/api/v3/tts/bidirection",
        "appid": env["VOLCENGINE_TTS_APPID"].strip(),
        "access_token": env["VOLCENGINE_TTS_ACCESS_TOKEN"].strip(),
        "resource_id": "seed-tts-2.0",
        "speaker": env["VOLCENGINE_TTS_SPEAKER"].strip(),
        "enable_ws_reuse": True,
        "audio_params": {"speech_rate": 0, "loudness_rate": 0},
        "additions": {"post_process": {"pitch": 0}},
    }
    return config


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--server-ip", required=True)
    p.add_argument(
        "--streaming-profile", choices=["aliyun-volcengine"],
        help="Opt-in provider-backed streaming ASR/TTS; requires secret environment values"
    )
    args = p.parse_args()
    try:
        address = ipaddress.ip_address(args.server_ip)
    except ValueError:
        p.error("Use the Mac's reachable LAN IPv4 address")
    if address.version != 4 or address.is_loopback or address.is_unspecified:
        p.error("Use the Mac's reachable LAN IPv4 address")
    data = yaml.safe_load((ROOT / "config/xiaozhi.local.example.yaml").read_text())
    data["server"]["websocket"] = f"ws://{address}:8000/xiaozhi/v1/"
    data["server"]["auth_key"] = secrets.token_urlsafe(32)
    if args.streaming_profile:
        try:
            data = enable_streaming_voice(data, dict(os.environ))
        except ValueError as exc:
            p.error(str(exc))
    target = ROOT / "laptop/server/build/xiaozhi/main/xiaozhi-server/data/.config.yaml"
    if not target.parent.parent.is_dir():
        p.error("Install the server overlay first")
    target.parent.mkdir(exist_ok=True)
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        p.error(f"Private configuration already exists at {target}; preserve or move it first")
    with os.fdopen(fd, "w") as stream:
        yaml.safe_dump(data, stream, sort_keys=False)
    print(f"Private local provider settings created at {target}; credential hidden")


if __name__ == "__main__":
    main()
