"""Pass real NEC decoder and queue-gate observations through the Mac validator."""

import shutil
import subprocess
from pathlib import Path

import pytest
from desk_robot.dock_ir import dock_beacon_code, validate_ir

BODY = Path(__file__).resolve().parents[1] / "firmware/body"
NEC = BODY / "lib/TerminalIr"


def _receipt(line: str) -> dict:
    keys = (
        "left_valid", "right_valid", "match", "left_seq", "right_seq",
        "left_age_ms", "right_age_ms", "code", "left_code", "right_code",
        "motor_authorized", "charging_authorized",
    )
    data = dict(zip(keys, map(int, line.split()), strict=True))
    for key in ("left_valid", "right_valid", "match", "motor_authorized", "charging_authorized"):
        assert data[key] in (0, 1)
        data[key] = bool(data[key])
    return {**data, "robot_id": "robot-01", "physical_qualified": False}


@pytest.fixture(scope="module")
def firmware_receipts(tmp_path_factory):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ required for NEC cross-layer host test")
    directory = tmp_path_factory.mktemp("nec_receipts")
    binary = directory / "terminal_ir_poll_tests"
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-DDESK_ROBOT_STEPPER=1",
         "-I", str(BODY / "tests/fakes/terminal_ir"), "-I", str(NEC),
         str(BODY / "tests/terminal_ir_poll_tests.cpp"), str(NEC / "TerminalIr.cpp"),
         "-o", str(binary)], check=True, capture_output=True, text=True,
    )
    output = subprocess.run(
        [str(binary), "--emit-mac-receipts"], check=True, capture_output=True, text=True,
    )
    receipts = [_receipt(line) for line in output.stdout.splitlines()]
    assert len(receipts) == 80
    return receipts


@pytest.mark.parametrize("dock_id", range(1, 6))
@pytest.mark.parametrize("saturated_side", [0, 1])
def test_firmware_receipts_match_mac_validator(firmware_receipts, dock_id, saturated_side):
    start = ((dock_id - 1) * 2 + saturated_side) * 8
    rows = firmware_receipts[start:start + 8]
    expected_code = dock_beacon_code(dock_id)
    assert [row["match"] for row in rows] == [True, True, False, False, True, False, False, True]
    assert [row["left_seq"] for row in rows] == [1, 1, 1, 1, 2, 2, 2, 3]
    assert [row["right_seq"] for row in rows] == [1, 1, 1, 1, 2, 2, 2, 3]
    for row in rows:
        assert validate_ir(row, "robot-01", expected_dock_id=dock_id) is row
        assert row["code"] == row["left_code"] == row["right_code"] == (
            expected_code if row["match"] else 0
        )
        assert row["left_valid"] is row["right_valid"] is row["match"]
        assert not row["motor_authorized"] and not row["charging_authorized"]
    assert rows[1]["left_age_ms"] == 200
    assert rows[2]["left_age_ms"] == 201
    with pytest.raises(ValueError, match="Fresh NEC"):
        validate_ir(rows[1], "robot-01", expected_dock_id=dock_id, elapsed_ms=1)
    with pytest.raises(ValueError, match="Foreign NEC"):
        validate_ir(rows[0], "robot-01", expected_dock_id=dock_id % 5 + 1)
