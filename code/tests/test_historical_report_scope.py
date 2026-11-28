"""Archived reports must not masquerade as live verification receipts."""
import json
from pathlib import Path

import pytest

REPORTS = Path(__file__).resolve().parents[2] / "docs/records/reports"
ARCHIVE = sorted(REPORTS.glob("*.json"))


def test_historical_report_archive_is_present():
    assert ARCHIVE


@pytest.mark.parametrize("path", ARCHIVE, ids=lambda path: path.name)
def test_archived_report_cannot_claim_current_head(path):
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["evidence_scope"] == "historical_snapshot"
    assert report["current_head_verified"] is False


def test_pre_photo_bom_cannot_claim_current_purchase_authority():
    path = (
        REPORTS.parents[1] / "hardware/archive/bom-before-photo-audit-2026-11-04.json"
    )
    bom = json.loads(path.read_text(encoding="utf-8"))
    assert bom["evidence_scope"] == "historical_snapshot"
    assert bom["current_head_verified"] is False
    assert bom["purchase_ready"] is False
    assert "docs/hardware/full-feature-plan.json" in bom["scope_note"]
    assert "code/scripts/procurement_release.py" in bom["scope_note"]
