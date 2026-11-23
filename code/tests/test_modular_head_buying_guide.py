"""The actual head builder guide must reflect paid evidence and current AEC scope."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_modular_head_guide_reconciles_paid_sense_and_pending_physical_gate():
    guide = (ROOT / "docs/guides/modular-head.md").read_text(encoding="utf-8")
    bom = json.loads(
        (ROOT / "docs/hardware/bom.json").read_text(encoding="utf-8")
    )
    receipt = bom["paid_reconciliation"]
    payment = receipt["payment_total_usd"]
    assert payment == bom["reported_already_purchased_usd"]
    assert receipt["inspected_usable_hardware"] is False
    assert receipt["all_project_prior_spend_reconciled"] is False

    intro = guide.split("## Reuse drivers", maxsplit=1)[0]
    assert f"**\u0024{payment:.2f} paid**" in intro
    assert "**uninspected**" in intro
    assert "November 7" in intro
    assert "older **\u002418.87** displayed listing was not the paid amount" in intro
    assert "**$21.11 head subtotal**" in intro
    assert "one-complete-robot.md" in intro
    assert "Cozmars" in intro and "unprinted fallback" in intro

    # A compiled microphone/reference pathway does not imply physical AEC.
    assert "\u0060SenseReferenceCodec\u0060" in guide
    assert "software\nintegration" in guide
    assert "not a drop-in ESP-IDF binary" in guide
    assert "[physical audio acceptance](audio-barge-in.md)" in guide
    assert "The compiled\nSense baseline has no playback reference/AEC" not in guide
    assert "The Sense build passes; no physical Sense test has happened." not in guide
    assert "At the November 6 firmware snapshot" in guide
    assert "2,503,664 bytes" in guide
    assert "0x2f0000-byte OTA slot check" in guide
    assert "not a compile report for the current PR head" in guide
    assert "Recheck the exact current ESP-IDF" in guide

