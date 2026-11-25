"""Strict timeline identifiers must not discard valid conversational evidence."""
import pytest
from desk_robot.brain_context import compose_brain_context


class _IdentifierSubclass(str):
    pass


class _UnhashableIdentifier(str):
    __hash__ = None


@pytest.mark.parametrize("identifier_type", [_IdentifierSubclass, _UnhashableIdentifier])
@pytest.mark.parametrize("field", ["channel", "kind"])
def test_nonplain_timeline_identifier_does_not_abort_or_alias_context(identifier_type, field):
    malformed = {"channel": "sensor", "kind": "nose_twist"}
    malformed[field] = identifier_type(malformed[field])
    context = compose_brain_context([], [], [
        {"channel": "sensor", "kind": "touch_tap"},
        {"channel": "camera"},
        malformed,
    ])
    assert "Physical sensor edge: touch_tap" in context.interaction
    assert "XIAO frame received" in context.interaction
    assert "nose_twist" not in context.interaction


@pytest.mark.parametrize("field", ["channel", "kind"])
def test_invalid_safety_identity_cannot_displace_valid_older_fault(field):
    valid = {
        "channel": "sensor", "kind": "safety_fault",
        "source": "wroom_event", "age_ms": 1, "fault_detail": "cliff",
    }
    malformed = {**valid, "fault_detail": "invalid"}
    malformed[field] = _IdentifierSubclass(malformed[field])
    context = compose_brain_context([], [], [
        valid, *[{"channel": "camera"} for _ in range(63)], malformed,
    ])
    assert "WROOM reported latched safety fault (cliff)" in context.interaction
    assert "fault (invalid)" not in context.interaction
