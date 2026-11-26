import itertools

import pytest
from desk_robot.initiative_policy import (
    event_budget_reason,
    first_initiative_veto,
    quiet_voice_reason,
)


_BOOLEAN_TRIPLES = tuple(itertools.product((False, True), repeat=3))


@pytest.mark.parametrize("local,scheduled,human", _BOOLEAN_TRIPLES)
def test_quiet_voice_reason_precedence(local, scheduled, human):
    calls = []

    def human_active():
        calls.append(True)
        return human

    expected = (
        "manual_quiet" if local else "scheduled_quiet_hours" if scheduled
        else "human_floor_busy" if human else None
    )
    assert quiet_voice_reason(
        local_quiet=local, scheduled_quiet=scheduled, human_active=human_active,
    ) == expected
    assert len(calls) == int(not local and not scheduled)


@pytest.mark.parametrize("first,second,third", _BOOLEAN_TRIPLES)
def test_first_initiative_veto_evaluates_only_until_first_blocker(first, second, third):
    calls = []
    rules = [("first", first), ("second", second), ("third", third)]

    def probe(name, blocked):
        calls.append(name)
        return blocked

    result = first_initiative_veto(*(
        (name, lambda name=name, blocked=blocked: probe(name, blocked))
        for name, blocked in rules
    ))
    expected = next((name for name, blocked in rules if blocked), None)
    assert result == expected
    assert calls == [name for name, _ in rules][:
        3 if expected is None else [name for name, _ in rules].index(expected) + 1
    ]


@pytest.mark.parametrize(
    ("event_age", "fleet_age", "expected"),
    [
        (2.99, 11.99, "duplicate_event_cooldown"),
        (2.99, 12.0, "duplicate_event_cooldown"),
        (3.0, 11.99, "fleet_speech_cooldown"),
        (3.0, 12.0, None),
        (-1.0, 11.99, "fleet_speech_cooldown"),
        (3.0, -1.0, None),
    ],
)
def test_event_budget_reason_precedence_and_boundaries(event_age, fleet_age, expected):
    assert event_budget_reason(
        now=100.0, previous_event_at=100.0 - event_age,
        fleet_spoken_at=100.0 - fleet_age, event_window=3.0, speech_interval=12.0,
    ) == expected
