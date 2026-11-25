"""Source admission fence for a single group conversation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Settings


@dataclass
class GroupContextConsent:
    """Capture grant generations once; a later grant cannot revive old evidence."""

    settings: Settings
    sharing_generation: int | None = None
    memory_generation: int | None = None
    camera_generation: int | None = None
    room_generation: int | None = None

    @classmethod
    def capture(cls, settings: Settings, *, has_multimodal: bool) -> GroupContextConsent:
        fence = cls(settings)
        if settings.mode == "hardware" and settings.fleet_text_sharing_enabled:
            fence.sharing_generation = settings.fleet_sharing_consent_generation
            if settings.voice_memory_tools_enabled:
                fence.memory_generation = settings.voice_memory_consent_generation
            if has_multimodal and settings.voice_vision_tools_enabled:
                fence.admit_camera()
        return fence

    def admit_camera(self) -> None:
        if self.camera_generation is None:
            self.camera_generation = self.settings.camera_consent_generation

    def admit_room(self) -> None:
        if self.room_generation is None:
            self.room_generation = self.settings.room_station_consent_generation

    def revoked(self, *, private_memory_current: bool) -> bool:
        """Use the same source predicate for speech admission and prompt cleanup."""
        settings = self.settings
        return (
            (self.sharing_generation is not None
             and (not settings.fleet_text_sharing_enabled
                  or settings.fleet_sharing_consent_generation != self.sharing_generation))
            or (self.memory_generation is not None
                and (not settings.voice_memory_tools_enabled
                     or settings.voice_memory_consent_generation != self.memory_generation))
            or (self.camera_generation is not None
                and (not settings.voice_vision_tools_enabled
                     or settings.camera_consent_generation != self.camera_generation))
            or (self.room_generation is not None
                and (not settings.room_station_context_enabled
                     or settings.room_station_consent_generation != self.room_generation))
            or not private_memory_current
        )
