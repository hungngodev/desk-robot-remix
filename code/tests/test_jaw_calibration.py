"""Grasp calibration arithmetic never replaces physical servo/force trials."""
import json
import runpy
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
tool = runpy.run_path(str(ROOT / "scripts/calibrate_jaw_fsr.py"))
propose = tool["propose_force_limits"]
capture = tool["capture"]
safe_endpoint = tool["_safe_aux_endpoint"]


def measured_samples():
    return {
        "free": [(100 + (i % 3), i + 1) for i in range(8)],
        "contact": [(700 + (i % 3), i + 9) for i in range(8)],
        "upper": [(2100 + (i % 3), i + 17) for i in range(8)],
    }


def test_recommends_signed_raw_limits_without_marking_physical_success():
    result = propose(measured_samples())
    assert result["grip_force_sign"] == 1
    assert 300 <= result["grip_force_delta_raw"] < 600
    assert result["grip_force_limit_raw"] > result["grip_force_delta_raw"]
    assert not result["newtons_measured"]
    assert not result["physical_force_safety_qualified"]
    assert result["manual_review_required"]


@pytest.mark.parametrize("phase,endpoint", [
    ("free", -32768), ("contact", 32767), ("upper", 32767),
])
def test_adc_clipping_cannot_qualify_force_trial(phase, endpoint):
    samples = measured_samples()
    _, seq = samples[phase][0]
    samples[phase][0] = (endpoint, seq)
    with pytest.raises(ValueError, match="Untrusted"):
        propose(samples)


def test_inverted_adc_polarity_supported():
    samples = measured_samples()
    for rows in samples.values():
        for i, row in enumerate(rows):
            rows[i] = (5000 - row[0], row[1])
    assert propose(samples)["grip_force_sign"] == -1


def test_flat_contact_and_duplicate_or_reordered_hardware_frames_rejected():
    samples = measured_samples()
    samples["contact"] = [(100, i + 9) for i in range(8)]
    with pytest.raises(ValueError):
        propose(samples)
    samples = measured_samples()
    samples["contact"][1] = samples["contact"][0]
    with pytest.raises(ValueError, match="forward hardware conversions"):
        propose(samples)
    samples = measured_samples()
    samples["upper"] = [(730, i + 17) for i in range(8)]
    with pytest.raises(ValueError):
        propose(samples)


async def test_real_jaw_calibration_refuses_missing_wroom_boot_or_age():
    def respond(_request):
        return httpx.Response(200, json={
            "robot_id": "robot-01",
            "force": {"valid": True, "calibrated": False,
                      "adc": [0, 100], "jaw_seq": 1},
        })
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ValueError, match="requires WROOM boot and jaw age"):
            await capture(client, base_url="http://127.0.0.1:8008",
                          robot="robot-01", token="s" * 32,
                          count=5, interval=0.12, boot_state={})


async def test_real_jaw_calibration_rejects_reboot_amid_independent_samples():
    sequence = 0
    def respond(_request):
        nonlocal sequence
        sequence += 1
        return httpx.Response(200, json={
            "robot_id": "robot-01",
            "force": {"valid": True, "jaw_valid": True, "calibrated": False,
                      "adc": [0, 100], "jaw_seq": sequence,
                      "boot_id": 5 if sequence < 3 else 6,
                      "jaw_age_ms": 10},
        })
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ValueError, match="WROOM reboot"):
            await capture(client, base_url="http://127.0.0.1:8008",
                          robot="robot-01", token="s" * 32,
                          count=5, interval=0.12, boot_state={})


async def test_real_jaw_calibration_preserves_boot_across_manual_phases():
    sequence = 0
    current_boot = 17
    def respond(_request):
        nonlocal sequence
        sequence += 1
        return httpx.Response(200, json={
            "robot_id": "robot-01",
            "force": {"valid": True, "jaw_valid": True, "calibrated": False,
                      "adc": [0, 100], "jaw_seq": sequence,
                      "boot_id": current_boot, "jaw_age_ms": 10},
        })
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        shared_boot = {}
        first = await capture(client, base_url="http://127.0.0.1:8008",
                              robot="robot-01", token="s" * 32,
                              count=5, interval=0.12, boot_state=shared_boot)
        assert len(first) == 5 and shared_boot["boot_id"] == 17
        current_boot = 18
        with pytest.raises(ValueError, match="WROOM reboot"):
            await capture(client, base_url="http://127.0.0.1:8008",
                          robot="robot-01", token="s" * 32,
                          count=5, interval=0.12, boot_state=shared_boot)


async def test_capture_requires_independent_jaw_seq_and_reuses_existing_aux():
    next_seq = 0
    def respond(request):
        nonlocal next_seq
        assert request.url.path == "/v1/robots/robot-01/aux"
        assert request.headers["Authorization"] == "Bearer " + "s" * 32
        next_seq += 1
        return httpx.Response(200, json={
            "robot_id": "robot-01",
            "force": {"valid": True, "calibrated": False,
                      "adc": [0, 100], "jaw_seq": next_seq},
        })
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        rows = await capture(client, base_url="http://127.0.0.1:8008",
                             robot="robot-01", token="s" * 32,
                             count=5, interval=0.12)
    assert rows == [(100, seq) for seq in range(1, 6)]


@pytest.mark.parametrize(("origin", "robot"), [
    ("http://example.com:8008", "robot-01"),
    ("http://192.168.1.100:8008", "robot-01"),
    ("http://127.0.0.1:8008/another", "robot-01"),
    ("http://username:password@localhost:8008", "robot-01"),
    ("http://localhost:8008?redirect=1", "robot-01"),
    ("http://localhost:8008#fragment", "robot-01"),
    ("ftp://localhost:8008", "robot-01"),
    ("http://localhost:99999", "robot-01"),
    ("http://localhost:8008\nInjected: 1", "robot-01"),
    ("http://localhost:8008", "robot-01/aux"),
    ("http://localhost:8008", "robot-01?other=1"),
    ("http://localhost:8008", "a" * 41),
])
async def test_jaw_calibration_rejects_bad_bearer_origin_before_http(
    origin, robot,
):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError):
            await capture(
                client, base_url=origin, robot=robot, token="s" * 32,
                count=5, interval=0.12,
            )
    assert calls == []


@pytest.mark.parametrize(("origin", "expected"), [
    ("http://127.0.0.1:8008", "http://127.0.0.1:8008/v1/robots/robot-01/aux"),
    ("http://localhost:8008/", "http://localhost:8008/v1/robots/robot-01/aux"),
    ("http://[::1]:8008", "http://[::1]:8008/v1/robots/robot-01/aux"),
    ("https://robot.example.com", "https://robot.example.com/v1/robots/robot-01/aux"),
])
def test_jaw_calibration_allows_loopback_http_or_verified_https(origin, expected):
    assert safe_endpoint(origin, "robot-01") == expected


@pytest.mark.parametrize("step", [1, 2, 3, 4, None])
async def test_jaw_candidate_preserves_existing_grasp_step(tmp_path, monkeypatch, step):
    source = tmp_path / "grasp.json"
    original = {"measured": True}
    if step is not None:
        original["grip_step_deg"] = step
    source.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setenv("DESK_ROBOT_OPERATOR_TOKEN", "t" * 24)
    monkeypatch.setattr("sys.argv", ["calibrate_jaw_fsr.py", "--calibration", str(source)])
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    main = tool["main"]
    phases = iter(measured_samples().values())

    async def fake_capture(*_args, **_kwargs):
        return next(phases)

    monkeypatch.setitem(main.__globals__, "capture", fake_capture)
    await main()
    candidate = json.loads(
        (tmp_path / "grasp.jaw_candidate.json").read_text(encoding="utf-8")
    )
    assert candidate["grip_step_deg"] == (4 if step is None else step)
    assert candidate["measured"] is False
    assert json.loads(source.read_text(encoding="utf-8")) == original


@pytest.mark.parametrize("step", [True, 0, 5, 1.0, "2", None])
async def test_jaw_candidate_rejects_invalid_existing_grasp_step(tmp_path, monkeypatch, step):
    source = tmp_path / "grasp.json"
    source.write_text(json.dumps({"grip_step_deg": step}), encoding="utf-8")
    monkeypatch.setenv("DESK_ROBOT_OPERATOR_TOKEN", "t" * 24)
    monkeypatch.setattr("sys.argv", ["calibrate_jaw_fsr.py", "--calibration", str(source)])

    def unexpected_prompt(_prompt):
        pytest.fail("Invalid geometry must be rejected before operator prompts")

    monkeypatch.setattr("builtins.input", unexpected_prompt)
    with pytest.raises(ValueError, match="grip_step_deg"):
        await tool["main"]()
    assert not (tmp_path / "grasp.jaw_candidate.json").exists()


async def test_physical_jaw_capture_requires_independent_channel_validity():
    def respond(_request):
        return httpx.Response(200, json={
            "robot_id": "robot-01",
            "force": {"valid": True, "calibrated": False,
                      "adc": [0, 100], "jaw_seq": 1,
                      "boot_id": 17, "jaw_age_ms": 10},
        })
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ValueError, match="independent jaw validity"):
            await capture(client, base_url="http://127.0.0.1:8008",
                          robot="robot-01", token="s" * 32,
                          count=5, interval=0.12, boot_state={})


async def test_physical_jaw_capture_accepts_jaw_when_belly_invalid():
    sequence = 0

    def respond(_request):
        nonlocal sequence
        sequence += 1
        return httpx.Response(200, json={
            "robot_id": "robot-01",
            "force": {"valid": False, "jaw_valid": True, "belly_valid": False,
                      "calibrated": False, "adc": [32767, 100],
                      "jaw_seq": sequence, "boot_id": 17, "jaw_age_ms": 10},
        })
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        rows = await capture(client, base_url="http://127.0.0.1:8008",
                             robot="robot-01", token="s" * 32,
                             count=5, interval=0.12, boot_state={})
    assert rows == [(100, seq) for seq in range(1, 6)]
