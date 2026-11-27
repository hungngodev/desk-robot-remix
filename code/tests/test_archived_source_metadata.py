"""Keep historical procurement and CAD metadata distinct from release evidence."""

import json
from decimal import Decimal
from pathlib import Path

_DOCS = Path(__file__).resolve().parents[2] / "docs"


def test_amazon_archive_retains_historical_cash_outlay():
    record = json.loads(
        (_DOCS / "hardware/archive/amazon-candidates.json").read_text(),
        parse_float=Decimal,
    )
    assert record["scope"].startswith("Historical")
    assert record["purchase_ready"] is False
    assert record["shipping_usd"] is None and record["tax_usd"] is None
    spend = sum(row["pack_price_usd"] * row["packs_to_buy"] for row in record["items"])
    assert spend == record["pack_spend_usd"]
    total = spend + record["power_wiring_fastener_allowance_usd"] + record["decoupling_allowance_usd"]
    assert total == record["planning_total_before_charges_usd"]
    assert record["over_cap_before_charges"] is (total > record["first_robot_cap_usd"])


def test_forklift_manifest_distinguishes_pdf_from_stl():
    record = json.loads((_DOCS / "cad/originals/forklift/source.json").read_text())
    assert record["modified"] is False
    assert record["physical_fit_verified"] is False
    files = {row["file"]: row for row in record["files"]}
    assert files.keys() == {"fork_lift_e.stl", "fork_lift_f.stl", "forklifft.pdf"}
    pdf = files["forklifft.pdf"]
    assert pdf["format"] == "PDF"
    assert pdf["content_reviewed"] is False
    assert "STL" not in pdf["changes"]
    for name in ("fork_lift_e.stl", "fork_lift_f.stl"):
        mesh = files[name]
        assert mesh["format"] == "binary STL"
        assert mesh["bytes"] == 84 + 50 * mesh["triangles"]
