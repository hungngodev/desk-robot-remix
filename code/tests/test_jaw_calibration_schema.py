"""Jaw calibration JSON must preserve exact integer firmware units."""
import json
from pathlib import Path

import pytest
from desk_robot.calibration import Calibration
from pydantic import ValidationError

EXAMPLE = Path(__file__).resolve().parents[1] / "config/calibration.example.json"


@pytest.mark.parametrize("field,value", [
    ("grip_open", "60"),
    ("grip_closed", 110.0),
    ("grip_force_delta_raw", "275"),
    ("grip_force_limit_raw", 960.0),
    ("grip_force_sign", True),
    ("grip_force_sign", "-1"),
    ("grip_step_deg", True),
    ("grip_step_deg", 4.0),
])
def test_jaw_schema_rejects_coerced_integer_fields(tmp_path, field, value):
    payload = json.loads(EXAMPLE.read_text())
    payload.update(grip_force_delta_raw=275, grip_force_limit_raw=960)
    payload[field] = value
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValidationError, match=field):
        Calibration.model_validate(payload)
    with pytest.raises(ValidationError, match=field):
        Calibration.load(path)


@pytest.mark.parametrize("sign", [-1, 1])
def test_jaw_candidate_raw_counts_round_trip_without_approval(tmp_path, sign):
    payload = json.loads(EXAMPLE.read_text())
    payload.update(grip_force_delta_raw=275, grip_force_limit_raw=960,
                   grip_force_sign=sign, grip_step_deg=3)
    model = Calibration.model_validate(payload)
    path = tmp_path / "candidate.json"
    model.save(path)
    loaded = Calibration.load(path)
    assert loaded == model
    assert loaded.measured is False
    with pytest.raises(ValueError, match="unmeasured"):
        loaded.verify_ready()
