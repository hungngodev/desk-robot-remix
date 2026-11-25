"""Exercise actual spawned workers, including an unreturning native-call surrogate."""
import asyncio
import os
import signal
import sys
import time

import pytest
from desk_robot.dock_process import DetectorPool, DockDetectorBusy
from desk_robot.dock_vision import DockCameraCalibration

CAMERA = DockCameraCalibration(410, 410, 320, 240, 60, 12)
FAKE_WORKER = r'''
import base64, json, os, sys, time
print("ready", flush=True)
for line in sys.stdin:
    request = json.loads(line)
    image = base64.b64decode(request["jpeg"])
    if image == b"hang":
        time.sleep(60)
    elif image == b"crash":
        os._exit(23)
    elif image == b"malformed":
        print("not-json", flush=True)
        continue
    elif image == b"oversized":
        print("x" * 100000, flush=True)
        continue
    elif image == b"duplicate":
        print('{"id":0,"id":%d,"pose":null}' % request["id"], flush=True)
        continue
    result = {"id": request["id"], "pose": {
        "x_mm": 0, "y_mm": 0, "z_mm": 400, "reprojection_error_px": 0.5,
        "captured_at": request["captured_at"],
    }}
    if image == b"wrong-id":
        result["id"] -= 1
    elif image == b"wrong-clock":
        result["pose"]["captured_at"] -= 1
    elif image == b"nan":
        result["pose"]["z_mm"] = float("nan")
    elif image == b"fresh":
        result["pose"]["z_mm"] = 450
    print(json.dumps(result), flush=True)
'''


@pytest.fixture
def pool():
    return DetectorPool((sys.executable, "-u", "-c", FAKE_WORKER))


async def request(pool, jpeg=b"fresh"):
    return await pool.detect(jpeg, CAMERA, captured_at=time.monotonic())


@pytest.mark.parametrize("failure", [
    b"hang", b"crash", b"malformed", b"oversized", b"duplicate", b"wrong-id",
    b"wrong-clock", b"nan",
])
async def test_failed_child_is_reaped_then_fresh_frame_uses_warm_spare(pool, failure):
    await pool.prewarm()
    assert len(pool._ready) == 2
    failed, spare = pool._ready
    try:
        start = time.monotonic()
        with pytest.raises((TimeoutError, ValueError, RuntimeError)):
            await request(pool, failure)
        assert failed.returncode is not None and failed not in pool._owned
        with pytest.raises(ProcessLookupError):
            os.kill(failed.pid, 0)
        pose = await request(pool)
        assert pose.z_mm == 450
        assert pool._ready[0] is spare
        assert time.monotonic() - start < 0.5
        await pool.prewarm()
        assert len(pool._ready) == 2
        assert failed not in pool._owned
    finally:
        await pool.close()
    assert not pool._owned


async def test_sigstop_native_freeze_cancellation_and_parallel_refusal(pool):
    await pool.prewarm()
    frozen = pool._ready[0]
    os.kill(frozen.pid, signal.SIGSTOP)
    observer = asyncio.create_task(request(pool))
    try:
        await asyncio.sleep(0.02)
        with pytest.raises(DockDetectorBusy):
            await request(pool)
        observer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await observer
        async with asyncio.timeout(0.4):
            while pool._active is not None:
                await asyncio.sleep(0.001)
        assert frozen.returncode == -signal.SIGKILL
        assert (await request(pool)).z_mm == 450
    finally:
        await pool.close()
    assert not pool._owned


async def test_cancel_before_exchange_and_concurrent_close(pool):
    await pool.prewarm()
    active = asyncio.create_task(request(pool, b"hang"))
    await asyncio.sleep(0)
    active.cancel()
    with pytest.raises(asyncio.CancelledError):
        await active
    await asyncio.gather(pool.close(), pool.close())
    assert not pool._owned
    with pytest.raises(DockDetectorBusy):
        await request(pool)


async def test_close_fences_active_frame_and_kills_all_children(pool):
    await pool.prewarm()
    processes = tuple(pool._owned)
    pending = asyncio.create_task(request(pool, b"hang"))
    await asyncio.sleep(0.02)
    await pool.close()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert not pool._owned
    assert all(process.returncode is not None for process in processes)


async def test_cold_and_expired_frames_are_not_queued(pool):
    try:
        with pytest.raises(TimeoutError):
            await pool.detect(b"hang", CAMERA, captured_at=time.monotonic() - 1)
        assert not pool._owned and pool._warming is None
        with pytest.raises(DockDetectorBusy, match="warming"):
            await request(pool, b"hang")
        await pool.prewarm()
        assert (await request(pool)).z_mm == 450
    finally:
        await pool.close()


async def test_real_opencv_worker_receives_generated_jpeg():
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    if not hasattr(cv2, "aruco"):
        pytest.skip("OpenCV vision extra does not provide AprilTag")
    frame = np.full((480, 640), 255, np.uint8)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    frame[160:320, 240:400] = cv2.aruco.generateImageMarker(dictionary, 12, 160)
    ok, jpeg = cv2.imencode(".jpg", frame)
    assert ok
    pool = DetectorPool()
    try:
        await pool.prewarm()
        assert len(pool._ready) == 2
        captured = time.monotonic()
        pose = await pool.detect(jpeg.tobytes(), CAMERA, captured_at=captured)
        assert pose is not None and 140 < pose.z_mm < 170
        assert pose.captured_at == captured
    finally:
        await pool.close()
    assert not pool._owned
