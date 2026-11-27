"""Detector checkpoint SHA-256 identity binding and JPEG repr hiding."""
from __future__ import annotations

import hashlib
from io import BytesIO

import pytest
from desk_robot.config import ConfigurationError, RobotConfig, Settings
from desk_robot.object_detector import DetectorFrame, detect_object_frame
from desk_robot.object_targets import ObjectOwner, ObjectQuery
from desk_robot.vision import Detection, YoloWorldVision
from PIL import Image


def _sample_frame():
    buf = BytesIO()
    Image.new("RGB", (40, 30), "white").save(buf, format="JPEG")
    query = ObjectQuery(
        "robot-01", "key", "s1", "t1", "origin-1", 1, "tag-1", "cal-1",
        7, "boot-1", 1, 100, 1_000_000,
    )
    owner = ObjectOwner(
        "robot-01", "s1", "t1", "origin-1", 1, "tag-1", "cal-1",
        7, "boot-1", 1, True, True,
    )
    frame = DetectorFrame(
        "robot-01", "s1", "t1", "origin-1", 1, "tag-1", "cal-1",
        7, "boot-1", 1, 3, 200, 300, 1_800_000_000.0, buf.getvalue(),
    )
    return query, owner, frame


def test_detector_frame_repr_omits_raw_jpeg():
    _, _, frame = _sample_frame()
    assert frame.jpeg.startswith(b"\xff\xd8")
    rendered = repr(frame)
    assert "ff\\xd8" not in rendered and "JFIF" not in rendered
    assert "jpeg=" not in rendered


def test_settings_rejects_invalid_vision_weights_sha256():
    robots = [RobotConfig(id="robot-01", name="Pet", token_env="DESK_ROBOT_HEAD_1_TOKEN")]
    with pytest.raises((ConfigurationError, ValueError), match="64-character SHA-256"):
        Settings(mode="simulation", robots=robots, vision_weights_sha256="not-hex")
    valid = Settings(mode="simulation", robots=robots, vision_weights_sha256="A" * 64)
    assert valid.vision_weights_sha256 == "a" * 64


@pytest.mark.asyncio
async def test_yolo_detector_requires_matching_checkpoint_sha256(tmp_path):
    weights = tmp_path / "yolov8s-worldv2.pt"
    weights.write_bytes(b"fake-yolo-weights-v1")
    digest = hashlib.sha256(b"fake-yolo-weights-v1").hexdigest()
    query, owner, frame = _sample_frame()

    # Arbitrary weights path without expected qualified_model_sha256 is rejected.
    vision = YoloWorldVision(weights, runtime_asset_identity="yolov8s-worldv2+cpu")
    try:
        missing = await detect_object_frame(
            vision, frame, query, owner, model_qualified=True,
            now_us=500, clock_us=lambda: 500,
            request_is_current=lambda: True, safety_clear=lambda: True,
        )
        assert missing.reason == "detector_provenance_unverified"

        # Mismatched expected digest fails closed before inference.
        wrong = await detect_object_frame(
            vision, frame, query, owner, model_qualified=True,
            qualified_model_sha256="0" * 64,
            now_us=500, clock_us=lambda: 500,
            request_is_current=lambda: True, safety_clear=lambda: True,
        )
        assert wrong.reason == "detector_provenance_unverified"

        # Replace predict path to isolate SHA-256 identity binding offline.
        async def fake_detect(_jpeg, _label):
            return [Detection("key", 0.95, (2.0, 2.0, 12.0, 12.0))]

        vision.detect = fake_detect  # type: ignore[method-assign]
        vision.verify_weights_identity()

        matched = await detect_object_frame(
            vision, frame, query, owner, model_qualified=True,
            qualified_model_sha256=digest,
            model_asset_identity="yolov8s-worldv2+cpu",
            now_us=500, clock_us=lambda: 500,
            request_is_current=lambda: True, safety_clear=lambda: True,
        )
        assert matched.status == "camera_seen"
        assert matched.model_sha256 == digest
        assert matched.model_asset_identity == "yolov8s-worldv2+cpu"

        # Replacing the weights file after qualification must fail closed.
        weights.write_bytes(b"tampered-weights-v2")
        tampered = await detect_object_frame(
            vision, frame, query, owner, model_qualified=True,
            qualified_model_sha256=digest,
            now_us=500, clock_us=lambda: 500,
            request_is_current=lambda: True, safety_clear=lambda: True,
        )
        assert tampered.reason == "detector_provenance_unverified"
    finally:
        await vision.close()
