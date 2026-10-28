import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/{name}.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_allowances_and_over_budget_are_not_ready():
    budget = module("check_budget").budget
    data = json.loads((ROOT / "hardware/bom.json").read_text())
    result = budget(data)
    assert result["parts_estimate_usd"] == 123.25
    assert not result["purchase_ready"] and result["quoted_total_usd"] is None
    for row in data["items"]:
        row["price_status"] = "verified"
    assert not budget(data, 0, 0)["purchase_ready"]  # mechanical fit still unknown
    data["fit_confirmed"] = True
    assert budget(data, 0, 0)["purchase_ready"]
    assert not budget(data, 30, 10)["purchase_ready"]


def trial(category, n):
    return {
        "robot_id": "robot-01",
        "category": category,
        "trial": str(n),
        "object_description": "Unit test fixture, not a real trial",
        "mass_g": "1",
        "date": "test",
        "firmware": "test",
        "calibration": "test",
        "flat_start": "true",
        "lift_mm": "10",
        "hold_seconds": "3",
        "placed_under_control": "true",
        "assisted": "false",
    }


def test_empty_records_and_assisted_or_propped_keys_do_not_pass():
    summarize = module("check_trials").summarize
    assert not summarize([], "robot-01")["physical_acceptance_pass"]
    rows = [trial(cat, n) for cat in ("key", "candy") for n in range(1, 11)]
    assert summarize(rows, "robot-01")["physical_acceptance_pass"]
    for r in rows[:3]:
        r["flat_start"] = "false"
    assert not summarize(rows, "robot-01")["physical_acceptance_pass"]
    rows.append(rows[-1].copy())
    with pytest.raises(ValueError, match="distinct"):
        summarize(rows, "robot-01")
