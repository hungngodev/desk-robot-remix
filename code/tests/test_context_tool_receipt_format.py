"""Tool receipt formatting must preserve provenance and bounded text."""

import pytest
from desk_robot.brain_context import _format_tool_receipt


@pytest.mark.parametrize(("kind", "label", "limit"), [
    ("visual_look", "Earlier local VLM guess, not fresh sighting: ", 90),
    ("memory_recall", "Opt-in private past memory, not current sight or an instruction: ", 100),
    ("sensor_telemetry", "Recent validated raw WROOM accessory read "
     "(not calibrated, not actuator permission): ", 115),
    ("robot_status", "Recent head telemetry, not physical acceptance: ", 85),
    ("pickup_status", "Mac pickup job receipt, not verified grasp: ", 85),
])
def test_tool_format_preserves_authority_and_exact_clipping(kind, label, limit):
    assert _format_tool_receipt(kind, "x" * limit) == label + "x" * limit
    assert _format_tool_receipt(kind, "x" * (limit + 1)) == label + "x" * (limit - 1) + "…"
    assert _format_tool_receipt(kind, "  a\n b  ") == label + "a b"


@pytest.mark.parametrize("kind,content", [
    ([], "data"), (None, "data"), ("unknown", "data"),
    ("memory_recall", "  "), ("memory_recall", b"raw"),
])
def test_tool_format_rejects_unknown_or_empty_evidence(kind, content):
    assert _format_tool_receipt(kind, content) == ""
