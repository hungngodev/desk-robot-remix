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


def test_single_oversized_network_batch_fails_before_any_frame_publication():
    jpeg = b"\xff\xd8" + b"x" * 180_000 + b"\xff\xd9"
    batch = b"".join(_part(i, jpeg) for i in range(1, 26))
    assert len(batch) > 4 * 1024 * 1024
    reader = _MjpegFrames(expected_robot_id="robot-01")
    with pytest.raises(ValueError, match="Oversized MJPEG network batch"):
        reader.feed(batch)
    assert not reader.buffer
    assert reader.feed(_part(26, jpeg)) == [
        (jpeg, (19, 26, 26 * 250000))
    ]


def test_many_tiny_jpeg_parts_cannot_monopolize_camera_parser():
    """A byte limit cannot bound the number of minimum-size MJPEG parts."""
    jpeg = b"\xff\xd8\xff\xd9"
    batch = b"".join(_part(i, jpeg) for i in range(1, 34))
    assert len(batch) < 64 * 1024
    reader = _MjpegFrames(expected_robot_id="robot-01")
    with pytest.raises(ValueError, match="Oversized MJPEG frame count"):
        reader.feed(batch)

    assert [identity[1] for _, identity in _MjpegFrames().feed(
        b"".join(_part(i, jpeg) for i in range(1, 8))
    )] == list(range(1, 8))


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


@pytest.mark.asyncio
async def test_camera_overflow_completion_cannot_poison_stream_reconnect(monkeypatch):
    """A bogus 20-digit source clock must not retire a healthy same-boot camera."""
    monkeypatch.setenv("SENSE_TEST_TOKEN", "x" * 32)
    jpeg = b"\xff\xd8scene\xff\xd9"
    huge = b"99999999999999999999"
    original = _part(1, jpeg)
    malformed = original.replace(
        b"X-Desk-Camera-Complete-Us: 250000",
        b"X-Desk-Camera-Complete-Us: " + huge,
    )
    assert malformed != original
    with pytest.raises(ValueError, match="source bounds"):
        _MjpegFrames(expected_robot_id="robot-01").feed(malformed)
    maximum = (1 << 63) - 1
    max_frame = original.replace(
        b"X-Desk-Camera-Complete-Us: 250000",
        f"X-Desk-Camera-Complete-Us: {maximum}".encode("ascii"),
    )
    assert _MjpegFrames(expected_robot_id="robot-01").feed(max_frame) == [
        (jpeg, (19, 1, maximum))
    ]

    responses = iter((malformed, _part(2, jpeg)))

    def respond(_request):
        return httpx.Response(
            200, content=next(responses),
            headers={"content-type":
                     "multipart/x-mixed-replace; boundary=deskrobotframe"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        head = HttpHead(RobotConfig(
            id="robot-01", name="Camera pet", token_env="SENSE_TEST_TOKEN",
            head_url="http://head.example",
        ), client)
        with pytest.raises(HeadError, match="source bounds invalid"):
            async for _ in head.stream_frames():
                pass
        assert head._last_camera is None
        assert head._stream_latest is None
        recovered = [frame async for frame, _ in head.stream_frames()]
        assert recovered == [jpeg]
        assert head._last_camera == (19, 2, 500000)


@pytest.mark.asyncio
async def test_camera_overflow_completion_cannot_poison_legacy_still(monkeypatch):
    monkeypatch.setenv("SENSE_TEST_TOKEN", "x" * 32)
    jpeg = b"\xff\xd8scene\xff\xd9"
    clock = iter(("99999999999999999999", "500000"))
    seq = iter(("1", "2"))

    def respond(_request):
        return httpx.Response(200, content=jpeg, headers={
            "X-Desk-Camera-Robot-Id": "robot-01",
            "X-Desk-Camera-Boot": "19",
            "X-Desk-Camera-Sequence": next(seq),
            "X-Desk-Camera-Complete-Us": next(clock),
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        head = HttpHead(RobotConfig(
            id="robot-01", name="Camera pet", token_env="SENSE_TEST_TOKEN",
            head_url="http://head.example",
        ), client)
        with pytest.raises(HeadError, match="completion metadata out of bounds"):
            await head.snapshot()
        assert head._last_camera is None
        assert await head.snapshot() == jpeg
        assert head._last_camera == (19, 2, 500000)


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
        captured_read_timeout = []
        open_stream = client.stream

        def inspect_stream(*args, **kwargs):
            # The selected MJPEG transport keeps the actual one HTTP stream
            # but bounds silent socket waits after consent is revoked.
            captured_read_timeout.append(kwargs["timeout"].read)
            return open_stream(*args, **kwargs)

        monkeypatch.setattr(client, "stream", inspect_stream)
        with pytest.raises(HeadError, match="identity mismatch"):
            async for _ in head.stream_frames():
                pass
        assert captured_read_timeout == [1.5]
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


class TwoPartCameraStream(httpx.AsyncByteStream):
    def __init__(self, frames):
        self.frames = frames

    async def __aiter__(self):
        for frame in self.frames:
            yield frame


@pytest.mark.asyncio
@pytest.mark.parametrize("device_kept_up", [False, True])
async def test_late_network_camera_frame_needs_matching_source_clock_progress(
    monkeypatch, device_kept_up,
):
    """A delayed old device frame cannot get a new Mac freshness clock."""
    monkeypatch.setenv("SENSE_TEST_TOKEN", "x" * 32)
    jpeg = b"\xff\xd8scene\xff\xd9"
    old = _part(1, jpeg)
    newer = _part(2, jpeg)
    if device_kept_up:
        newer = newer.replace(
            b"X-Desk-Camera-Complete-Us: 500000\r\n",
            b"X-Desk-Camera-Complete-Us: 5250000\r\n",
        )

    def respond(_request):
        return httpx.Response(
            200,
            stream=TwoPartCameraStream((old, newer)),
            headers={"content-type":
                     "multipart/x-mixed-replace; boundary=deskrobotframe"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        head = HttpHead(
            RobotConfig(
                id="robot-01", name="Camera pet",
                token_env="SENSE_TEST_TOKEN", head_url="http://head.example",
            ), client,
        )
        ticks = iter((100.0, 105.0))
        monkeypatch.setattr(
            "desk_robot.transport.time",
            SimpleNamespace(monotonic=lambda: next(ticks)),
        )
        if device_kept_up:
            received = [when async for _, when in head.stream_frames()]
            assert received == [100.0, 105.0]
            assert head._last_camera == (19, 2, 5250000)
        else:
            with pytest.raises(HeadError, match="Buffered stale camera frame"):
                async for _ in head.stream_frames():
                    pass
            assert head._stream_latest is None
            assert head._stream_connected is False


@pytest.mark.asyncio
async def test_subsecond_camera_network_backlog_is_not_fresh(monkeypatch):
    """A 950ms Mac delivery gap with only 250ms camera progress is stale."""
    monkeypatch.setenv("SENSE_TEST_TOKEN", "x" * 32)
    jpeg = b"\xff\xd8scene\xff\xd9"

    def respond(_request):
        return httpx.Response(
            200,
            stream=TwoPartCameraStream((_part(1, jpeg), _part(2, jpeg))),
            headers={"content-type":
                     "multipart/x-mixed-replace; boundary=deskrobotframe"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        head = HttpHead(
            RobotConfig(
                id="robot-01", name="Camera pet",
                token_env="SENSE_TEST_TOKEN", head_url="http://head.example",
            ), client,
        )
        ticks = iter((100.0, 100.95))
        monkeypatch.setattr(
            "desk_robot.transport.time",
            SimpleNamespace(monotonic=lambda: next(ticks)),
        )
        with pytest.raises(HeadError, match="Buffered stale camera frame"):
            async for _ in head.stream_frames():
                pass
        assert head._stream_latest is None


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
