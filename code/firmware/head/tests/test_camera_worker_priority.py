"""Keep optional JPEG network work below the canonical realtime audio tasks."""

import re
from pathlib import Path

import pytest

HEAD = Path(__file__).resolve().parents[1]


def _worker_priority(source: str, worker: str, name: str) -> int:
    match = re.search(
        rf'xTaskCreate\(\s*{worker}\s*,\s*"{name}"\s*,\s*8192\s*,\s*'
        r'async_req\s*,\s*(\d+)\s*,\s*nullptr\s*\)',
        source,
    )
    assert match is not None, f"Missing or changed {name} task configuration"
    return int(match.group(1))


@pytest.mark.parametrize(
    ("worker", "name"),
    [("CameraTask", "robot_camera"), ("CameraStreamTask", "robot_stream")],
)
def test_camera_workers_yield_to_audio(worker: str, name: str) -> None:
    bridge = (HEAD / "overlay/robot_bridge.cc").read_text()
    assert _worker_priority(bridge, worker, name) == 1
    assert _worker_priority(bridge, "BodyReadTask", "robot_body_read") == 3


def test_camera_priority_below_pinned_xiaozhi_audio() -> None:
    audio_path = HEAD.parents[1] / "upstream/xiaozhi-esp32/main/audio/audio_service.cc"
    if not audio_path.is_file():
        pytest.skip("Pinned Xiaozhi source unavailable")
    audio = audio_path.read_text()
    for name in ("audio_input", "audio_output", "opus_codec"):
        priorities = re.findall(rf'"{name}"\s*,[^,]+,\s*this\s*,\s*(\d+)\s*,', audio)
        assert priorities, f"Missing pinned {name} task configuration"
        assert min(map(int, priorities)) > 1
