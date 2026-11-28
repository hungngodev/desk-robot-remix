"""Synthetic JPEG buffers must close even when Pillow raises."""

from io import BytesIO

import pytest
from desk_robot import simulator
from PIL import Image, UnidentifiedImageError


@pytest.fixture
def buffers(monkeypatch):
    opened = []

    def track(*args):
        stream = BytesIO(*args)
        opened.append(stream)  # Prevent garbage collection from masking leaks.
        return stream

    monkeypatch.setattr(simulator, "BytesIO", track)
    return opened


@pytest.mark.asyncio
async def test_snapshot_closes_buffer_and_preserves_jpeg(buffers):
    jpeg = await simulator.SimulatedHead("robot-01").snapshot()
    assert len(buffers) == 1 and buffers[0].closed
    with BytesIO(jpeg) as source, Image.open(source) as image:
        assert image.format == "JPEG"
        assert image.size == (200, 200)


@pytest.mark.asyncio
async def test_snapshot_closes_buffer_on_encoder_failure(buffers, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("encoder failed")

    monkeypatch.setattr(Image.Image, "save", fail)
    with pytest.raises(OSError, match="encoder failed"):
        await simulator.SimulatedHead("robot-01").snapshot()
    assert len(buffers) == 1 and buffers[0].closed


@pytest.mark.asyncio
async def test_detect_closes_buffer_and_preserves_detection(buffers):
    jpeg = await simulator.SimulatedHead("robot-01").snapshot()
    detections = await simulator.SimulationVision().detect(jpeg, "candy")
    assert len(detections) == 1 and detections[0].label == "candy"
    assert len(buffers) == 2 and all(stream.closed for stream in buffers)


@pytest.mark.asyncio
async def test_detect_closes_buffer_on_invalid_jpeg(buffers):
    with pytest.raises(UnidentifiedImageError):
        await simulator.SimulationVision().detect(b"not a JPEG", "candy")
    assert len(buffers) == 1 and buffers[0].closed
