import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/{name}.py")
    value = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        spec.loader.exec_module(value)
    finally:
        sys.path.pop(0)
    return value


def test_legacy_budget_exact_cap_with_both_fees():
    budget = module("check_budget").budget
    data = {
        "cap_usd": 50, "fit_confirmed": True,
        "items": [{"item": "sample", "quantity": 3,
                   "unit_usd": "16.66", "price_status": "verified"}],
    }
    exact = budget(data, "0.01", "0.01")
    assert exact["known_subtotal_usd"] == 49.98
    assert exact["quoted_total_usd"] == 50.00
    assert exact["remaining_under_cap_usd"] == 0.00
    assert exact["purchase_ready"] is True
    over = budget(data, "0.01", "0.02")
    assert over["known_landed_subtotal_usd"] == 50.01
    assert over["remaining_under_cap_usd"] == -0.01
    assert over["purchase_ready"] is False
    partial = budget(data, "0.03", None)
    assert partial["known_landed_subtotal_usd"] == 50.01
    assert partial["unknown_landed_fees"] == ["tax"]
    assert partial["quoted_total_usd"] is None
    assert partial["planning_over_cap"] is True


def test_allowances_and_over_budget_are_not_ready():
    budget = module("check_budget").budget
    data = {
        "cap_usd": 50, "fit_confirmed": False,
        "readiness_checks": {"power": False},
        "items": [{"item": "example parts", "quantity": 2,
                   "unit_usd": 20, "price_status": "allowance"}],
    }
    result = budget(data)
    assert result["parts_estimate_usd"] == 40
    assert not result["purchase_ready"] and result["quoted_total_usd"] is None
    for row in data["items"]:
        row["price_status"] = "verified"
    assert not budget(data, 0, 0)["purchase_ready"]  # mechanical fit still unknown
    data["fit_confirmed"] = True
    assert not budget(data, 0, 0)["purchase_ready"]  # unverified power stays a gate
    data["readiness_checks"]["power"] = True
    assert budget(data, 0, 0)["purchase_ready"]
    assert budget(data, 7, 3)["purchase_ready"]  # delivered cap includes charges
    assert not budget(data, 8, 3)["purchase_ready"]
    with pytest.raises(ValueError, match="non-negative"):
        budget(data, -1, 0)


def historical_quoted_budget():
    return {
        "cap_usd": 50, "fit_confirmed": True,
        "readiness_checks": {"power": True},
        "items": [
            {"item": "sample part", "quantity": 2,
             "unit_usd": 10, "price_status": "verified"},
        ],
    }


@pytest.mark.parametrize("shipping,tax,missing", [(31, None, "tax"), (None, 31, "shipping")])
def test_legacy_budget_counts_known_fee_when_other_fee_is_missing(shipping, tax, missing):
    result = module("check_budget").budget(historical_quoted_budget(), shipping, tax)
    assert result["known_landed_subtotal_usd"] == 51
    assert result["planning_total_usd"] == 51
    assert result["unknown_landed_fees"] == [missing]
    assert result["planning_over_cap"] is True
    assert result["remaining_under_cap_usd"] is None
    assert result["quoted_total_usd"] is None
    assert not result["purchase_ready"]


def test_legacy_budget_over_cap_is_tristate_with_incomplete_costs():
    data = historical_quoted_budget()
    budget = module("check_budget").budget
    assert budget(data)["planning_over_cap"] is None
    assert budget(data, 30, 0)["planning_over_cap"] is False
    assert budget(data, "30.01", 0)["planning_over_cap"] is True
    data["items"].append({"item": "unpriced", "quantity": 1,
                          "unit_usd": None, "price_status": "quote_pending"})
    assert budget(data, 0, 0)["planning_over_cap"] is None
    result = budget(data, 31, None)
    assert result["planning_over_cap"] is True
    assert result["known_landed_subtotal_usd"] == 51
    assert result["planning_total_usd"] is None
    assert not result["purchase_ready"]


@pytest.mark.parametrize("currency", ["EUR", "VND", None, "usd"])
@pytest.mark.parametrize("item_level", [False, True])
def test_legacy_budget_rejects_non_usd_currency(currency, item_level):
    data = historical_quoted_budget()
    data["currency"] = "USD"
    target = data["items"][0] if item_level else data
    target["currency"] = currency
    with pytest.raises(ValueError, match="currency must be USD"):
        module("check_budget").budget(data, 0, 0)


def test_legacy_budget_accepts_explicit_usd_currency():
    data = historical_quoted_budget()
    data["currency"] = data["items"][0]["currency"] = "USD"
    assert module("check_budget").budget(data, 0, 0)["purchase_ready"]


def test_legacy_budget_cli_warns_when_partial_cost_exceeds_cap(tmp_path):
    import subprocess
    import sys

    path = tmp_path / "historical.json"
    path.write_text(json.dumps(historical_quoted_budget()), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_budget.py"),
         "--bom", str(path), "--shipping", "31"],
        capture_output=True, text=True, timeout=15,
    )
    assert completed.returncode == 0
    assert json.loads(completed.stdout)["planning_over_cap"] is True
    assert "WARNING: known planning costs exceed the USD cap." in completed.stderr


@pytest.mark.parametrize("field", ["unit_usd", "cap_usd", "shipping", "tax"])
def test_legacy_budget_rejects_money_above_cent_safe_bound(field):
    data = historical_quoted_budget()
    amount = "1000000000000.01"
    fees = {"shipping": 0, "tax": 0}
    if field == "unit_usd":
        data["items"][0][field] = amount
    elif field == "cap_usd":
        data[field] = amount
    else:
        fees[field] = amount
    with pytest.raises(ValueError, match="historical USD bound"):
        module("check_budget").budget(data, **fees)


def test_legacy_budget_bounds_quantity_and_aggregate_cost():
    data = historical_quoted_budget()
    data["items"][0].update(quantity=10**100, unit_usd=0)
    with pytest.raises(ValueError, match="historical unit bound"):
        module("check_budget").budget(data, 0, 0)
    data["items"][0].update(quantity=2, unit_usd="500000000000.01")
    with pytest.raises(ValueError, match="subtotal exceeds"):
        module("check_budget").budget(data, 0, 0)
    data["items"][0].update(quantity=1, unit_usd="1000000000000.00")
    data["cap_usd"] = "1000000000000.00"
    budget = module("check_budget").budget
    assert budget(data, 0, 0)["purchase_ready"]
    with pytest.raises(ValueError, match="total exceeds"):
        budget(data, "0.01", None)


@pytest.mark.parametrize("token", ["1e-999", "10.0000000000000001"])
def test_legacy_budget_cli_rejects_subcent_json_tokens(tmp_path, token):
    import subprocess
    import sys

    data = historical_quoted_budget()
    data["items"][0]["unit_usd"] = "raw-price-token"
    path = tmp_path / "historical.json"
    path.write_text(
        json.dumps(data).replace('"raw-price-token"', token), encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_budget.py"),
         "--bom", str(path), "--shipping", "0", "--tax", "0"],
        capture_output=True, text=True, timeout=15,
    )
    assert completed.returncode == 2
    assert "exact USD cents" in completed.stderr
    assert not completed.stdout.strip()


def test_legacy_budget_cli_preserves_exact_decimal_money(tmp_path):
    import subprocess
    import sys

    data = historical_quoted_budget()
    data["cap_usd"] = 20.46
    data["items"][0]["unit_usd"] = 10.23
    path = tmp_path / "historical.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_budget.py"),
         "--bom", str(path), "--shipping", "0", "--tax", "0"],
        capture_output=True, text=True, timeout=15, check=True,
    )
    output = json.loads(completed.stdout)
    assert output["quoted_total_usd"] == output["cap_usd"] == 20.46
    assert output["historical_math_ready"] is True
    assert output["purchase_ready"] is False


@pytest.mark.parametrize("quantity", [-1, 0, 1.5, True, False, "2", None])
def test_legacy_budget_rejects_nonpositive_or_noninteger_quantities(quantity):
    data = historical_quoted_budget()
    data["items"][0]["quantity"] = quantity
    with pytest.raises(ValueError, match="positive integer"):
        module("check_budget").budget(data, 0, 0)


@pytest.mark.parametrize("tiny", ["0.001", "1.230001", "1e-999999"])
def test_legacy_budget_rejects_positive_subcent_money(tiny):
    # A positive amount cannot underflow to a reported free historical item.
    legacy = historical_quoted_budget()
    legacy["items"][0]["unit_usd"] = tiny
    with pytest.raises(ValueError, match="exact USD cents"):
        module("check_budget").budget(legacy, 0, 0)

    legacy["items"][0]["unit_usd"] = "10.00"
    for fees in ((tiny, 0), (0, tiny)):
        with pytest.raises(ValueError, match="exact USD cents"):
            module("check_budget").budget(legacy, *fees)

    legacy["cap_usd"] = tiny
    with pytest.raises(ValueError, match="exact USD cents"):
        module("check_budget").budget(legacy, 0, 0)


def test_legacy_budget_accepts_exact_cents_with_trailing_decimal_zeroes():
    legacy = historical_quoted_budget()
    legacy["items"][0]["unit_usd"] = "10.2300"
    result = module("check_budget").budget(legacy, "1.000", "0.00")
    assert result["known_subtotal_usd"] == 20.46
    assert result["quoted_total_usd"] == 21.46


@pytest.mark.parametrize("unit_price", [
    -10, "-1.50", "NaN", "Infinity", "-Infinity", float("nan"),
    float("inf"), True, "not a quote",
])
def test_legacy_budget_rejects_negative_nonfinite_and_nonnumeric_price(unit_price):
    data = historical_quoted_budget()
    data["items"][0]["unit_usd"] = unit_price
    with pytest.raises(ValueError, match="finite non-negative"):
        module("check_budget").budget(data, 0, 0)


@pytest.mark.parametrize("bad_cap", [
    -1, "NaN", "Infinity", float("inf"), True, None,
])
def test_legacy_budget_rejects_invalid_purchase_cap(bad_cap):
    data = historical_quoted_budget()
    data["cap_usd"] = bad_cap
    with pytest.raises(ValueError, match="finite non-negative"):
        module("check_budget").budget(data, 0, 0)


@pytest.mark.parametrize("which,bad_value", [
    ("shipping", -1), ("tax", -1),
    ("shipping", "NaN"), ("tax", "Infinity"),
    ("shipping", float("inf")), ("tax", True),
])
def test_legacy_budget_rejects_bad_landed_fees(which, bad_value):
    data = historical_quoted_budget()
    fees = {"shipping": 0, "tax": 0}
    fees[which] = bad_value
    with pytest.raises(ValueError, match="finite non-negative"):
        module("check_budget").budget(data, **fees)


@pytest.mark.parametrize("field,value", [
    ("fit_confirmed", "yes"), ("readiness_checks", {"power": "yes"}),
    ("items", [None]),
])
def test_legacy_budget_rejects_untrusted_release_like_inputs(field, value):
    data = historical_quoted_budget()
    data[field] = value
    with pytest.raises(ValueError):
        module("check_budget").budget(data, 0, 0)


def test_legacy_budget_valid_math_still_cannot_authorize_purchase_cli(tmp_path):
    import subprocess
    import sys

    data = historical_quoted_budget()
    budget = module("check_budget").budget
    assert budget(data, 5, 2)["known_subtotal_usd"] == 20
    assert budget(data, 5, 2)["quoted_total_usd"] == 27
    assert budget(data, 5, 2)["purchase_ready"] is True
    path = tmp_path / "valid-historical.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_budget.py"),
         "--bom", str(path), "--shipping", "5", "--tax", "2",
         "--require-ready"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 2
    assert "HOLD: legacy BOM cannot approve a purchase" in result.stderr
    output = json.loads(result.stdout)
    assert output["historical_math_ready"] is True
    assert output["purchase_ready"] is False
    assert output["quoted_total_usd"] == 27
    data["items"][0]["quantity"] = -10
    path = tmp_path / "unsafe-historical.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_budget.py"),
         "--bom", str(path), "--shipping", "0", "--tax", "0",
         "--require-ready"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 2
    assert "positive integer" in result.stderr
    assert not result.stdout.strip()


def test_active_budget_is_a_first_robot_target_with_open_checks():
    data = json.loads((ROOT.parent / "docs/hardware/bom.json").read_text())
    result = module("check_budget").budget(data)
    assert data["cap_usd"] == 50
    assert result["pending_checks"]
    assert not result["purchase_ready"]


def test_missing_price_is_unknown_not_free_or_a_complete_quote():
    budget = module("check_budget").budget
    data = {
        "cap_usd": 50, "fit_confirmed": True,
        "readiness_checks": {"power": True},
        "items": [
            {"item": "quoted parts", "quantity": 2,
             "unit_usd": 10, "price_status": "verified"},
            {"item": "unpriced power kit", "quantity": 1,
             "unit_usd": None, "price_status": "verified"},
        ],
    }
    result = budget(data, 0, 0)
    assert result["known_subtotal_usd"] == 20
    assert result["parts_estimate_usd"] is None
    assert result["planning_total_usd"] is None
    assert result["quoted_total_usd"] is None
    assert result["remaining_under_cap_usd"] is None
    assert result["unknown_price_items"] == ["unpriced power kit"]
    assert "unpriced power kit" in result["unquoted_items"]
    assert not result["purchase_ready"]
    data["items"][1]["unit_usd"] = 30
    assert budget(data, 0, 0)["purchase_ready"]
    assert not budget(data, 1, 0)["purchase_ready"]


def trial(category, n):
    return {
        "robot_id": "robot-01",
        "category": category,
        "trial": str(n),
        "object_description": "Unit test fixture, not a real trial",
        "assembly_id": "synthetic-test-assembly",
        "mass_g": "1",
        "date": "2026-11-21",
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


# Original source and full-feature plan consistency checks belong with existing
# records and budget tests. These are documentation checks, NOT hardware tests.
DOCS = ROOT.parent / "docs"


def test_source_map_keeps_every_originally_registered_feature():
    text = (DOCS / "source-map.md").read_text(encoding="utf-8")
    feature_ids = re.findall(r"^\| \`([FBSGH]\d{3})\` \|", text, re.MULTILINE)
    expected = {
        *(f"F{n:03d}" for n in range(1, 40)),
        *(f"B{n:03d}" for n in range(1, 31)),
        *(f"S{n:03d}" for n in range(1, 76)),
        *(f"G{n:03d}" for n in range(1, 47)),
        *(f"H{n:03d}" for n in range(1, 11)),
    }
    assert len(feature_ids) == len(set(feature_ids)), "Duplicate feature ID"
    assert set(feature_ids) >= expected, sorted(expected - set(feature_ids))


def test_original_html_link_index_matches_the_uploaded_document():
    """Frozen against all 131 unique URL href values in the uploaded HTML."""
    text = (DOCS / "source-map.md").read_text(encoding="utf-8")
    matches = re.findall(
        r"^\| \`(L\d{3})\` \| <(https?://[^>\s]+)> \|$",
        text,
        re.MULTILINE,
    )
    assert len(matches) == 131
    assert {key for key, _ in matches} == {f"L{n:03d}" for n in range(1, 132)}
    values = [url for _, url in matches]
    assert len(set(values)) == 131
    digest = hashlib.sha256("\n".join(sorted(values)).encode("utf-8")).hexdigest()
    assert digest == "6a40d539546f30bb5739b1919b99f069b22e6d31aa0a212efe35dac928916986"


def test_full_behavioral_acceptance_keeps_original_gates():
    product = (DOCS / "product-definition.md").read_text(encoding="utf-8")
    evidence = (DOCS / "records/verification.md").read_text(encoding="utf-8")
    for number in range(1, 13):
        assert f"| A{number} " in product, f"Canonical A{number} removed"
        assert f"| **A{number} " in evidence, f"Expanded A{number} removed"
    for scenario in range(1, 11):
        assert f"E{scenario:02d}" in evidence
    assert "19/20" in evidence and "18/20" in evidence
    assert "8/10" in evidence
    assert "120s" in evidence
    assert "zero false" in evidence.lower()
    assert "proactive" in product.lower()
    assert "quiet" in product.lower()


@pytest.mark.parametrize(
    "doc, heading",
    [
        ("README.md", "## Full final project contract and scope"),
        ("product-definition.md", "## Full five robot system and proactive conversation contract"),
        ("PLAN.md", "## Complete linear build and permanent verification stages"),
        ("PLAN.md", "## Concrete code and integration ownership plan"),
        ("source-map.md", "## Original HTML feature and sensor idea register"),
        ("source-map.md", "## Complete original HTML research link index"),
        ("decision-log.md", "## Open conflicts requiring decisions before construction"),
        ("records/verification.md", "## Expanded full robot and five peer acceptance cases"),
        ("research/2026-11-03-active-pet-sources.md", "## Inspected upstream source selection and reuse boundaries"),
        ("research/2026-11-03-active-pet-sources.md", "## Detailed unverified HTML numerical proposals"),
    ],
)
def test_full_feature_sections_live_in_their_existing_canonical_files(doc, heading):
    body = (DOCS / doc).read_text(encoding="utf-8")
    assert heading in body
    assert "docs/blueprint/" not in body


def test_new_canonical_document_links_are_local_and_resolvable():
    """Check document paths; external URL validity and GitHub anchors are separate."""
    checked = [
        ROOT.parent / "README.md",
        ROOT.parent / "AGENTS.md",
        *(DOCS / file for file in (
            "README.md", "PLAN.md", "product-definition.md", "source-map.md",
            "decision-log.md", "records/verification.md",
            "research/2026-11-03-active-pet-sources.md",
        )),
    ]
    for file in checked:
        text = file.read_text(encoding="utf-8")
        for link in re.findall(r"\]\(([^)\n]+)\)", text):
            if link.startswith(("https://", "http://", "mailto:", "#")):
                continue
            rel = link.split("#", 1)[0]
            if rel and not rel.startswith("/"):
                target = (file.parent / rel).resolve()
                assert target.exists(), f"Broken link in {file}: {link}"


def test_source_crosswalk_matches_41_original_html_section_ids():
    """Exact ordered identifiers from the original, independently parsed HTML."""
    text = (DOCS / "source-map.md").read_text(encoding="utf-8")
    table = text.split("## Original HTML DOM section crosswalk, verified 2026-11-09", 1)[1]
    ids = re.findall(r"^\| \d+ \| \`([a-z0-9_-]+)\` \|", table, re.MULTILINE)
    assert len(ids) == len(set(ids)) == 41
    digest = hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()
    assert digest == "1128952b6b42f42eb0a5650714c541b7916b3f07b91856cf9ae82e3a9a3d43be"


def test_only_canonical_generated_file_keeps_static_shopping_tables():
    canonical = (
        DOCS / "hardware/complete-shopping-checklist.md"
    ).read_text(encoding="utf-8")
    wiring = (
        DOCS / "hardware/full-feature-wiring-and-shopping.md"
    ).read_text(encoding="utf-8")
    one = (
        DOCS / "hardware/one-robot-inventory-and-shopping.md"
    ).read_text(encoding="utf-8")

    assert "## 1. Owned or ordered, as reported" in canonical
    assert "## 2. Remaining components or unqualified roles" in canonical

    assert "## What you already have" not in wiring
    assert "## Buy and allocate per finished robot" not in wiring
    assert "| Component | Per robot | Five robots |" not in wiring
    assert "complete-shopping-checklist.md" in wiring
    assert "--format first-robot-markdown" in wiring
    assert "## Fixed pin wiring" in wiring

    assert "| Component | Have or buy |" not in one
    assert "| SCD40 CO2 module |" not in one
    assert "| AMG8833 thermal grid sensor |" not in one
    assert "complete-shopping-checklist.md" in one
    assert "--format first-robot-markdown" in one


def test_historical_bom_tracks_selected_vl53l0x_without_authorizing_bulk_buy():
    data = json.loads((DOCS / "hardware/bom.json").read_text(encoding="utf-8"))
    ranging = [
        item for item in data["items"]
        if "VL53L0X GY-530 generic" in item["item"]
    ]
    assert len(ranging) == 3
    assert sum(item["quantity"] for item in ranging) == 8
    assert sorted(item["quantity"] for item in ranging) == [1, 3, 4]
    assert all(item["unit_usd"] is None for item in ranging)
    assert all(item["price_status"] == "sample_quote_only" for item in ranging)
    assert all(item["reference_unit_usd"] == 1.44 for item in ranging)
    assert all(item["reference_price_date"] == "2026-11-18" for item in ranging)
    assert all("one sample" in item["fit"].lower() for item in ranging)
    assert not any(
        "VL53L4CD compatible" in item["item"] for item in data["items"]
    )
    replacement = next(
        item for item in data["optional_items"]
        if item["item"].startswith("Conditional generic MPU6050")
    )
    assert replacement["price_status"] == "not_selected"
    assert "adafruit.com" not in replacement["url"].lower()
    assert data["quote_status"] == "incomplete_eight_vl53l0x_breakouts_and_1s_power"
    parts = (DOCS / "hardware/parts.md").read_text(encoding="utf-8")
    assert "Sensor purchase hold" in parts
    wiring = (DOCS / "hardware/wiring.md").read_text(encoding="utf-8")
    assert "CH0 front-left floor VL53L0X 0x29" in wiring
    assert "front-left downward VL53L4CD candidate" not in wiring
    assert "downward VL6180X" not in wiring
    assert not module("check_budget").budget(data)["purchase_ready"]


def test_actual_wroom_stepper_wiring_has_unique_boot_safe_pins():
    """Prevent a future firmware pin change from silently corrupting the harness.

    This checks source pin ownership, not voltage, current, continuity or a
    physically fitted board. The DC reference is a different binary/profile.
    """
    pins = (ROOT / "firmware/body/include/BodyPins.h").read_text()
    stepper = pins.split("#if DESK_ROBOT_STEPPER", 1)[1].split("#else", 1)[0]

    def values(name, source):
        found = re.search(rf"constexpr int {name}\[\] = \{{([^}}]+)\}};", source)
        assert found, f"Missing {name} pin array"
        return [int(x.strip()) for x in found.group(1).split(",")]

    def one(name, source):
        found = re.search(rf"constexpr int {name} = (-?\d+);", source)
        assert found, f"Missing {name} pin"
        return int(found.group(1))

    wheels = values("kLeftStepperPins", stepper) + values("kRightStepperPins", stepper)
    left = values("kLeftStepperPins", stepper)
    right = values("kRightStepperPins", stepper)
    motor_tokens = re.search(r"constexpr int kMotorPins\[\] = \{([^}]+)\};", stepper)
    assert motor_tokens, "Missing kMotorPins pin array"
    pin_refs = {
        **{f"kLeftStepperPins[{i}]": p for i, p in enumerate(left)},
        **{f"kRightStepperPins[{i}]": p for i, p in enumerate(right)},
    }
    phases = [
        pin_refs[tok.strip()] if tok.strip() in pin_refs else int(tok.strip())
        for tok in motor_tokens.group(1).split(",")
    ]
    assert len(wheels) == len(phases) == 8
    assert wheels == phases
    assert one("kMuxReset", stepper) == -1  # passive 3.3 V pullup, no GPIO4
    external = [
        *wheels,
        one("kUartRx", pins), one("kUartTx", pins),
        one("kSensorSda", stepper), one("kSensorScl", stepper),
        one("kLiftServo", pins), one("kGripServo", pins),
        one("kTouchOutput", stepper),
    ]
    assert len(external) == len(set(external)) == 15
    assert one("kTouchOutput", stepper) == 34  # input only, no internal pullup
    motor_outputs = set(external) - {34}
    forbidden = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 15, 34, 35, 36, 39}
    assert motor_outputs.isdisjoint(forbidden)
    assert one("kSensorSda", stepper) == 21
    assert one("kSensorScl", stepper) == 22
    assert (one("kUartRx", pins), one("kUartTx", pins)) == (16, 17)


def test_default_budget_cli_uses_canonical_first_unit_not_historical_bom():
    import subprocess
    import sys

    cmd = [sys.executable, str(ROOT / "scripts/check_budget.py")]
    completed = subprocess.run(cmd, capture_output=True, text=True,
                               check=True, timeout=15)
    current = json.loads(completed.stdout)
    assert current["source"] == "canonical full-feature-plan.json"
    assert current["purchase_ready"] is False
    assert current["landed_total_usd"] is None
    assert current["first_robot"]["purchase_approved"] is False
    assert len(current["first_robot"]["linked_decisions"]) == 14
    assert current["evaluation_cart"]["exact_sku_count"] == 13
    assert current["evaluation_cart"]["component_quantity"] == 17
    assert current["evaluation_cart"]["historical_priced_partial_subtotal_usd"] == 40.41
    budget = current["evaluation_cart"]["historical_first_unit_budget"]
    assert budget["first_unit_cap_usd"] == 50
    assert budget["reported_prior_spend_usd"] == 13.67
    assert budget["historical_combined_before_tax_shipping_usd"] == 54.08
    assert budget["historical_over_cap_before_tax_shipping_usd"] == 4.08
    assert budget["historical_over_cap_is_hypothetical"] is True
    assert "WARNING: hypothetical historical sample selection" in completed.stderr
    assert "by $4.08 before tax and shipping" in completed.stderr
    assert "not incurred spending or a current quote" in completed.stderr
    assert all("VL53L4CD" not in item["name"]
               for item in current["evaluation_cart"]["items"])
    denied = subprocess.run([*cmd, "--require-ready"],
                            capture_output=True, text=True, timeout=15)
    assert denied.returncode == 2
    assert "HOLD" in denied.stderr


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            '{"cap_usd":50,"cap_usd":1,"fit_confirmed":true,'
            '"readiness_checks":{"power":true},"items":[]}',
            "duplicate object key",
        ),
        (
            '{"cap_usd":NaN,"fit_confirmed":true,'
            '"readiness_checks":{"power":true},"items":[]}',
            "numeric constant",
        ),
        (
            '{"cap_usd":1e9999,"fit_confirmed":true,'
            '"readiness_checks":{"power":true},"items":[]}',
            "overflows finite range",
        ),
    ],
)
def test_legacy_budget_cli_rejects_ambiguous_json_before_math(
    tmp_path, raw, expected,
):
    import subprocess
    import sys

    path = tmp_path / "ambiguous-historical.json"
    path.write_text(raw, encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/check_budget.py"),
            "--bom",
            str(path),
            "--shipping",
            "0",
            "--tax",
            "0",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert completed.returncode == 2
    assert not completed.stdout.strip()
    assert "historical budget JSON is invalid or ambiguous" in completed.stderr
    assert expected in completed.stderr


def test_legacy_complete_bom_cannot_approve_purchase_cli(tmp_path):
    import subprocess
    import sys

    fabricated = {
        "cap_usd": 50, "fit_confirmed": True,
        "readiness_checks": {"power": True},
        "items": [{"item": "fictional approved part", "quantity": 1,
                   "unit_usd": 1, "price_status": "verified"}],
    }
    path = tmp_path / "historical.json"
    path.write_text(json.dumps(fabricated), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_budget.py"),
         "--bom", str(path), "--shipping", "0", "--tax", "0",
         "--require-ready"],
        capture_output=True, text=True, timeout=15,
    )
    assert completed.returncode == 2
    output = json.loads(completed.stdout)
    assert output["historical_math_ready"] is True
    assert output["purchase_ready"] is False
    assert "legacy BOM cannot approve" in completed.stderr
