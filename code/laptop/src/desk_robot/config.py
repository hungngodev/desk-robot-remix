from __future__ import annotations

import os
import time
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator


class RobotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    name: str
    persona: str = "You are a friendly desk companion. Keep replies to one short sentence."
    head_url: str = "http://127.0.0.1:8081"
    token_env: str
    device_id: str = ""
    motion_enabled: bool = False
    exploration_qualified: bool = False  # Explicit real swept-path trial gate; not a simulation claim.
    # Optional physical sensor-triggered interactions. None means NOT calibrated.
    nose_twist_threshold_counts: int | None = Field(default=None, ge=80, le=1800)
    squeeze_raw_threshold: int | None = Field(default=None, ge=100, le=30000)
    proximity_near_raw_threshold: int | None = Field(default=None, ge=25, le=245)
    battery_low_percent: int = Field(default=20, ge=5, le=40)
    # An actual measured optical contact threshold, NOT a heart-rate model.
    paw_contact_ir_raw_threshold: int | None = Field(default=None, ge=1000, le=250000)
    paw_contact_interactions_qualified: bool = False
    # Ambient change thresholds use actual SHT41 readings, never guessed room conditions.
    ambient_interactions_qualified: bool = False
    nfc_interactions_qualified: bool = False  # toy tags only, never access control
    ambient_temp_change_centi: int | None = Field(default=None, ge=100, le=2000)
    ambient_humidity_change_centi: int | None = Field(default=None, ge=500, le=3000)
    # Only opt-in after observing repeatable BMP280 readings in the actual shell.
    bmp280_interactions_qualified: bool = False
    bmp280_pressure_change_pa: int | None = Field(default=None, ge=100, le=5000)
    gesture_interactions_qualified: bool = False  # measured hardware gate
    handling_interactions_qualified: bool = False  # measured MPU6050 mount and stationary baseline
    handling_tilt_threshold_deg: int = Field(default=38, ge=25, le=75)
    handling_shake_delta_mg: int = Field(default=550, ge=300, le=1400)
    side_near_threshold_mm: int | None = Field(default=None, ge=35, le=1000)
    side_interactions_qualified: bool = False  # measured 3-direction geometry, no motor permit
    calibration: Path | None = None
    dock_calibration: Path | None = None
    dock_motion_qualified: bool = False
    # Actual AVR dock beacon is flashed per physical station. Never infer
    # an assigned dock from a pet name or from one matching IR observation.
    dock_beacon_id: int | None = Field(default=None, ge=1, le=5)
    dock_turn_sign: int | None = Field(default=None, ge=-1, le=1)
    dock_forward_sign: int | None = Field(default=None, ge=-1, le=1)
    voice: str = "af_heart"

    @model_validator(mode="after")
    def local_http(self):
        from urllib.parse import urlparse

        if self.dock_turn_sign == 0 or self.dock_forward_sign == 0:
            raise ValueError("Dock movement polarity cannot be zero")
        u = urlparse(self.head_url)
        if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
            raise ValueError("head_url must be an http(s) URL without embedded credentials")
        return self


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Global live camera grant covers every configured pet. Private Pydantic
    # storage never becomes a serializable configuration or model instruction.
    _camera_consent_generation: int = PrivateAttr(default=0)
    _camera_consent_started_at: float = PrivateAttr(default=0.0)
    _voice_memory_consent_generation: int = PrivateAttr(default=0)
    _transcript_consent_generation: int = PrivateAttr(default=0)
    _room_station_consent_generation: int = PrivateAttr(default=0)
    _fleet_sharing_consent_generation: int = PrivateAttr(default=0)
    robots: list[RobotConfig]
    mode: Literal["hardware", "simulation"] = "hardware"
    coordinator_token_env: str = "DESK_ROBOT_API_TOKEN"
    tools_token_env: str = "DESK_ROBOT_TOOL_TOKEN"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"
    kokoro_url: str = "http://127.0.0.1:8880"
    speech_bridge_url: str = "http://127.0.0.1:8766"
    speech_bridge_token_env: str = "DESK_ROBOT_SPEECH_TOKEN"
    vision_weights: Path | None = None
    vision_model: str = ""  # Explicit local Ollama VLM; never silently use a cloud model.
    voice_memory_tools_enabled: bool = False  # Explicit opt-in for Xiaozhi to read own episodic text.
    voice_transcript_memory_enabled: bool = False  # Separate consent to retain model-estimated spoken words as text.
    voice_vision_tools_enabled: bool = False  # Explicit opt-in for Xiaozhi camera questions/voice frame selection.
    pet_autostart_enabled: bool = False  # Explicit hardware opt-in for idle camera and sensor observation.
    pet_activity_min_interval_seconds: float = Field(default=30.0, ge=5.0, le=600.0)
    pet_activity_max_interval_seconds: float = Field(default=90.0, ge=5.0, le=600.0)
    fleet_text_sharing_enabled: bool = False  # Opt-in local, provenance-tagged text only.
    fleet_social_autonomy_enabled: bool = False  # Bounded pet-to-pet talk, explicit opt-in.
    fleet_social_min_interval_seconds: int = Field(default=300, ge=30, le=3600)
    room_station_enabled: bool = False  # One explicit USB source, never an extra robot
    room_station_port: str | None = None  # Actual local /dev/tty.* device
    room_station_context_enabled: bool = False  # Consent for all pets to read room facts
    # Optional actual ADC endpoints for one physical probe, never fake defaults.
    room_station_soil_dry_adc: int | None = Field(default=None, strict=True, ge=1, le=4094)
    room_station_soil_wet_adc: int | None = Field(default=None, strict=True, ge=1, le=4094)
    fleet_text_auto_fanout_enabled: bool = True  # Keep existing broadcast behavior unless selective-only chosen.
    max_job_seconds: float = Field(default=45, ge=1, le=120)
    trials_file: Path = Path("data/physical-trials.jsonl")
    memory_dir: Path = Path("../data/private/memory")

    def model_post_init(self, __context: object) -> None:
        # A boot-time live grant also needs a local monotonic admission fence.
        if self.voice_vision_tools_enabled:
            self._camera_consent_started_at = time.monotonic()

    @model_validator(mode="after")
    def unique_ids(self):
        if self.pet_activity_min_interval_seconds > self.pet_activity_max_interval_seconds:
            raise ValueError(
                "Pet activity minimum interval cannot exceed maximum"
            )
        if self.voice_transcript_memory_enabled and (
            self.mode != "hardware" or not self.voice_memory_tools_enabled
        ):
            raise ValueError(
                "Spoken transcript retention needs hardware and separate voice memory consent"
            )
        if self.pet_autostart_enabled and (
            self.mode != "hardware"
            or not self.voice_vision_tools_enabled
            or not self.vision_model
        ):
            raise ValueError(
                "Proactive camera autostart requires hardware, explicit camera consent and a local VLM"
            )
        if self.fleet_social_autonomy_enabled and not self.fleet_text_sharing_enabled:
            raise ValueError("Automatic peer dialogue requires explicit local text sharing consent")
        if self.room_station_enabled and (
            self.mode != "hardware" or not isinstance(self.room_station_port, str)
            or not self.room_station_port.startswith("/dev/")
            or len(self.room_station_port) > 255
        ):
            raise ValueError("Room station requires a real explicit local USB serial port")
        if self.room_station_context_enabled and not self.room_station_enabled:
            raise ValueError("Room station context needs explicit source enable and consent")
        soil_dry = self.room_station_soil_dry_adc
        soil_wet = self.room_station_soil_wet_adc
        if (soil_dry is None) != (soil_wet is None):
            raise ValueError("Soil calibration needs both measured dry and wet ADC values")
        if soil_dry is not None:
            if not self.room_station_enabled:
                raise ValueError("Soil calibration requires a real enabled room station")
            from .soil_calibration import SoilCalibration
            SoilCalibration(soil_dry, soil_wet)
        ids = [r.id for r in self.robots]
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("At least one robot and unique robot IDs are required")
        device_ids = [r.device_id for r in self.robots if r.device_id]
        if len(set(device_ids)) != len(device_ids):
            raise ValueError("device_id must uniquely identify a robot")
        docks = [r.dock_beacon_id for r in self.robots if r.dock_beacon_id is not None]
        if len(set(docks)) != len(docks):
            raise ValueError("Each physical dock beacon may be assigned to only one robot")
        if self.mode == "hardware" and any(
            r.dock_motion_qualified and r.dock_beacon_id is None
            for r in self.robots
        ):
            raise ValueError("Qualified dock approach requires assigned beacon ID")
        return self

    def __setattr__(self, name: str, value: object) -> None:
        was_granted = (
            name == "voice_vision_tools_enabled"
            and getattr(self, "voice_vision_tools_enabled", False) is True
        )
        memory_was_granted = (
            name == "voice_memory_tools_enabled"
            and getattr(self, "voice_memory_tools_enabled", False) is True
        )
        room_was_granted = (
            name == "room_station_context_enabled"
            and getattr(self, "room_station_context_enabled", False) is True
        )
        transcript_was_granted = (
            name == "voice_transcript_memory_enabled"
            and getattr(self, "voice_transcript_memory_enabled", False) is True
        )
        sharing_was_granted = (
            name == "fleet_text_sharing_enabled"
            and getattr(self, "fleet_text_sharing_enabled", False) is True
        )
        super().__setattr__(name, value)
        if was_granted and not self.voice_vision_tools_enabled:
            # Even an immediate re-enable is a NEW grant; old VLM evidence
            # and in-flight plans must never regain the prior authorization.
            self._camera_consent_generation += 1
        elif name == "voice_vision_tools_enabled" and self.voice_vision_tools_enabled and not was_granted:
            # Sent Opus text has a Mac monotonic timestamp. A late HTTP
            # receipt from the revoked grant cannot enter this new context.
            self._camera_consent_started_at = time.monotonic()
        if memory_was_granted and not self.voice_memory_tools_enabled:
            # Disabling memory access revokes outstanding asynchronous reads.
            # The next opt-in is a new grant even without SQLite edits.
            self._voice_memory_consent_generation += 1
        if room_was_granted and not self.room_station_context_enabled:
            # Room-station text from a previous grant cannot be emitted by a
            # late Ollama plan if the operator has already opted out.
            self._room_station_consent_generation += 1

        if transcript_was_granted and not self.voice_transcript_memory_enabled:
            # Immediate regrant does not revive an in-flight transcript write.
            self._transcript_consent_generation += 1
        if sharing_was_granted and not self.fleet_text_sharing_enabled:
            # Peer relays and in-flight SQLite writes belong to the old grant.
            self._fleet_sharing_consent_generation += 1

    @property
    def camera_consent_generation(self) -> int:
        return self._camera_consent_generation

    @property
    def camera_consent_started_at(self) -> float:
        return self._camera_consent_started_at

    @property
    def voice_memory_consent_generation(self) -> int:
        return self._voice_memory_consent_generation

    @property
    def transcript_consent_generation(self) -> int:
        return self._transcript_consent_generation

    @property
    def room_station_consent_generation(self) -> int:
        return self._room_station_consent_generation

    @property
    def fleet_sharing_consent_generation(self) -> int:
        return self._fleet_sharing_consent_generation

    def robot(self, robot_id: str) -> RobotConfig:
        for robot in self.robots:
            if robot.id == robot_id:
                return robot
        raise KeyError(robot_id)


def secret(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if len(value) < 24 or value.lower() in ("changeme", "your-token-here"):
        raise ValueError(f"Set {name} to a unique token of at least 24 characters")
    return value


def load_settings(path: str | Path) -> Settings:
    path = Path(path).resolve()
    with path.open("rb") as stream:
        settings = Settings.model_validate(tomllib.load(stream))
    for robot in settings.robots:
        if robot.calibration and not robot.calibration.is_absolute():
            robot.calibration = (path.parent / robot.calibration).resolve()
    for robot in settings.robots:
        if robot.dock_calibration and not robot.dock_calibration.is_absolute():
            robot.dock_calibration = (path.parent / robot.dock_calibration).resolve()
    if settings.vision_weights and not settings.vision_weights.is_absolute():
        settings.vision_weights = (path.parent / settings.vision_weights).resolve()
    if not settings.trials_file.is_absolute():
        settings.trials_file = (path.parent / settings.trials_file).resolve()
    if not settings.memory_dir.is_absolute():
        settings.memory_dir = (path.parent / settings.memory_dir).resolve()
    return settings
