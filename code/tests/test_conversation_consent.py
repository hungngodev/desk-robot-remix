from types import SimpleNamespace

import pytest
from desk_robot.conversation_consent import GroupContextConsent


def grants(**overrides):
    values = dict(
        mode="hardware", fleet_text_sharing_enabled=True,
        voice_memory_tools_enabled=True, voice_vision_tools_enabled=True,
        room_station_context_enabled=True, fleet_sharing_consent_generation=0,
        voice_memory_consent_generation=0, camera_consent_generation=0,
        room_station_consent_generation=0,
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
