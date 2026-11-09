import importlib.util
import hashlib
import re
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
