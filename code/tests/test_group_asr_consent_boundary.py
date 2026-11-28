"""Group prompt admission must not revive queued pre-grant ASR evidence."""
from types import SimpleNamespace

import pytest
from desk_robot.conversation_consent import GroupContextConsent


@pytest.mark.parametrize("regrant", [False, True])
def test_group_asr_snapshot_revoked_before_brain_context(regrant):
    settings = SimpleNamespace(
        mode="hardware", fleet_text_sharing_enabled=True,
        fleet_sharing_consent_generation=0, voice_memory_tools_enabled=False,
        voice_vision_tools_enabled=True, camera_consent_generation=0,
        camera_consent_started_at=10.0,
    )
    fence = GroupContextConsent.capture(settings, has_multimodal=True)
    old = {"channel": "human_transcript", "source_at": 11.0, "content": "old"}
    fault = {"channel": "sensor", "source": "wroom_event"}
    assert fence.filter_live_transcripts([old, fault], now=12.0) == [old, fault]
    settings.voice_vision_tools_enabled = False
    settings.camera_consent_generation += 1
    assert fence.revoked(private_memory_current=True)
    if regrant:
        settings.voice_vision_tools_enabled = True
        settings.camera_consent_started_at = 13.0
    assert fence.revoked(private_memory_current=True)
    # Even a new group session must not admit the previous grant's queued ASR.
    fresh_fence = GroupContextConsent.capture(settings, has_multimodal=True)
    fresh = {"channel": "human_transcript", "source_at": 14.0, "content": "fresh"}
    assert fresh_fence.filter_live_transcripts([old, fault, fresh], now=15.0) == (
        [fault, fresh] if regrant else [fault]
    )
