from types import SimpleNamespace

import pytest
from desk_robot.conversation_consent import GroupContextConsent


@pytest.mark.parametrize(("sharing", "social", "callback", "allowed"), [
    (False, False, True, False),
    (False, True, True, False),
    (True, False, True, False),
    (True, True, False, False),
    (True, True, True, True),
])
def test_hardware_social_admission(sharing, social, callback, allowed):
    settings = SimpleNamespace(
        mode="hardware", fleet_text_sharing_enabled=sharing,
        fleet_social_autonomy_enabled=social, fleet_sharing_consent_generation=0,
        voice_memory_tools_enabled=False, voice_vision_tools_enabled=False,
    )
    fence = GroupContextConsent.capture(settings, has_multimodal=False)
    assert fence.allows_autonomous_social(has_permission_check=callback) is allowed
    settings.fleet_text_sharing_enabled = True
    settings.fleet_social_autonomy_enabled = True
    settings.fleet_sharing_consent_generation += 1
    assert not fence.allows_autonomous_social(has_permission_check=True)
