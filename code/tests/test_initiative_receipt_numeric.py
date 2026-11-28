"""Numeric receipt boundaries must fail closed before human-floor probes."""

import pytest
from desk_robot.initiative_policy import receipt_veto


@pytest.mark.parametrize("offered_at", [10**400, -(10**400), float("inf"), float("nan"), True])
def test_unrepresentable_receipt_is_rejected_before_other_policy(offered_at):
    def unexpected():
        pytest.fail("invalid receipt must not query the human floor")

    assert receipt_veto(
        now=100.0, offered_at=offered_at, max_age=10.0,
        quiet_changed_at=0.0, latest_human_turn=unexpected,
    ) == "event_expired_before_admission"
