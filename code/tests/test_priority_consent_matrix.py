"""Host policy and readonly-query consent matrix.

Scope note:
- Exercises laptop-side `GroupContextConsent`, `quiet_voice_veto`, `receipt_veto`,
  and direct `/v1/pet/{robot_id}/plan-readonly` user-query consent revocation
  when camera or private-memory consent is withdrawn.
- Leaves Sense-hardware physical BOOT microphone mute and end-to-end revoked
  microphone audio-to-query trials explicitly OPEN/unverified: the Mac
  `Settings` fixture intentionally has no local software mic-mute toggle, so
  VAD (`human_active`) alone does not close physical BOOT mic-mute checks.
"""
from types import SimpleNamespace

import pytest
from desk_robot.api_readonly_planner import (
    _PlanContext,
    _revalidate_context,
    _revalidate_selected_grants,
)
from desk_robot.conversation_consent import GroupContextConsent
from desk_robot.initiative_policy import quiet_voice_veto, receipt_veto
from fastapi import HTTPException


@pytest.mark.parametrize("quiet", [False, True])
@pytest.mark.parametrize("human_active", [False, True])
@pytest.mark.parametrize("camera_muted", [False, True])
@pytest.mark.parametrize("peer_enabled", [False, True])
@pytest.mark.parametrize("memory_revoked", [False, True])
def test_priority_consent_matrix(
    quiet, human_active, camera_muted, peer_enabled, memory_revoked,
):
    settings = SimpleNamespace(
        mode="hardware",
        fleet_text_sharing_enabled=peer_enabled,
        voice_memory_tools_enabled=not memory_revoked,
        voice_vision_tools_enabled=not camera_muted,
        room_station_context_enabled=False,
        fleet_sharing_consent_generation=3,
        voice_memory_consent_generation=5,
        camera_consent_generation=7,
        room_station_consent_generation=11,
    )
    fence = GroupContextConsent.capture(settings, has_multimodal=True)
    assert fence.sharing_generation == (3 if peer_enabled else None)
    assert fence.camera_generation == (7 if peer_enabled and not camera_muted else None)
    assert not fence.revoked(private_memory_current=True)
    # Quiet and live VAD govern optional initiative, not source grants.
    assert quiet_voice_veto(
        local_quiet=quiet, scheduled_quiet=False, human_active=lambda: human_active,
    ) is (quiet or human_active)
    assert receipt_veto(
        now=10.0, offered_at=8.0, max_age=5.0, quiet_changed_at=0.0,
        latest_human_turn=lambda: 9.0 if human_active else 0.0,
    ) == ("human_turn_superseded_event" if human_active else None)

    # Direct user query revalidation fails closed (403) when admitted camera or
    # memory consent is revoked after snapshot capture.
    app = SimpleNamespace(state=SimpleNamespace(runtime=SimpleNamespace(multimodal=None)))
    snapshot = _PlanContext(
        visual=None,
        turn_at_request=None,
        camera_context_used=not camera_muted,
        camera_consent_generation=settings.camera_consent_generation,
        camera_granted_at_request=not camera_muted,
        room_context_used=False,
        room_consent_generation=settings.room_station_consent_generation,
        memory_granted_at_request=True,
        memory_consent_generation=settings.voice_memory_consent_generation,
        context="",
    )
    _revalidate_context(app, settings, "robot-01", snapshot)
    if memory_revoked:
        with pytest.raises(HTTPException) as exc:
            _revalidate_selected_grants(
                settings, snapshot, [{"route": "voice-context"}],
                {"voice-context": True, "look": False},
            )
        assert exc.value.status_code == 403
    else:
        _revalidate_selected_grants(
            settings, snapshot, [{"route": "voice-context"}],
            {"voice-context": True, "look": False},
        )
        settings.voice_memory_tools_enabled = False
        with pytest.raises(HTTPException) as exc:
            _revalidate_selected_grants(
                settings, snapshot, [{"route": "voice-context"}],
                {"voice-context": True, "look": False},
            )
        assert exc.value.status_code == 403
        settings.voice_memory_tools_enabled = True

    # Regranting a camera must not resurrect an admitted old camera generation.
    settings.voice_vision_tools_enabled = False
    with pytest.raises(HTTPException) as exc:
        _revalidate_selected_grants(
            settings,
            SimpleNamespace(**{**snapshot.__dict__, "camera_granted_at_request": True}),
            [{"route": "look"}],
            {"voice-context": False, "look": True},
        )
    assert exc.value.status_code == 403
    settings.camera_consent_generation += 1
    settings.voice_vision_tools_enabled = True
    assert fence.revoked(private_memory_current=True) is (peer_enabled and not camera_muted)
    # Revoked peer sharing is independent of camera grant and quiet state.
    settings.fleet_text_sharing_enabled = False
    settings.fleet_sharing_consent_generation += 1
    settings.fleet_text_sharing_enabled = True
    assert fence.revoked(private_memory_current=True) is peer_enabled
    assert fence.revoked(private_memory_current=False)
