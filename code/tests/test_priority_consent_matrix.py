"""Host policy matrix, not a substitute for physical BOOT microphone testing."""
from types import SimpleNamespace

import pytest
from desk_robot.conversation_consent import GroupContextConsent
from desk_robot.initiative_policy import quiet_voice_veto, receipt_veto


@pytest.mark.parametrize("quiet", [False, True])
@pytest.mark.parametrize("human_active", [False, True])
@pytest.mark.parametrize("camera_muted", [False, True])
@pytest.mark.parametrize("peer_enabled", [False, True])
def test_priority_consent_matrix(quiet, human_active, camera_muted, peer_enabled):
    settings = SimpleNamespace(
        mode="hardware",
        fleet_text_sharing_enabled=peer_enabled,
        voice_memory_tools_enabled=False,
        voice_vision_tools_enabled=not camera_muted,
        fleet_sharing_consent_generation=3,
        camera_consent_generation=7,
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
    # Regranting a camera must not resurrect an admitted old camera generation.
    settings.voice_vision_tools_enabled = False
    settings.camera_consent_generation += 1
    settings.voice_vision_tools_enabled = True
    assert fence.revoked(private_memory_current=True) is (peer_enabled and not camera_muted)
    # Revoked peer sharing is independent of camera grant and quiet state.
    settings.fleet_text_sharing_enabled = False
    settings.fleet_sharing_consent_generation += 1
    settings.fleet_text_sharing_enabled = True
    assert fence.revoked(private_memory_current=True) is peer_enabled
    assert fence.revoked(private_memory_current=False)
