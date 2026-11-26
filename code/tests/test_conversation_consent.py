from types import SimpleNamespace

import pytest
from desk_robot.conversation_consent import GroupContextConsent


def grants(**overrides):
    values = dict(
        mode="hardware", fleet_text_sharing_enabled=True,
        voice_memory_tools_enabled=True, voice_vision_tools_enabled=True,
        room_station_context_enabled=True, fleet_sharing_consent_generation=0,
        voice_memory_consent_generation=0, camera_consent_generation=0,
        room_station_consent_generation=0, camera_consent_started_at=10.0,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(("flag", "generation"), [
    ("fleet_text_sharing_enabled", "fleet_sharing_consent_generation"),
    ("voice_memory_tools_enabled", "voice_memory_consent_generation"),
    ("voice_vision_tools_enabled", "camera_consent_generation"),
    ("room_station_context_enabled", "room_station_consent_generation"),
])
def test_admitted_source_revocation_cannot_be_regranted(flag, generation):
    settings = grants()
    fence = GroupContextConsent.capture(settings, has_multimodal=True)
    fence.admit_room()
    assert not fence.revoked(private_memory_current=True)
    setattr(settings, flag, False)
    assert fence.revoked(private_memory_current=True)
    setattr(settings, generation, 1)
    setattr(settings, flag, True)
    fence.admit_camera()
    fence.admit_room()
    assert fence.revoked(private_memory_current=True)


def test_late_camera_and_room_admission_preserve_first_generation():
    settings = grants(voice_vision_tools_enabled=False, room_station_context_enabled=False)
    fence = GroupContextConsent.capture(settings, has_multimodal=True)
    assert not fence.revoked(private_memory_current=True)
    settings.camera_consent_generation = 4
    settings.room_station_consent_generation = 7
    settings.voice_vision_tools_enabled = True
    settings.room_station_context_enabled = True
    fence.admit_camera()
    fence.admit_room()
    assert not fence.revoked(private_memory_current=True)
    settings.camera_consent_generation += 1
    fence.admit_camera()
    assert fence.revoked(private_memory_current=True)


def test_unadmitted_sources_do_not_revoke_but_private_correction_does():
    settings = grants(fleet_text_sharing_enabled=False)
    fence = GroupContextConsent.capture(settings, has_multimodal=True)
    settings.fleet_text_sharing_enabled = True
    settings.fleet_sharing_consent_generation += 1
    settings.camera_consent_generation += 1
    settings.voice_memory_consent_generation += 1
    settings.room_station_consent_generation += 1
    assert fence.sharing_generation is None
    assert fence.memory_generation is None
    assert not fence.revoked(private_memory_current=True)
    assert fence.revoked(private_memory_current=False)


@pytest.mark.parametrize("text", [
    "Do not share my conversation",
    "I might allow you to remember",
    "The phrase is 'you have permission'",
    "Yes, but not with the other robots",
])
@pytest.mark.parametrize("disabled", [
    "fleet_text_sharing_enabled", "voice_vision_tools_enabled",
])
def test_transcript_text_cannot_grant_permission(text, disabled):
    settings = grants(**{disabled: False})
    fence = GroupContextConsent.capture(settings, has_multimodal=True)
    transcript = {"channel": "human_transcript", "source_at": 20.0, "content": text}
    sensor = {"channel": "sensor", "source": "wroom_event"}
    assert fence.filter_live_transcripts([transcript, sensor], now=21.0) == [sensor]
    assert getattr(settings, disabled) is False


@pytest.mark.parametrize(("stamp", "accepted"), [
    (9.999, False), (10.0, False), (19.999, False), (20.0, True),
    (49.999, True), (50.0, True), (50.001, False),
    (None, False), (True, False), ("49.0", False), (float("nan"), False),
])
def test_group_transcript_grant_and_freshness_boundaries(stamp, accepted):
    fence = GroupContextConsent.capture(grants(), has_multimodal=True)
    transcript = {"channel": "human_transcript", "source_at": stamp, "age_ms": 0}
    assert fence.filter_live_transcripts([transcript], now=50.0) == (
        [transcript] if accepted else []
    )


def test_new_group_session_does_not_revive_old_transcripts_or_fence():
    settings = grants()
    previous = GroupContextConsent.capture(settings, has_multimodal=True)
    old = {"channel": "human_transcript", "source_at": 20.0}
    assert previous.filter_live_transcripts([old], now=21.0) == [old]
    settings.fleet_sharing_consent_generation += 1
    settings.camera_consent_generation += 1
    settings.camera_consent_started_at = 22.0
    current = GroupContextConsent.capture(settings, has_multimodal=True)
    new = {"channel": "human_transcript", "source_at": 23.0}
    assert previous.revoked(private_memory_current=True)
    assert previous.filter_live_transcripts([old, new], now=24.0) == []
    assert not current.revoked(private_memory_current=True)
    assert current.filter_live_transcripts([old, new], now=24.0) == [new]


@pytest.mark.parametrize(("stamp", "accepted"), [(39.999, False), (40.0, True)])
def test_fresh_transcript_must_also_belong_to_current_grant(stamp, accepted):
    fence = GroupContextConsent.capture(
        grants(camera_consent_started_at=40.0), has_multimodal=True,
    )
    transcript = {"channel": "human_transcript", "source_at": stamp}
    assert fence.filter_live_transcripts([transcript], now=50.0) == (
        [transcript] if accepted else []
    )
