"""Reject corrupt status and invalid capture cursors before recording evidence."""
import asyncio
import runpy
from pathlib import Path

import httpx
import pytest

CAPTURE = runpy.run_path(str(Path(__file__).resolve().parents[1] /
                             "scripts/capture_side_ranges.py"))


def frame():
    return {
        "robot_id": "robot-01", "armed": False,
        "motor": {"m0": 0, "m1": 0}, "drive_ms": 0,
        "side_ranges": {
            "mm": [80, 500, 500], "age_ms": [10, 10, 10],
            "sample_ms": [100, 200, 300], "boot_id": 73,
            "valid_mask": 7, "present_mask": 7, "motion_certified": False,
        },
    }


def capture(handler, **overrides):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            options = dict(
                base_url="http://127.0.0.1:8008", robot="robot-01",
                token="operator-private-demo-token", side="left", label="near",
                count=1, interval=.05, firmware_commit="flash-sha", mount_id="mount-a",
                sample_id_start=1,
            )
            options.update(overrides)
            return await CAPTURE["capture_phase"](client, **options)

    return asyncio.run(run())


@pytest.mark.parametrize("overrides", [
    {"count": 0}, {"side": []}, {"label": {}}, {"interval": float("nan")},
    {"previous_ms": -1}, {"previous_ms": True}, {"previous_ms": 2**32},
    {"previous_boot": 0}, {"previous_boot": True}, {"previous_boot": 2**32},
])
def test_invalid_capture_arguments_do_not_poll(overrides):
    def handler(_request):
        pytest.fail("Invalid capture argument triggered a status request")

    with pytest.raises(ValueError, match="Authenticated, labeled"):
        capture(handler, **overrides)


def test_corrupt_status_json_aborts_without_retry():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=b'{"side_ranges":')

    with pytest.raises(RuntimeError, match="Malformed WROOM status JSON"):
        capture(handler)
    assert len(calls) == 1


def test_duplicate_selected_conversion_exhausts_exact_retry_budget():
    calls = []

    def handler(request):
        calls.append(request)
        payload = frame()
        payload["side_ranges"]["sample_ms"][1] += len(calls)
        return httpx.Response(200, json=payload)

    with pytest.raises(RuntimeError, match="Not enough distinct"):
        capture(handler, count=2, previous_ms=100, previous_boot=73)
    assert len(calls) == 20
