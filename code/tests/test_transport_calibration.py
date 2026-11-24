import json
from pathlib import Path
from runpy import run_path

import httpx
import pytest
from desk_robot.calibration import Calibration
from desk_robot.transport import HeadError, HttpHead, expected_ack, validate_command

# The USB bench tool is intentionally a standalone script, not a second
# installable robot controller or a package in the firmware/runtime hierarchy.
inspect_status = run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/serial_bench.py")
)["inspect_status"]


@pytest.mark.parametrize(
    "command",
    [
        "drive 41 0 100",
        "drive 0 0 251",
        "drive 0 0 nan",
        "drive 0 0 100\narm",
        "grip 121",
        "lift 59",
        "stop extra",
        "arm ",
        "rearm",  # local body USB recovery is never a network movement command
        "drive 0  0 100",
    ],
)
def test_invalid_commands_rejected(command):
    with pytest.raises(ValueError):
        validate_command(command)


def test_default_drive_duration_matches_body_and_head_ack():
    assert validate_command("drive 20 -20") == "drive"
    assert expected_ack("drive 20 -20") == (
        "OK drive left=20 right=-20 ms=250"
    )
    assert expected_ack("drive 20 -20 50") == (
        "OK drive left=20 right=-20 ms=50"
    )
    for invalid in ("drive 40 40 251", "drive 41 0", "drive 0 0 0"):
        with pytest.raises(ValueError):
            validate_command(invalid)


@pytest.mark.parametrize(
    "reply,identity",
    [
        ("OK drive", "robot-01"),
        ("OK drive left=21 right=20 ms=100", "robot-01"),
        ("OK drive left=20 right=20 ms=100", "robot-02"),
    ],
)
async def test_ack_must_match_command_and_robot(settings, tokens, reply, identity):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True, "reply": reply, "robot_id": identity})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client)
        with pytest.raises(HeadError):
            await head.command("drive 20 20 100")
        assert len(calls) == 1


@pytest.mark.parametrize(
    "payload",
    [
        b'{"ok":false,"ok":true,"reply":"OK halt","robot_id":"robot-01"}',
        b'{"ok":true,"reply":"ERR denied","reply":"OK halt","robot_id":"robot-01"}',
        b'{"ok":true,"reply":"OK halt","robot_id":"robot-02","robot_id":"robot-01"}',
    ],
)
async def test_terminal_halt_refuses_ambiguous_json_receipt(settings, tokens, payload):
    calls = []

    def handler(request):
        calls.append(request)
        assert json.loads(request.content) == {"command": "halt"}
        return httpx.Response(200, content=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client)
        with pytest.raises(HeadError, match="Malformed authenticated head JSON"):
            await head.command("halt")
        assert len(calls) == 1


async def test_nested_status_fields_must_not_conflict(settings, tokens):
    payload = b'{"robot_id":"robot-01","safety":{"ready":false,"ready":true}}'
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.path == "/api/status"
        if len(calls) == 1:
            return httpx.Response(200, content=payload)
        return httpx.Response(
            200, json={"robot_id": "robot-01", "safety": {"ready": False}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client)
        with pytest.raises(HeadError, match="Malformed authenticated head JSON"):
            await head.status()
        assert (await head.status())["safety"]["ready"] is False
        assert len(calls) == 2


async def test_camera_completion_sequence_and_boot_id_protect_five_pet_capture(settings, tokens):
    calls = 0
    frames = [
        ("12", "1", "10000"),
        ("12", "2", "20000"),
        ("12", "2", "20000"),  # replay, must not be a new observation
        ("13", "1", "5000"),   # reset after real Sense reboot
    ]
    async def handler(request):
        nonlocal calls
        assert request.url.path == "/api/camera.jpg"
        index = min(calls, len(frames) - 1)
        calls += 1
        return httpx.Response(200, headers={
            **dict(zip(
                ("X-Desk-Camera-Boot", "X-Desk-Camera-Sequence",
                 "X-Desk-Camera-Complete-Us"), frames[index], strict=True,
            )),
            "X-Desk-Camera-Robot-Id": settings.robots[0].id,
        }, content=b"\xff\xd8frame\xff\xd9")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client, strict_capture=True)
        assert await head.snapshot() == b"\xff\xd8frame\xff\xd9"
        assert await head.snapshot() == b"\xff\xd8frame\xff\xd9"
        with pytest.raises(HeadError, match="stale or replayed"):
            await head.snapshot()
        assert await head.snapshot() == b"\xff\xd8frame\xff\xd9"
        assert calls == 4




async def test_old_xiao_camera_boot_cannot_reenter_after_live_reconnect(
    settings, tokens,
):
    """Boot A, B, then delayed A is not a new observation on the Mac."""
    frames = [
        (12, 1, 10000), (13, 1, 2000), (12, 3, 30000),
    ]
    calls = 0

    async def handler(request):
        nonlocal calls
        assert request.url.path == "/api/camera.jpg"
        boot, seq, completed = frames[calls]
        calls += 1
        return httpx.Response(
            200, headers={
                "X-Desk-Camera-Robot-Id": settings.robots[0].id,
                "X-Desk-Camera-Boot": str(boot),
                "X-Desk-Camera-Sequence": str(seq),
                "X-Desk-Camera-Complete-Us": str(completed),
            }, content=b"\xff\xd8new frame\xff\xd9",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client, strict_capture=True)
        assert (await head.snapshot()).startswith(b"\xff\xd8")
        assert (await head.snapshot()).startswith(b"\xff\xd8")
        with pytest.raises(HeadError, match="retired boot"):
            await head.snapshot()
        assert head._last_camera == (13, 1, 2000)
        assert head._retired_camera_boots == {12}
        assert calls == 3


async def test_xiao_camera_boot_history_never_evicts_old_frame_identity(
    settings, tokens,
):
    """Nine real boot changes exhaust a bounded camera provenance lease."""
    calls = 0

    async def handler(request):
        nonlocal calls
        boot = 100 + calls
        calls += 1
        return httpx.Response(
            200, headers={
                "X-Desk-Camera-Robot-Id": settings.robots[0].id,
                "X-Desk-Camera-Boot": str(boot),
                "X-Desk-Camera-Sequence": "1",
                "X-Desk-Camera-Complete-Us": "1000",
            }, content=b"\xff\xd8image\xff\xd9",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client, strict_capture=True)
        for _ in range(9):
            await head.snapshot()  # 100 through 108, eight retired boots.
        assert len(head._retired_camera_boots) == 8
        with pytest.raises(HeadError, match="history exhausted"):
            await head.snapshot()
        assert head._last_camera == (108, 1, 1000)
        assert 100 in head._retired_camera_boots
        assert calls == 10



async def test_truncated_camera_jpeg_does_not_consume_source_sequence(settings, tokens):
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        assert request.url.path == "/api/camera.jpg"
        return httpx.Response(
            200,
            headers={
                "X-Desk-Camera-Robot-Id": settings.robots[0].id,
                "X-Desk-Camera-Boot": "51",
                "X-Desk-Camera-Sequence": "1",
                "X-Desk-Camera-Complete-Us": "10000",
            },
            content=(b"\xff\xd8frame" if calls == 1
                     else b"\xff\xd8frame\xff\xd9"),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client, strict_capture=True)
        with pytest.raises(HeadError, match="complete JPEG"):
            await head.snapshot()
        # Same authentic source sequence is valid on retry because a
        # truncated response must not be accepted as a camera observation.
        assert await head.snapshot() == b"\xff\xd8frame\xff\xd9"
        assert calls == 2


async def test_oversized_still_jpeg_does_not_consume_camera_sequence(settings, tokens):
    """The Mac must enforce the Sense 512 KiB cap even on legacy still HTTP."""
    calls = 0

    async def handler(request):
        nonlocal calls
        assert request.url.path == "/api/camera.jpg"
        calls += 1
        return httpx.Response(
            200,
            headers={
                "X-Desk-Camera-Robot-Id": settings.robots[0].id,
                "X-Desk-Camera-Boot": "61",
                "X-Desk-Camera-Sequence": "1",
                "X-Desk-Camera-Complete-Us": "11000",
            },
            content=(b"\xff\xd8" + b"x" * (512 * 1024) + b"\xff\xd9"
                     if calls == 1 else b"\xff\xd8ok\xff\xd9"),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client, strict_capture=True)
        with pytest.raises(HeadError, match="bounded complete JPEG"):
            await head.snapshot()
        assert await head.snapshot() == b"\xff\xd8ok\xff\xd9"
        assert head._last_camera == (61, 1, 11000)
        assert calls == 2


async def test_snapshot_rejects_missing_or_cross_pet_camera_identity(
    settings, tokens,
):
    """A misrouted physical JPEG is never attributed to a different pet."""
    for sender in (None, "robot-02"):
        # Bind this specific mocked camera identity, not the loop cell.
        async def handler(request, sender=sender):
            headers = {
                "X-Desk-Camera-Boot": "31",
                "X-Desk-Camera-Sequence": "1",
                "X-Desk-Camera-Complete-Us": "1000",
            }
            if sender is not None:
                headers["X-Desk-Camera-Robot-Id"] = sender
            return httpx.Response(
                200, headers=headers, content=b"\xff\xd8camera\xff\xd9",
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            head = HttpHead(settings.robots[0], client, strict_capture=True)
            with pytest.raises(HeadError, match="robot identity"):
                await head.snapshot()
            assert head._last_camera is None
            assert not head._retired_camera_boots


async def test_hardware_camera_requires_true_capture_metadata(settings, tokens):
    async def handler(request):
        # Supply the required pet identity, but NOT the camera boot,
        # sequence, or capture completion headers. This isolates the
        # missing-metadata refusal from the earlier identity check.
        return httpx.Response(
            200, headers={"X-Desk-Camera-Robot-Id": settings.robots[0].id},
            content=b"\xff\xd8unmarked\xff\xd9",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client, strict_capture=True)
        with pytest.raises(HeadError, match="metadata"):
            await head.snapshot()


def _stream_part(seq, payload=b"\xff\xd8camera\xff\xd9", *, boot=17):
    return (
        f"--deskrobotframe\r\n"
        "Content-Type: image/jpeg\r\n"
        f"Content-Length: {len(payload)}\r\n"
        "X-Desk-Camera-Robot-Id: robot-01\r\n"
        f"X-Desk-Camera-Boot: {boot}\r\n"
        f"X-Desk-Camera-Sequence: {seq}\r\n"
        f"X-Desk-Camera-Complete-Us: {seq * 1000}\r\n\r\n"
    ).encode("ascii") + payload + b"\r\n"


@pytest.mark.parametrize("mode", ["connected", "failed", "required"])
async def test_pending_still_capture_cannot_relabel_live_stream(settings, tokens, mode):
    import asyncio

    entered = asyncio.Event()
    release = asyncio.Event()
    jpeg = b"\xff\xd8stream\xff\xd9"

    async def handler(request):
        if request.url.path == "/api/camera.jpg":
            entered.set()
            await release.wait()
            return httpx.Response(
                200, content=b"\xff\xd8still\xff\xd9",
                headers={
                    "X-Desk-Camera-Robot-Id": "robot-01",
                    "X-Desk-Camera-Boot": "17",
                    "X-Desk-Camera-Sequence": "2",
                    "X-Desk-Camera-Complete-Us": "2000",
                },
            )
        assert request.url.path == "/api/camera.mjpg"
        if mode == "failed":
            return httpx.Response(503)
        return httpx.Response(
            200, content=_stream_part(1, jpeg),
            headers={"Content-Type": "multipart/x-mixed-replace; boundary=deskrobotframe"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client, strict_capture=True)
        still = asyncio.create_task(head.snapshot())
        stream = None
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
            if mode == "required":
                head.require_stream()
            else:
                stream = head.stream_frames()
                if mode == "connected":
                    assert (await asyncio.wait_for(anext(stream), timeout=1))[0] == jpeg
                else:
                    with pytest.raises(HeadError, match="camera stream unavailable"):
                        await asyncio.wait_for(anext(stream), timeout=1)
            release.set()
            with pytest.raises(HeadError, match="superseded by live stream"):
                await asyncio.wait_for(still, timeout=1)
            if mode == "connected":
                assert head._last_camera == (17, 1, 1000)
                assert head._stream_latest == jpeg
                receipt = await head.snapshot(
                    require_live_stream=True,
                    include_stream_receipt=True,
                    include_stream_identity=True,
                )
                assert receipt[0] == jpeg
                assert receipt[2] == (17, 1, 1000)
                assert receipt[3] == head._stream_generation
            else:
                assert head._last_camera is None
                assert head._stream_latest is None
        finally:
            release.set()
            await asyncio.gather(still, return_exceptions=True)
            if stream is not None:
                await stream.aclose()


def test_mjpeg_stream_parser_handles_split_headers_and_frame_bodies():
    from desk_robot.transport import _MjpegFrames

    first = b"\xff\xd8one\xff\xd9"
    second = b"\xff\xd8two\xff\xd9"
    wire = _stream_part(1, first) + _stream_part(2, second)
    reader = _MjpegFrames()
    frames = []
    for step in (wire[:7], wire[7:66], wire[66:124], wire[124:130], wire[130:]):
        frames.extend(reader.feed(step))
    assert frames == [(first, (17, 1, 1000)), (second, (17, 2, 2000))]
    assert reader.buffer == bytearray()


@pytest.mark.parametrize("corrupt", [
    _stream_part(1, b"\xff\xd8missing-end"),
    _stream_part(1).replace(b"Content-Length: 10", b"Content-Length: 9999999"),
    _stream_part(1).replace(b"X-Desk-Camera-Sequence: 1",
                            b"X-Desk-Camera-Sequence: -1"),
    _stream_part(1).replace(b"Content-Type: image/jpeg",
                            b"Content-Type: text/html"),
    b"--unexpected\r\nContent-Length: 10\r\n\r\n1234567890\r\n",
])
def test_mjpeg_stream_refuses_malformed_or_truncated_frames(corrupt):
    from desk_robot.transport import _MjpegFrames
    with pytest.raises(ValueError):
        _MjpegFrames().feed(corrupt)


@pytest.mark.parametrize("cut", [3, 45, -4, -1])
async def test_mjpeg_eof_rejects_partial_part_and_clears_stream(settings, tokens, cut):
    complete = _stream_part(1)
    partial = _stream_part(2)[:cut]

    async def handler(request):
        return httpx.Response(
            200,
            headers={"content-type": "multipart/x-mixed-replace; boundary=deskrobotframe"},
            content=complete + partial,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client, strict_capture=True)
        frames = head.stream_frames()
        first, _ = await anext(frames)
        assert first == b"\xff\xd8camera\xff\xd9"
        with pytest.raises(HeadError, match="Truncated MJPEG part at end of stream"):
            await anext(frames)
        assert not head._stream_connected
        assert head._stream_latest is None
        assert head._last_camera == (17, 1, 1000)


async def test_mjpeg_eof_accepts_complete_parts(settings, tokens):
    async def handler(request):
        return httpx.Response(
            200,
            headers={"content-type": "multipart/x-mixed-replace; boundary=deskrobotframe"},
            content=_stream_part(1),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client, strict_capture=True)
        frames = [jpeg async for jpeg, _ in head.stream_frames()]
        assert frames == [b"\xff\xd8camera\xff\xd9"]
        assert not head._stream_connected
        assert head._stream_latest is None


async def test_persistent_mjpeg_video_feeds_existing_snapshot_callers(settings, tokens):
    payload_a = b"\xff\xd8first\xff\xd9"
    payload_b = b"\xff\xd8second\xff\xd9"
    calls = []

    async def handler(request):
        calls.append(request.url.path)
        assert request.url.path == "/api/camera.mjpg"
        assert request.headers["Authorization"] == (
            "Bearer " + tokens[settings.robots[0].token_env]
        )
        return httpx.Response(
            200,
            headers={"content-type": "multipart/x-mixed-replace; boundary=deskrobotframe"},
            content=_stream_part(1, payload_a) + _stream_part(2, payload_b),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client, strict_capture=True)
        frames = head.stream_frames()
        # A single network read may contain several complete frames. The
        # live consumer receives only the newest, never a stale backlog.
        newest, _ = await anext(frames)
        assert newest == payload_b
        assert await head.snapshot() == newest
        assert head._last_camera == (17, 2, 2000)
        assert calls == ["/api/camera.mjpg"]
        await frames.aclose()
        assert not head._stream_connected



async def test_visual_stream_outage_never_silently_falls_back_to_jpeg_polls(
    settings, tokens,
):
    calls = []

    async def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, content=b"\xff\xd8fallback\xff\xd9")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client, strict_capture=True)
        head.require_stream()
        with pytest.raises(HeadError, match="stream is not connected"):
            await head.snapshot()
        assert calls == []  # No hidden /api/camera.jpg polling.


async def test_mjpeg_duplicate_camera_identity_cannot_replay_frame(settings, tokens):
    async def handler(request):
        return httpx.Response(
            200,
            headers={"content-type": "multipart/x-mixed-replace; boundary=deskrobotframe"},
            content=_stream_part(1) + _stream_part(1),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client, strict_capture=True)
        frames = head.stream_frames()
        # Validate every identity before exposing even the first frame of
        # a coalesced network read. A replay poisons the entire batch.
        with pytest.raises(HeadError, match="stale or replayed"):
            await anext(frames)
        await frames.aclose()
        assert not head._stream_connected



async def test_mjpeg_stream_rejects_old_boot_replay_after_real_head_reset(
    settings, tokens,
):
    """The same boot lease covers continuous MJPEG, not just still JPEG."""
    async def handler(request):
        return httpx.Response(
            200, headers={
                "content-type":
                    "multipart/x-mixed-replace; boundary=deskrobotframe",
            },
            content=(
                _stream_part(1, boot=12)
                + _stream_part(1, boot=13)
                + _stream_part(2, boot=12)
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client, strict_capture=True)
        frames = head.stream_frames()
        try:
            # Retired boot replay inside one coalesced read must fail
            # before any frame from that read reaches a vision consumer.
            with pytest.raises(HeadError, match="retired boot"):
                await anext(frames)
            assert head._last_camera == (13, 1, 1000)
        finally:
            await frames.aclose()
        assert not head._stream_connected



def test_calibration_rejects_examples_and_degenerate_geometry(settings):
    path = settings.robots[0].calibration
    c = Calibration.load(path)
    assert c.ground((100, 100)) == pytest.approx((100, 100))
    data = json.loads(path.read_text())
    data["measured"] = False
    with pytest.raises(ValueError, match="unmeasured"):
        Calibration.model_validate(data).verify_ready()
    data["pixel_points"] = [[0, 0], [10, 0], [20, 0], [30, 0]]
    with pytest.raises(ValueError, match="collinear"):
        Calibration.model_validate(data)


def test_nonfinite_calibration_rejected(settings):
    data = json.loads(settings.robots[0].calibration.read_text())
    data["grip_ground_mm"] = [float("nan"), 100]
    with pytest.raises(ValueError):
        Calibration.model_validate(data)


def test_usb_bench_reads_five_real_range_slots_without_arming():
    status = {
        "backend": "stepper_28byj48", "armed": False,
        "imu": {"family": 1, "gyro_id": 212, "aux_id": 73},
        "touch": {"active": False, "count": 2},
        "safety": {"required": True, "ready": False, "fault": "missing_sample", "sensor": 0},
        "ranges": {
            "mm": [50, 51, 49, 52, 200],
            "age_ms": [9, 10, 11, 12, 14],
            "present_mask": 31, "valid_mask": 31,
        },
    }
    result = inspect_status(status)
    assert [s["position"] for s in result["ranges"]] == [
        "front_left", "front_right", "rear_left", "rear_right", "forward",
    ]
    assert [s["distance_mm"] for s in result["ranges"]] == [50, 51, 49, 52, 200]
    assert result["eligible_for_manual_local_rearm"]
    assert result["imu"]["family"] == "berryimu_v1"
    assert result["imu"]["gyro_who_am_i"] == 212
    assert result["imu"]["raw_six_axis_available"] is False
    assert result["imu"]["attitude_interlock_active"] is None
    assert result["local_guard_fault"] == "missing_sample"
    assert not result["physical_qualification_pass"]
    status["ranges"]["present_mask"] = 23
    status["ranges"]["valid_mask"] = 15
    result = inspect_status(status)
    assert not result["ranges"][3]["present"]
    assert not result["ranges"][4]["valid"]
    assert not result["eligible_for_manual_local_rearm"]


def test_usb_bench_reports_raw_six_axis_without_claiming_tilt_safety():
    status = {
        "backend": "stepper_28byj48", "armed": False,
        "imu": {"family": 1, "gyro_id": 212, "aux_id": 73,
                "valid": True, "acc": [-32768, 0, 16384],
                "gyro": [-25, 33, 125], "age_ms": 20},
        "touch": {"active": False},
        "safety": {"ready": False, "fault": "missing_sample"},
        "ranges": {"mm": [50, 50, 50, 50, 200],
                   "age_ms": [5, 6, 7, 8, 9],
                   "present_mask": 31, "valid_mask": 31},
    }
    result = inspect_status(status)
    assert result["imu"]["raw_six_axis_available"] is True
    assert result["imu"]["attitude_interlock_active"] is None
    assert result["imu"]["accelerometer_raw"] == [-32768, 0, 16384]
    assert result["imu"]["gyroscope_raw"] == [-25, 33, 125]
    assert result["imu"]["sample_age_ms"] == 20
    assert result["physical_qualification_pass"] is False
    assert result["imu"]["physical_qualification_pass"] is False

    for bad in (
        {"valid": True, "acc": [1, 2, 3], "gyro": [4, 5, 6], "age_ms": 201},
        {"valid": True, "acc": [1, 2, 3], "gyro": [4, 5, 6], "age_ms": -1},
        {"valid": True, "acc": [1, 2, 32768], "gyro": [4, 5, 6], "age_ms": 1},
        {"valid": True, "acc": [1, 2, 3], "gyro": [4, 5], "age_ms": 1},
        {"valid": 1, "acc": [1, 2, 3], "gyro": [4, 5, 6], "age_ms": 1},
        {"valid": True, "acc": [1, 2, 3], "gyro": [4, 5, 6], "age_ms": "1"},
        {"valid": True, "acc": [1, 2, 3], "gyro": [4, 5, 6], "age_ms": 1,
         "family": 0},
    ):
        mutated = dict(status)
        mutated["imu"] = {**status["imu"], **bad}
        with pytest.raises(ValueError):
            inspect_status(mutated)


def test_usb_mpu6050_raw_diagnostic_and_family_validation():
    status = {
        "backend": "stepper_28byj48", "armed": False,
        "touch": {"active": False},
        "safety": {"required": True, "ready": False, "fault": "missing_sample"},
        "ranges": {"mm": [40, 40, 40, 40, 250],
                   "age_ms": [10, 10, 10, 10, 10],
                   "present_mask": 31, "valid_mask": 31},
        "imu": {"family": 4, "gyro_id": 0x68, "aux_id": 0,
                "valid": True, "acc": [0, 0, 16384],
                "gyro": [0, 0, -12], "age_ms": 20},
    }
    result = inspect_status(status)
    assert result["imu"]["family"] == "mpu6050"
    assert result["imu"]["raw_six_axis_available"] is True
    assert result["imu"]["attitude_interlock_active"] is None
    assert result["imu"]["physical_qualification_pass"] is False
    for bad in ({"gyro_id": 0}, {"aux_id": 3}, {"family": 5}, {"age_ms": 201}):
        changed = {**status, "imu": {**status["imu"], **bad}}
        with pytest.raises(ValueError):
            inspect_status(changed)


def test_usb_optional_sensor_mask_levels_and_bumper_manual_rearm_gate():
    status = {
        "backend": "stepper_28byj48", "armed": False,
        "touch": {"active": False},
        "safety": {"ready": True, "fault": "none"},
        "ranges": {"mm": [35, 35, 35, 35, 300],
                   "age_ms": [5, 5, 5, 5, 5],
                   "present_mask": 31, "valid_mask": 31},
        "extras": {"mask": 7, "bumper": True, "bumps": 1,
                   "reed": False, "reed_count": 2,
                   "pir": True, "pir_count": 3},
    }
    result = inspect_status(status)
    assert result["optional_inputs"]["enabled_mask"] == 7
    assert result["optional_inputs"]["pir_events"] == 3
    assert result["optional_inputs"]["bumper_events"] == 1
    assert not result["eligible_for_manual_local_rearm"]
    assert not result["optional_inputs"]["physical_qualification_pass"]
    for bad in (
        {"mask": 8}, {"mask": True}, {"bumper": 1}, {"bumps": -1},
        {"reed_count": 2**32}, {"pir": "true"},
    ):
        changed = {**status, "extras": {**status["extras"], **bad}}
        with pytest.raises(ValueError):
            inspect_status(changed)
    changed = {**status, "extras": {**status["extras"], "mask": 0}}
    with pytest.raises(ValueError, match="Unenabled"):
        inspect_status(changed)




def test_usb_extra_left_right_rear_ranges_are_read_only_and_source_checked():
    base = {
        "backend": "stepper_28byj48", "armed": False,
        "touch": {"active": False},
        "safety": {"ready": False, "fault": "missing_sample"},
        "ranges": {"mm": [50, 50, 50, 50, 200],
                   "age_ms": [1, 1, 1, 1, 1],
                   "present_mask": 31, "valid_mask": 31},
        "side_ranges": {"mm": [310, 295, 0], "age_ms": [6, 7, 0],
                        "present_mask": 3, "valid_mask": 3,
                        "motion_certified": False},
    }
    report = inspect_status(base)
    assert report["side_ranges"]["reported"]
    assert [v["direction"] for v in report["side_ranges"]["readings"]] == [
        "left", "right", "rear",
    ]
    assert report["side_ranges"]["readings"][2]["present"] is False
    assert not report["side_ranges"]["motion_certified"]
    assert not report["side_ranges"]["physical_qualification_pass"]
    for change in (
        {"valid_mask": 7}, {"present_mask": 8}, {"valid_mask": True},
        {"mm": [1, 2]}, {"mm": [0, 20, 0]},
        {"age_ms": [1, -1, 0]}, {"motion_certified": True},
        {"motion_certified": "false"},
    ):
        invalid = {**base, "side_ranges": {**base["side_ranges"], **change}}
        with pytest.raises(ValueError):
            inspect_status(invalid)
    without = dict(base)
    without.pop("side_ranges")
    assert inspect_status(without)["side_ranges"]["reported"] is False

def test_usb_cap1188_eight_touch_zones_are_diagnostic_not_motion_authority():
    status = {
        "backend": "stepper_28byj48", "armed": False,
        "touch": {"active": False},
        "safety": {"ready": False, "fault": "missing_sample"},
        "ranges": {"mm": [50, 50, 50, 50, 200],
                   "age_ms": [1, 1, 1, 1, 1],
                   "present_mask": 31, "valid_mask": 31},
        "extras": {"mask": 0, "bumper": False, "bumps": 0,
                   "reed": False, "reed_count": 0,
                   "pir": False, "pir_count": 0,
                   "cap": 0b10000001, "cap_ok": True, "cap_events": 7},
    }
    report = inspect_status(status)
    assert report["cap_touch"]["zone_mask"] == 129
    assert report["cap_touch"]["rising_zone_events"] == 7
    assert report["cap_touch"]["valid"]
    assert not report["cap_touch"]["physical_qualification_pass"]
    # Optional petting never grants nor revokes local USB safety recovery.
    # The diagnostic must be identical to an otherwise identical body status
    # with CAP fields absent. Actual WROOM guard remains authoritative.
    without_cap = {
        **status, "extras": {
            key: value for key, value in status["extras"].items()
            if key not in ("cap", "cap_ok", "cap_events")
        },
    }
    assert (report["eligible_for_manual_local_rearm"] ==
            inspect_status(without_cap)["eligible_for_manual_local_rearm"])
    for broken in (
        {"cap": 256}, {"cap": -1}, {"cap": True},
        {"cap_ok": 1}, {"cap_events": -2},
        {"cap_events": 2**32},
        {"cap": 1, "cap_ok": False},
    ):
        corrupted = {**status, "extras": {**status["extras"], **broken}}
        with pytest.raises(ValueError):
            inspect_status(corrupted)
    incomplete = {**status, "extras": {key: value for key, value
                                     in status["extras"].items()
                                     if key != "cap_events"}}
    with pytest.raises(ValueError):
        inspect_status(incomplete)

@pytest.mark.parametrize("change", [
    {"backend": "dc_pwm"},
    {"imu": {"family": 5, "gyro_id": 0, "aux_id": 0}},
    {"imu": {"family": 4, "gyro_id": 0, "aux_id": 0}},
    {"imu": {"family": True, "gyro_id": 212, "aux_id": 73}},
    {"touch": {"active": "false"}},
    {"safety": None},
    {"ranges": {}},
    {"ranges": {"mm": [1] * 5, "age_ms": [1] * 5,
                "present_mask": True, "valid_mask": 31}},
    {"ranges": {"mm": [1] * 5, "age_ms": [1] * 5,
                "present_mask": 63, "valid_mask": 31}},
    {"ranges": {"mm": [1, 2, 3], "age_ms": [1] * 5,
                "present_mask": 31, "valid_mask": 31}},
])
def test_usb_bench_rejects_malformed_or_wrong_profile_status(change):
    status = {
        "backend": "stepper_28byj48", "armed": False,
        "touch": {"active": False},
        "safety": {"ready": False, "fault": "missing_sample"},
        "ranges": {"mm": [50, 50, 50, 50, 200],
                   "age_ms": [2, 2, 2, 2, 2],
                   "present_mask": 31, "valid_mask": 31},
    }
    status.update(change)
    with pytest.raises(ValueError):
        inspect_status(status)


async def test_replaced_mjpeg_stream_cannot_publish_or_clear_new_stream(settings, tokens):
    """An old reader finishing after reconnect must not erase fresh camera state."""
    import asyncio

    old_release = asyncio.Event()
    first = b"\xff\xd8old\xff\xd9"
    stale = b"\xff\xd8stale\xff\xd9"
    fresh = b"\xff\xd8fresh\xff\xd9"
    requests = 0

    class Feed(httpx.AsyncByteStream):
        def __init__(self, old):
            self.old = old

        async def __aiter__(self):
            if self.old:
                yield _stream_part(1, first)
                await old_release.wait()
                yield _stream_part(3, stale)
            else:
                yield _stream_part(2, fresh)

        async def aclose(self):
            pass

    async def handler(request):
        nonlocal requests
        requests += 1
        return httpx.Response(
            200,
            headers={"content-type": "multipart/x-mixed-replace; boundary=deskrobotframe"},
            stream=Feed(requests == 1),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client, strict_capture=True)
        old = head.stream_frames()
        assert (await anext(old))[0] == first
        replacement = head.stream_frames()
        assert (await anext(replacement))[0] == fresh
        old_release.set()
        with pytest.raises(HeadError, match="Superseded"):
            await anext(old)
        await old.aclose()
        assert head._stream_connected
        assert head._stream_latest == fresh
        assert head._last_camera == (17, 2, 2000)
        assert await head.snapshot() == fresh
        await replacement.aclose()
        assert not head._stream_connected


@pytest.mark.parametrize("ok", [
    None, 0, 1, "true", "false", [], {}, False,
])
async def test_head_command_ack_requires_json_boolean_true(settings, tokens, ok):
    """A truthy nonboolean ACK must not authorize more physical motion."""
    import httpx

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={
            "ok": ok, "reply": "OK drive left=20 right=20 ms=100",
            "robot_id": "robot-01",
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client)
        with pytest.raises(HeadError, match="Unmatched or failed command ACK"):
            await head.command("drive 20 20 100")
        assert len(calls) == 1


@pytest.mark.parametrize("payload", [[], ["yes"], "OK", 1, True, None])
@pytest.mark.parametrize("endpoint", ["/api/status", "/api/command"])
async def test_head_rejects_nonobject_status_or_motion_ack(
    settings, tokens, payload, endpoint,
):
    """Typed JSON payloads are mandatory before any ACK can be trusted."""
    import httpx

    def handler(request):
        assert request.url.path == endpoint
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client)
        with pytest.raises(HeadError):
            if endpoint == "/api/status":
                await head.status()
            else:
                await head.command("drive 20 20 100")


@pytest.mark.parametrize("path,method", [
    ("/api/command", "command"),
    ("/api/status", "status"),
    ("/api/aux", "aux_status"),
    ("/api/ir", "ir_status"),
])
@pytest.mark.parametrize("payload", [b"<html>gateway error</html>", b"{", b"[]", b"null"])
async def test_authenticated_transport_rejects_malformed_json_as_head_error(
    settings, tokens, path, method, payload,
):
    """HTTP success is not a valid WROOM receipt without a JSON object."""
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        assert request.url.path == path
        return httpx.Response(200, content=payload, headers={"content-type": "application/json"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client)
        with pytest.raises(HeadError, match="Malformed authenticated head JSON"):
            if method == "command":
                await head.command("drive 20 20 100")
            else:
                await getattr(head, method)()
        assert len(seen) == 1
        assert seen[0][1] == path


async def test_failed_replacement_mjpeg_stream_cannot_revive_old_reader(settings, tokens):
    """Failed reconnect must leave camera unavailable, not restore old frames."""
    import asyncio

    release_old = asyncio.Event()
    old_frame = b"\xff\xd8old\xff\xd9"
    calls = 0

    class OldFeed(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield _stream_part(1, old_frame)
            await release_old.wait()
            yield _stream_part(2, b"\xff\xd8stale\xff\xd9")

        async def aclose(self):
            pass

    async def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                headers={"content-type": "multipart/x-mixed-replace; boundary=deskrobotframe"},
                stream=OldFeed(),
            )
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client, strict_capture=True)
        head.require_stream()
        old = head.stream_frames()
        assert (await anext(old))[0] == old_frame
        replacement = head.stream_frames()
        with pytest.raises(HeadError, match="camera stream unavailable"):
            await anext(replacement)
        assert not head._stream_connected
        assert head._stream_latest is None
        release_old.set()
        with pytest.raises(HeadError, match="Superseded"):
            await anext(old)
        await old.aclose()
        assert not head._stream_connected
        assert head._stream_latest is None
        with pytest.raises(HeadError, match="not connected"):
            await head.snapshot()
        assert calls == 2


async def test_contextual_mood_cue_is_authenticated_and_never_motor(
    settings, tokens,
):
    robot = settings.robots[0]
    observed = []

    def reply(req):
        observed.append(req)
        assert req.url.path == "/api/face"
        assert req.headers["authorization"] == "Bearer " + tokens[robot.token_env]
        assert json.loads(req.content) == {"event": "mood:thinking"}
        return httpx.Response(200, json={
            "ok": True, "reply": "mood cue queued", "robot_id": robot.id,
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        head = HttpHead(robot, client)
        await head.face_event("mood:thinking")
        assert len(observed) == 1
        for illegal in ("mood:move", "mood:speak", "mood:angry", {}):
            with pytest.raises(ValueError, match="Unsupported cosmetic"):
                await head.face_event(illegal)
        assert len(observed) == 1

    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={
            "ok": True, "reply": "mood cue queued", "robot_id": "robot-02",
        })
    )) as client:
        with pytest.raises(HeadError, match="Cosmetic face cue"):
            await HttpHead(robot, client).face_event("mood:thinking")


async def test_authenticated_person_face_cue_is_cosmetic_and_identity_bound(
    settings, tokens,
):
    calls = []
    robot = settings.robots[0]

    async def handler(request):
        calls.append(request)
        assert request.url.path == "/api/face"
        assert request.method == "POST"
        assert request.headers["Authorization"] == (
            "Bearer " + tokens[robot.token_env]
        )
        assert json.loads(request.content) == {"event": "person_detected"}
        return httpx.Response(
            200, json={"ok": True, "reply": "person cue queued",
                       "robot_id": robot.id},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(robot, client)
        await head.face_event("person_detected")
        assert len(calls) == 1
        for unsupported in ("person_lost", "arm", "move", "", None, 1):
            with pytest.raises(ValueError, match="Unsupported cosmetic"):
                await head.face_event(unsupported)
        assert len(calls) == 1


async def test_person_face_cue_rejects_wrong_robot_or_missing_ack(
    settings, tokens,
):
    robot = settings.robots[0]
    for response in (
        {"ok": True, "reply": "person cue queued", "robot_id": "robot-02"},
        {"ok": False, "reply": "person cue queued", "robot_id": robot.id},
        {"ok": True, "reply": "wrong text", "robot_id": robot.id},
    ):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda req, captured=response: httpx.Response(200, json=captured)
            )
        ) as client:
            head = HttpHead(robot, client)
            with pytest.raises(HeadError, match="Cosmetic face cue"):
                await head.face_event("person_detected")


@pytest.mark.parametrize(
    "sensor_pid, raw_pid",
    [("OV2640", 0x26), ("OV3660", 0x3660), ("OV5640", 0x5640)],
)
async def test_actual_xiao_camera_pid_is_bound_to_authenticated_jpeg_boot(
    settings, tokens, sensor_pid, raw_pid,
):
    requests = []

    async def handler(request):
        requests.append(request.url.path)
        if request.url.path == "/api/camera.jpg":
            return httpx.Response(200, headers={
                "X-Desk-Camera-Robot-Id": settings.robots[0].id,
                "X-Desk-Camera-Boot": "41",
                "X-Desk-Camera-Sequence": "1",
                "X-Desk-Camera-Complete-Us": "9000",
            }, content=b"\xff\xd8camera\xff\xd9")
        if request.url.path == "/api/camera.identity":
            return httpx.Response(200, json={
                "robot_id": settings.robots[0].id,
                "camera_sensor_pid": sensor_pid,
                "camera_pid_raw": raw_pid,
                "boot": 41,
            })
        raise AssertionError("Unexpected camera request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client, strict_capture=True)
        assert (await head.snapshot()).startswith(b"\xff\xd8")
        assert await head.camera_identity() == sensor_pid
        assert requests == ["/api/camera.jpg", "/api/camera.identity"]


@pytest.mark.parametrize("override", [
    {"camera_sensor_pid": "OV3660", "camera_pid_raw": 0x5640},
    {"camera_sensor_pid": "OV2640", "camera_pid_raw": 0x2642},
    {"camera_sensor_pid": "OV2640", "camera_pid_raw": 0x2640},
    {"camera_sensor_pid": "OV5640", "camera_pid_raw": True},
    {"camera_sensor_pid": "OV5640", "camera_pid_raw": 0x3660},
    {"camera_sensor_pid": "OV5640", "boot": 42},
    {"camera_sensor_pid": "OV5640", "boot": True},
    {"robot_id": "another-robot"},
])
async def test_camera_identity_mismatch_never_qualifies_dock_sensor(
    settings, tokens, override,
):
    async def handler(request):
        if request.url.path == "/api/camera.jpg":
            return httpx.Response(200, headers={
                "X-Desk-Camera-Robot-Id": settings.robots[0].id,
                "X-Desk-Camera-Boot": "41",
                "X-Desk-Camera-Sequence": "1",
                "X-Desk-Camera-Complete-Us": "9000",
            }, content=b"\xff\xd8camera\xff\xd9")
        if request.url.path == "/api/camera.identity":
            body = {
                "robot_id": settings.robots[0].id,
                "camera_sensor_pid": "OV5640",
                "camera_pid_raw": 0x5640,
                "boot": 41,
            }
            body.update(override)
            return httpx.Response(200, json=body)
        raise AssertionError("Unexpected request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client, strict_capture=True)
        await head.snapshot()
        expected_error = ("Invalid camera identity boot"
                          if override.get("boot") is True
                          else "Camera (sensor PID|identity)")
        with pytest.raises(HeadError, match=expected_error):
            await head.camera_identity()


async def test_dock_uses_recent_stream_receipt_without_still_capture(
    settings, tokens,
):
    """A previously cached 0.5s-old JPEG cannot steer a physical dock job."""
    import asyncio
    import time

    requests = []

    def handler(request):
        requests.append(request.url.path)
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client, strict_capture=True)
        with pytest.raises(HeadError, match="connected live camera stream"):
            await head.snapshot_for_dock()
        head._stream_connected = True
        head._stream_latest = b"\xff\xd8dock\xff\xd9"
        head._stream_version = 1
        head._last_camera = (41, 1, 9000)
        head._stream_generation = 3
        head._stream_received_at = time.monotonic() - 0.5
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(head.snapshot_for_dock(), timeout=0.06)
        assert head._snapshot_version == 0
        head._stream_received_at = time.monotonic()
        frame, received, source_identity, stream_generation = await head.snapshot_for_dock()
        assert frame == b"\xff\xd8dock\xff\xd9"
        assert source_identity == (41, 1, 9000)
        assert stream_generation == 3
        assert 0 <= time.monotonic() - received <= 0.20
        assert head._snapshot_version == 1
        assert requests == []


@pytest.mark.parametrize("bad", [0, -1, 1.5, True, float("nan")])
async def test_invalid_dock_camera_age_bound_never_starts_capture(
    settings, tokens, bad,
):
    async with httpx.AsyncClient() as client:
        head = HttpHead(settings.robots[0], client, strict_capture=True)
        with pytest.raises(ValueError, match="receipt age limit"):
            await head.snapshot(max_stream_age_seconds=bad)


async def test_dock_stream_disconnect_while_waiting_for_camera_lock_never_polls(
    settings, tokens,
):
    """A late stream teardown cannot redirect docking to /api/camera.jpg."""
    import asyncio
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, content=b"invalid standalone jpeg")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client, strict_capture=True)
        head._stream_connected = True
        head._stream_version = 1
        await head.capture_lock.acquire()
        capture = asyncio.create_task(head.snapshot_for_dock())
        try:
            await asyncio.sleep(0)
            head._stream_connected = False
        finally:
            head.capture_lock.release()
        with pytest.raises(
            HeadError, match="stream is not connected|connected live camera stream"
        ):
            await capture
        assert paths == []

@pytest.mark.parametrize(("field", "first_value"), [
    ("measured", "false"),
    ("measured", "true"),
    ("ground_points_mm", "[[0, 0]]"),
])
def test_pickup_calibration_load_refuses_ambiguous_json_fields(
    settings, tmp_path, field, first_value,
):
    # Coordinator.pickup calls Calibration.load before submitting any job.
    data = json.loads(settings.robots[0].calibration.read_text())
    data["measured"] = True
    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps(data))
    assert Calibration.load(valid).measured is True

    ambiguous = tmp_path / "ambiguous.json"
    ambiguous.write_text(
        '{"' + field + '": ' + first_value + "," + json.dumps(data)[1:]
    )
    with pytest.raises(ValueError, match=f"Duplicate calibration JSON field: {field}"):
        Calibration.load(ambiguous)
