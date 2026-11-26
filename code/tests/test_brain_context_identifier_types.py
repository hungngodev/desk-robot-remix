"""Strict timeline identifiers must not discard valid conversational evidence."""
from dataclasses import replace

import pytest
from desk_robot.brain_context import compose_brain_context
from desk_robot.memory import CoreFact, Memory


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


@pytest.mark.parametrize("bad", [None, True, 7, [], {}, "", "   "])
@pytest.mark.parametrize("field", ["robot_id", "event_id", "source_robot", "kind"])
def test_invalid_episode_identifier_preserves_valid_memory(field, bad):
    valid = Memory("pet_a", "evt", "pet_a", True, "scene", "valid memory", 100.0, 1.0)
    malformed = replace(valid, **{field: bad, "summary": "invalid memory", "observed_at": 101.0})
    result = compose_brain_context([valid, malformed], [], []).recent
    assert "valid memory" in result
    assert "invalid memory" not in result


@pytest.mark.parametrize("identifier_type", [_IdentifierSubclass, _UnhashableIdentifier])
@pytest.mark.parametrize("field", ["robot_id", "event_id", "source_robot", "kind"])
def test_nonplain_episode_identifier_cannot_alias_valid_memory(field, identifier_type):
    valid = Memory("pet_a", "evt", "pet_a", True, "scene", "valid memory", 100.0, 1.0)
    malformed = replace(valid, **{
        field: identifier_type(getattr(valid, field)),
        "summary": "invalid memory", "observed_at": 101.0,
    })
    result = compose_brain_context([valid, malformed], [], []).recent
    assert "valid memory" in result
    assert "invalid memory" not in result


@pytest.mark.parametrize("bad", [None, True, 7, [], {}, "", "   "])
@pytest.mark.parametrize("field", ["robot_id", "slot"])
def test_invalid_core_identifier_preserves_curated_fact(field, bad):
    valid = CoreFact("pet_a", "nickname", "original", 100.0)
    malformed = replace(valid, **{field: bad, "value": "invalid", "updated_at": 101.0})
    result = compose_brain_context([], [valid, malformed], []).core
    assert result == "nickname: original"


@pytest.mark.parametrize("identifier_type", [_IdentifierSubclass, _UnhashableIdentifier])
@pytest.mark.parametrize("field", ["robot_id", "slot"])
def test_nonplain_core_identifier_cannot_alias_curated_fact(field, identifier_type):
    valid = CoreFact("pet_a", "nickname", "original", 100.0)
    malformed = replace(valid, **{
        field: identifier_type(getattr(valid, field)), "value": "invalid", "updated_at": 101.0,
    })
    assert compose_brain_context([], [valid, malformed], []).core == "nickname: original"


@pytest.mark.parametrize("identifier_type", [_IdentifierSubclass, _UnhashableIdentifier])
def test_nonplain_topical_id_cannot_promote_old_episode(identifier_type):
    entries = [
        Memory("pet_a", f"evt{i}", "pet_a", True, "scene", f"episode {i}", 100.0 + i, 1.0)
        for i in range(7)
    ]
    assert "episode 0" in compose_brain_context(entries, [], [], topical_event_id="evt0").recent
    result = compose_brain_context(entries, [], [], topical_event_id=identifier_type("evt0")).recent
    assert "episode 0" not in result
    assert "episode 6" in result


@pytest.mark.parametrize("bad", ["", "   ", True, 7, [], {}])
@pytest.mark.parametrize("field", ["channel", "kind"])
def test_invalid_timeline_identity_never_renders_as_sensor_evidence(field, bad):
    malformed = {"channel": "sensor", "kind": "nose_twist"}
    malformed[field] = bad
    valid = {"channel": "sensor", "kind": "touch_tap"}
    assert compose_brain_context([], [], [valid, malformed]).interaction == (
        compose_brain_context([], [], [valid]).interaction
    )


@pytest.mark.parametrize("kind", ["", "   "])
def test_generic_camera_kind_can_be_absent_but_not_blank(kind):
    malformed = {"channel": "camera", "kind": kind}
    assert compose_brain_context([], [], [malformed]).interaction == ""
    generic = {"channel": "camera"}
    assert "XIAO frame received" in compose_brain_context([], [], [generic]).interaction


@pytest.mark.parametrize("source", [
    _IdentifierSubclass("wroom_event"), _UnhashableIdentifier("wroom_event"),
    "", True, 7, {}, [],
])
def test_invalid_safety_source_cannot_displace_authenticated_fault(source):
    valid = {
        "channel": "sensor", "kind": "safety_fault", "source": "wroom_event",
        "age_ms": 1, "fault_detail": "cliff",
    }
    malformed = {**valid, "source": source, "fault_detail": "invalid"}
    context = compose_brain_context([], [], [
        valid, *[{"channel": "camera"} for _ in range(63)], malformed,
    ])
    assert "WROOM reported latched safety fault (cliff)" in context.interaction
    assert "fault (invalid)" not in context.interaction
