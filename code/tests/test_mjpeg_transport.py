"""Sense MJPEG parser memory bounds for batched and fragmented network reads."""

from types import SimpleNamespace

import httpx
import pytest
from desk_robot.config import RobotConfig
from desk_robot.transport import HeadError, HttpHead, _MjpegFrames


def _part(sequence: int, jpeg: bytes) -> bytes:
    return (
        b"--deskrobotframe\r\n"
        b"Content-Type: image/jpeg\r\n"
        + f"Content-Length: {len(jpeg)}\r\n".encode("ascii")
        + b"X-Desk-Camera-Robot-Id: robot-01\r\n"
        + b"X-Desk-Camera-Boot: 19\r\n"
        + f"X-Desk-Camera-Sequence: {sequence}\r\n".encode("ascii")
        + f"X-Desk-Camera-Complete-Us: {sequence * 250000}\r\n\r\n".encode("ascii")
        + jpeg + b"\r\n"
    )


def test_large_network_read_keeps_incremental_mjpeg_buffer_bounded():
    class TrackedBuffer(bytearray):
        peak = 0

        def extend(self, other):
            super().extend(other)
            self.peak = max(self.peak, len(self))

    jpeg = b"\xff\xd8" + b"x" * 180_000 + b"\xff\xd9"
    combined = b"".join(_part(i, jpeg) for i in range(1, 8))
    assert len(combined) > 1024 * 1024
    reader = _MjpegFrames()
    reader.buffer = TrackedBuffer()
    frames = reader.feed(combined)
    assert [identity[1] for _, identity in frames] == list(range(1, 8))
    assert all(frame == jpeg for frame, _ in frames)
    assert not reader.buffer
    assert reader.buffer.peak <= 512 * 1024 + 64 * 1024 + 1024


def test_camera_stream_header_requires_per_frame_robot_provenance():
    jpeg = b"\xff\xd8cam\xff\xd9"
    valid = _part(1, jpeg)
    assert _MjpegFrames(expected_robot_id="robot-01").feed(valid) == [
        (jpeg, (19, 1, 250000))
    ]
    with pytest.raises(ValueError, match="identity"):
        _MjpegFrames(expected_robot_id="robot-01").feed(
            valid.replace(b"X-Desk-Camera-Robot-Id: robot-01\r\n", b"")
        )
    with pytest.raises(ValueError, match="identity"):
        _MjpegFrames(expected_robot_id="robot-01").feed(
            valid.replace(b"X-Desk-Camera-Robot-Id: robot-01",
                          b"X-Desk-Camera-Robot-Id: robot-02")
        )


@pytest.mark.asyncio
async def test_multi_pet_stream_refuses_foreign_camera_before_publication(monkeypatch):
    monkeypatch.setenv("SENSE_TEST_TOKEN", "x" * 32)
    jpeg = b"\xff\xd8frame\xff\xd9"
    foreign = _part(2, jpeg).replace(
        b"X-Desk-Camera-Robot-Id: robot-01",
        b"X-Desk-Camera-Robot-Id: robot-02",
    )
    batch = _part(1, jpeg) + foreign
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                content=batch,
                headers={"content-type":
                         "multipart/x-mixed-replace; boundary=deskrobotframe"},
            )
        )
    ) as client:
        head = HttpHead(
            RobotConfig(
                id="robot-01", name="Pet one", token_env="SENSE_TEST_TOKEN",
                head_url="http://head.example",
            ), client,
        )
        with pytest.raises(HeadError, match="identity mismatch"):
            async for _ in head.stream_frames():
                pass
        assert head._stream_latest is None
        assert head._stream_connected is False


def test_fragmented_mjpeg_header_and_body_complete_once():
    jpeg = b"\xff\xd8" + b"\x01" * 45 + b"\xff\xd9"
    raw = _part(1, jpeg)
    reader = _MjpegFrames()
    assert reader.feed(raw[:6]) == []
    assert reader.feed(raw[6:78]) == []
    assert reader.feed(raw[78:-1]) == []
    assert reader.feed(raw[-1:]) == [(jpeg, (19, 1, 250000))]
    assert reader.feed(b"") == []

def test_stream_iterator_yields_before_exhausting_large_batch():
    jpeg = b"\xff\xd8" + b"y" * 180_000 + b"\xff\xd9"
    combined = b"".join(_part(i, jpeg) for i in range(1, 8))
    reader = _MjpegFrames()
    frames = reader.iter_feed(combined)
    assert next(frames) == (jpeg, (19, 1, 250000))
    # The iterator is paused after the first useful camera frame. A large
    # backlog must not be materialized before the consumer can yield.
    assert len(reader.buffer) < 64 * 1024
    assert [identity[1] for _, identity in frames] == list(range(2, 8))
    assert not reader.buffer

@pytest.mark.asyncio
async def test_batched_stream_frames_keep_actual_network_receipt_timestamp(
    monkeypatch,
):
    monkeypatch.setenv("SENSE_TEST_TOKEN", "x" * 32)
    jpeg = b"\xff\xd8" + b"z" * 500 + b"\xff\xd9"
    stream = _part(1, jpeg) + _part(2, jpeg)

    def respond(request):
        assert request.headers["authorization"] == "Bearer " + "x" * 32
        return httpx.Response(
            200,
            content=stream,
            headers={"content-type": "multipart/x-mixed-replace; boundary=deskrobotframe"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        head = HttpHead(
            RobotConfig(
                id="robot-01", name="Camera pet", token_env="SENSE_TEST_TOKEN",
                head_url="http://head.example",
            ),
            client,
        )
        ticks = iter((123.0, 456.0))
        monkeypatch.setattr(
            "desk_robot.transport.time",
            SimpleNamespace(monotonic=lambda: next(ticks)),
        )
        received = [when async for _, when in head.stream_frames()]
    # The most recent frame wins within one network read. Older identities
    # are still validated before the scene is handed to the model.
    assert received == [123.0]
    assert head._last_camera == (19, 2, 500000)


@pytest.mark.asyncio
async def test_batched_stream_rejects_replayed_identity_before_latest(monkeypatch):
    monkeypatch.setenv("SENSE_TEST_TOKEN", "x" * 32)
    jpeg = b"\xff\xd8" + b"x" * 20 + b"\xff\xd9"
    batch = _part(1, jpeg) + _part(1, jpeg) + _part(2, jpeg)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, content=batch, headers={
                    "content-type": "multipart/x-mixed-replace; boundary=deskrobotframe"
                },
            )
        )
    ) as client:
        head = HttpHead(
            RobotConfig(
                id="robot-01", name="Camera pet", token_env="SENSE_TEST_TOKEN",
                head_url="http://head.example",
            ),
            client,
        )
        with pytest.raises(HeadError, match="stale or replayed"):
            async for _ in head.stream_frames():
                pass


@pytest.mark.asyncio
async def test_sense_bearer_requests_refuse_redirect_even_if_shared_client_follows(
    monkeypatch,
):
    """A foreign redirect cannot change the authenticated camera endpoint."""
    monkeypatch.setenv("SENSE_TEST_TOKEN", "x" * 32)
    visited = []

    def redirect(request):
        visited.append(str(request.url))
        return httpx.Response(
            302, headers={"location": "https://foreign.invalid/other"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(redirect), follow_redirects=True,
    ) as client:
        head = HttpHead(
            RobotConfig(
                id="robot-01", name="Camera pet", token_env="SENSE_TEST_TOKEN",
                head_url="http://head.example",
            ), client,
        )
        with pytest.raises(HeadError, match="head request failed"):
            await head._request("GET", "/api/audio.reference")
        with pytest.raises(HeadError, match="camera stream unavailable"):
            async for _ in head.stream_frames():
                pass
    assert visited == [
        "http://head.example/api/audio.reference",
        "http://head.example/api/camera.mjpg",
    ]
