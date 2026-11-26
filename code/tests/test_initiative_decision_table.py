import itertools

import pytest
from desk_robot.initiative_policy import first_initiative_veto, quiet_voice_reason


@pytest.mark.parametrize("local,scheduled,human", itertools.product((False, True), repeat=3))
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


@pytest.mark.parametrize("first,second,third", itertools.product((False, True), repeat=3))
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
