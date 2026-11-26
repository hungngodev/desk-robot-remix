"""Source admission fence for a single group conversation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .brain_context import live_asr_in_current_grant

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

    def allows_autonomous_social(self, *, has_permission_check: bool) -> bool:
        """Hardware peer dialogue needs its own opt-in and a live caller fence."""
        settings = self.settings
        return settings.mode != "hardware" or (
            has_permission_check
            and settings.fleet_social_autonomy_enabled
            and self.sharing_generation is not None
            and settings.fleet_text_sharing_enabled
            and settings.fleet_sharing_consent_generation == self.sharing_generation
        )

    def admit_camera(self) -> None:
        if self.camera_generation is None:
            self.camera_generation = self.settings.camera_consent_generation

    def admit_room(self) -> None:
        if self.room_generation is None:
            self.room_generation = self.settings.room_station_consent_generation

    def filter_live_transcripts(self, timeline: list[dict], *, now: float) -> list[dict]:
        """Exclude expired ASR and evidence outside the group's current grants."""
        settings = self.settings
        if settings.mode != "hardware":
            return timeline
        live_relay_allowed = (
            self.sharing_generation is not None
            and settings.fleet_text_sharing_enabled
            and settings.fleet_sharing_consent_generation == self.sharing_generation
            and self.camera_generation is not None
            and settings.voice_vision_tools_enabled
            and settings.camera_consent_generation == self.camera_generation
        )
        # Match the hub's 30-second visible ASR lifetime at the admission boundary.
        earliest_source_at = max(settings.camera_consent_started_at, now - 30.0)
        return [
            item for item in timeline
            if live_asr_in_current_grant(
                item, now=now, enabled=live_relay_allowed,
                consent_started_at=earliest_source_at,
            )
        ]

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
