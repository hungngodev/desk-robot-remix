from __future__ import annotations

import os
import re
import secrets
import time
import tomllib
from collections.abc import Callable, Mapping
from ipaddress import ip_address
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse
from weakref import ReferenceType, ref

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    StrictBool,
    ValidationError,
    model_validator,
)

from .fleet_identity import device_identity_key, valid_unique_robot_ids
from .personality_policy import PersonalityProfile
from .private_files import read_private_env as read_private_env
from .serial_device import is_local_serial_path

CredentialEnvName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
LocalClockTime = Annotated[
    str, Field(strict=True, min_length=5, max_length=5,
               pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$"),
]


def quiet_hours_active(schedule: tuple[str, str] | None) -> bool:
    """Use the Mac's real local wall clock, including midnight and DST."""
    if schedule is None:
        return False
    start, end = schedule
    now = time.strftime("%H:%M", time.localtime())
    if start < end:
        return start <= now < end
    return now >= start or now < end


def _head_host(url: str) -> str:
    host = (urlparse(url).hostname or "").rstrip(".").casefold()
    try:
        address = ip_address(host)
    except ValueError:
        return host
    # IPv4-mapped IPv6 is another spelling of the same physical address.
    return str(getattr(address, "ipv4_mapped", None) or address)


def _require_boolean_assignment(model: BaseModel, name: str, value: object) -> None:
    field = type(model).model_fields.get(name)
    if field is not None and field.annotation is bool and type(value) is not bool:
        raise ValueError(f"{name} must be a boolean")


class RobotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, hide_input_in_errors=True)
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    name: str
    persona: str = "You are a friendly desk companion. Keep replies to one short sentence."
    personality_profile: PersonalityProfile = Field(default="balanced", frozen=True)
    head_url: str = "http://127.0.0.1:8081"
    token_env: CredentialEnvName
    # The bridge uses literal identity matching; only an empty string is unmapped.
    device_id: str = Field(default="", pattern=r"^\S*$")
    motion_enabled: StrictBool = False
    # Set only after verifying installed driver, wiring, and flashed WROOM.
    motor_backend: Literal["stepper_28byj48", "dc_pwm_guarded"] | None = None
    exploration_qualified: StrictBool = False  # Explicit real swept-path trial gate; not a simulation claim.
    # Optional physical sensor-triggered interactions. None means NOT calibrated.
    nose_twist_threshold_counts: int | None = Field(default=None, strict=True, ge=80, le=1800)
    squeeze_raw_threshold: int | None = Field(default=None, strict=True, ge=100, le=30000)
    proximity_near_raw_threshold: int | None = Field(default=None, strict=True, ge=25, le=245)
    battery_low_percent: int = Field(default=20, strict=True, ge=5, le=40)
    # An actual measured optical contact threshold, NOT a heart-rate model.
    paw_contact_ir_raw_threshold: int | None = Field(default=None, strict=True, ge=1000, le=250000)
    paw_contact_interactions_qualified: StrictBool = False
    # Ambient change thresholds use actual SHT41 readings, never guessed room conditions.
    ambient_interactions_qualified: StrictBool = False
    nfc_interactions_qualified: StrictBool = False  # toy tags only, never access control
    ambient_temp_change_centi: int | None = Field(default=None, strict=True, ge=100, le=2000)
    ambient_humidity_change_centi: int | None = Field(default=None, strict=True, ge=500, le=3000)
    # Only opt-in after observing repeatable BMP280 readings in the actual shell.
    bmp280_interactions_qualified: StrictBool = False
    bmp280_pressure_change_pa: int | None = Field(default=None, strict=True, ge=100, le=5000)
    gesture_interactions_qualified: StrictBool = False  # measured hardware gate
    handling_interactions_qualified: StrictBool = False  # measured MPU6050 mount and stationary baseline
    # Defaults are provisional; this separate attestation requires mounted-unit trials.
    handling_thresholds_calibrated: StrictBool = False
    handling_tilt_threshold_deg: int = Field(default=38, strict=True, ge=25, le=75)
    handling_shake_delta_mg: int = Field(default=550, strict=True, ge=300, le=1400)
    side_near_threshold_mm: int | None = Field(default=None, strict=True, ge=35, le=1000)
    side_interactions_qualified: StrictBool = False  # measured 3-direction geometry, no motor permit
    calibration: Path | None = None
    dock_calibration: Path | None = None
    dock_motion_qualified: StrictBool = False
    autonomous_low_battery_dock_enabled: StrictBool = False
    spatial_navigation_qualified: StrictBool = False
    object_detector_qualified: StrictBool = False
    # Actual AVR dock beacon is flashed per physical station. Never infer
    # an assigned dock from a pet name or from one matching IR observation.
    dock_beacon_id: int | None = Field(default=None, strict=True, ge=1, le=5)
    dock_marker_id: int | None = Field(default=None, strict=True, ge=0, le=586)
    dock_turn_sign: int | None = Field(default=None, strict=True, ge=-1, le=1)
    dock_forward_sign: int | None = Field(default=None, strict=True, ge=-1, le=1)
    voice: str = "af_heart"

    def __setattr__(self, name: str, value: object) -> None:
        _require_boolean_assignment(self, name, value)
        super().__setattr__(name, value)

    @model_validator(mode="after")
    def local_http(self):
        if not self.name.strip():
            raise ValueError("Robot name cannot be blank")
        if self.dock_turn_sign == 0 or self.dock_forward_sign == 0:
            raise ValueError("Dock movement polarity cannot be zero")
        try:
            u = urlparse(self.head_url)
            port = u.port
        except ValueError:
            # urllib may include malformed address or port text in its exception.
            raise ValueError("head_url must have a valid hostname and port") from None
        if (
            u.scheme not in ("http", "https") or not u.hostname
            or u.username is not None or u.password is not None
            or u.query or u.fragment or any(char.isspace() for char in self.head_url)
        ):
            raise ValueError("head_url must be an http(s) URL without embedded credentials")
        if port == 0:
            raise ValueError("head_url port must be nonzero")
        return self


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, hide_input_in_errors=True)
    # Global live camera grant covers every configured pet. Private Pydantic
    # storage never becomes a serializable configuration or model instruction.
    _camera_consent_generation: int = PrivateAttr(default=0)
    _camera_revocation_listeners: list[ReferenceType[Callable[[Settings], None]]] = PrivateAttr(
        default_factory=list,
    )
    _camera_consent_started_at: float = PrivateAttr(default=0.0)
    _voice_memory_consent_generation: int = PrivateAttr(default=0)
    _transcript_consent_generation: int = PrivateAttr(default=0)
    _voice_memory_consent_started_at: float = PrivateAttr(default=0.0)
    _transcript_consent_started_at: float = PrivateAttr(default=0.0)
    _room_station_consent_generation: int = PrivateAttr(default=0)
    _fleet_sharing_consent_generation: int = PrivateAttr(default=0)
    _fleet_social_autonomy_generation: int = PrivateAttr(default=0)
    _fleet_auto_fanout_consent_generation: int = PrivateAttr(default=0)
    robots: list[RobotConfig]
    mode: Literal["hardware", "simulation"] = "hardware"
    coordinator_token_env: CredentialEnvName = "DESK_ROBOT_API_TOKEN"
    tools_token_env: CredentialEnvName = "DESK_ROBOT_TOOL_TOKEN"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"
    kokoro_url: str = "http://127.0.0.1:8880"
    speech_bridge_url: str = "http://127.0.0.1:8766"
    speech_bridge_token_env: CredentialEnvName = "DESK_ROBOT_SPEECH_TOKEN"
    vision_weights: Path | None = None
    vision_model: str = ""  # Explicit local Ollama VLM; never silently use a cloud model.
    voice_memory_tools_enabled: StrictBool = False  # Explicit opt-in for Xiaozhi to read own episodic text.
    voice_transcript_memory_enabled: StrictBool = False  # Separate consent to retain model-estimated spoken words as text.
    voice_vision_tools_enabled: StrictBool = False  # Explicit opt-in for Xiaozhi camera questions/voice frame selection.
    pet_autostart_enabled: StrictBool = False  # Explicit hardware opt-in for idle camera and sensor observation.
    pet_activity_min_interval_seconds: float = Field(default=30.0, strict=True, ge=5.0, le=600.0)
    pet_activity_max_interval_seconds: float = Field(default=90.0, strict=True, ge=5.0, le=600.0)
    # Optional daily local-time window; fixed for the lifetime of this config.
    pet_quiet_hours: tuple[LocalClockTime, LocalClockTime] | None = Field(
        default=None, frozen=True,
    )
    fleet_text_sharing_enabled: StrictBool = False  # Opt-in local, provenance-tagged text only.
    fleet_social_autonomy_enabled: StrictBool = False  # Bounded pet-to-pet talk, explicit opt-in.
    fleet_social_min_interval_seconds: int = Field(default=300, strict=True, ge=30, le=3600)
    room_station_enabled: StrictBool = False  # One explicit USB source, never an extra robot
    room_station_port: str | None = None  # Actual local /dev/tty.* device
    room_station_context_enabled: StrictBool = False  # Consent for all pets to read room facts
    # Optional actual ADC endpoints for one physical probe, never fake defaults.
    room_station_soil_dry_adc: int | None = Field(default=None, strict=True, ge=1, le=4094)
    room_station_soil_wet_adc: int | None = Field(default=None, strict=True, ge=1, le=4094)
    fleet_text_auto_fanout_enabled: StrictBool = True  # Keep existing broadcast behavior unless selective-only chosen.
    vision_weights_sha256: str | None = None
    max_job_seconds: float = Field(default=45, strict=True, ge=1, le=120)
    trials_file: Path = Path("data/physical-trials.jsonl")
    memory_dir: Path = Path("../data/private/memory")

    def model_post_init(self, __context: object) -> None:
        # A boot-time live grant also needs a local monotonic admission fence.
        if self.voice_vision_tools_enabled:
            self._camera_consent_started_at = time.monotonic()
        if self.voice_memory_tools_enabled:
            self._voice_memory_consent_started_at = time.monotonic()
        if self.voice_transcript_memory_enabled:
            self._transcript_consent_started_at = time.monotonic()

    @model_validator(mode="after")
    def unique_ids(self):
        if (self.pet_quiet_hours is not None
                and self.pet_quiet_hours[0] == self.pet_quiet_hours[1]):
            raise ValueError("Quiet hours need distinct start and end times")
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
            or not self.vision_model.strip()
            or not any(robot.device_id.strip() for robot in self.robots)
        ):
            raise ValueError(
                "Proactive camera autostart requires hardware, explicit camera consent, "
                "a local VLM and at least one mapped Xiaozhi device_id"
            )
        if self.fleet_social_autonomy_enabled and not self.fleet_text_sharing_enabled:
            raise ValueError("Automatic peer dialogue requires explicit local text sharing consent")
        if self.room_station_enabled and (
            self.mode != "hardware" or not is_local_serial_path(self.room_station_port)
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
        # Per-pet SQLite filenames may alias on a case-insensitive Mac APFS
        # volume. Reject case variants before initializing any fleet services.
        if not valid_unique_robot_ids(ids):
            raise ValueError("At least one robot and unique robot IDs are required")
        credential_names = [
            self.coordinator_token_env,
            self.tools_token_env,
            self.speech_bridge_token_env,
            *(r.token_env for r in self.robots),
        ]
        if len(set(credential_names)) != len(credential_names):
            raise ValueError("Fleet requires unique credential environment names")
        if self.mode == "hardware":
            hosts = [_head_host(r.head_url) for r in self.robots]
            if len(set(hosts)) != len(hosts):
                raise ValueError("Hardware fleet requires unique head hosts")
            voices = [r.voice.strip().casefold() for r in self.robots]
            if not all(voices) or len(set(voices)) != len(voices):
                raise ValueError("Hardware fleet requires nonblank unique voices")
        device_ids = [device_identity_key(r.device_id) for r in self.robots if r.device_id]
        if len(set(device_ids)) != len(device_ids):
            raise ValueError("device_id must uniquely identify a robot")
        docks = [r.dock_beacon_id for r in self.robots if r.dock_beacon_id is not None]
        if len(set(docks)) != len(docks):
            raise ValueError("Each physical dock beacon may be assigned to only one robot")
        markers = [r.dock_marker_id for r in self.robots if r.dock_marker_id is not None]
        if len(set(markers)) != len(markers):
            raise ValueError("Each physical dock marker may be assigned to only one robot")
        if self.vision_weights_sha256 is not None:
            digest = self.vision_weights_sha256
            if (
                type(digest) is not str
                or len(digest) != 64
                or any(ch not in "0123456789abcdefABCDEF" for ch in digest)
            ):
                raise ValueError("vision_weights_sha256 must be a 64-character SHA-256 hex digest")
            object.__setattr__(self, "vision_weights_sha256", digest.lower())
        if self.mode == "hardware" and any(
            r.dock_motion_qualified and r.dock_beacon_id is None
            for r in self.robots
        ):
            raise ValueError("Qualified dock approach requires assigned beacon ID")
        return self

    def __setattr__(self, name: str, value: object) -> None:
        _require_boolean_assignment(self, name, value)
        was_granted = (
            name == "voice_vision_tools_enabled"
            and getattr(self, "voice_vision_tools_enabled", False) is True
        )
        memory_was_granted = (
            name == "voice_memory_tools_enabled"
            and getattr(self, "voice_memory_tools_enabled", False) is True
        )
        social_was_granted = (
            name == "fleet_social_autonomy_enabled"
            and getattr(self, "fleet_social_autonomy_enabled", False) is True
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
        fanout_was_granted = (
            name == "fleet_text_auto_fanout_enabled"
            and getattr(self, "fleet_text_auto_fanout_enabled", False) is True
        )
        super().__setattr__(name, value)
        if was_granted and not self.voice_vision_tools_enabled:
            # Even an immediate re-enable is a NEW grant; old VLM evidence
            # and in-flight plans must never regain the prior authorization.
            self._camera_consent_generation += 1
            for listener_ref in tuple(self._camera_revocation_listeners):
                listener = listener_ref()
                if listener is not None:
                    listener(self)
        elif name == "voice_vision_tools_enabled" and self.voice_vision_tools_enabled and not was_granted:
            # Sent Opus text has a Mac monotonic timestamp. A late HTTP
            # receipt from the revoked grant cannot enter this new context.
            self._camera_consent_started_at = time.monotonic()
        if memory_was_granted and not self.voice_memory_tools_enabled:
            # Disabling memory access revokes outstanding asynchronous reads.
            # The next opt-in is a new grant even without SQLite edits.
            self._voice_memory_consent_generation += 1
        elif (name == "voice_memory_tools_enabled"
              and self.voice_memory_tools_enabled and not memory_was_granted):
            self._voice_memory_consent_started_at = time.monotonic()
        if room_was_granted and not self.room_station_context_enabled:
            # Room-station text from a previous grant cannot be emitted by a
            # late Ollama plan if the operator has already opted out.
            self._room_station_consent_generation += 1

        if transcript_was_granted and not self.voice_transcript_memory_enabled:
            # Immediate regrant does not revive an in-flight transcript write.
            self._transcript_consent_generation += 1
        elif (name == "voice_transcript_memory_enabled"
              and self.voice_transcript_memory_enabled and not transcript_was_granted):
            self._transcript_consent_started_at = time.monotonic()
        if sharing_was_granted and not self.fleet_text_sharing_enabled:
            # Peer relays and in-flight SQLite writes belong to the old grant.
            self._fleet_sharing_consent_generation += 1
        if social_was_granted and not self.fleet_social_autonomy_enabled:
            # Revoking and regranting social autonomy must not revive queued dialogue.
            self._fleet_social_autonomy_generation += 1
        if fanout_was_granted and not self.fleet_text_auto_fanout_enabled:
            # Selective-only mode retires an older automatic peer batch.
            self._fleet_auto_fanout_consent_generation += 1

    def register_camera_revocation(self, listener: Callable[[Settings], None]) -> None:
        """Keep a weak listener; the runtime owns its lifetime."""
        self._camera_revocation_listeners = [
            entry for entry in self._camera_revocation_listeners if entry() is not None
        ]
        self._camera_revocation_listeners.append(ref(listener))

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
    def voice_memory_consent_started_at(self) -> float:
        return self._voice_memory_consent_started_at

    @property
    def transcript_consent_started_at(self) -> float:
        return self._transcript_consent_started_at

    @property
    def room_station_consent_generation(self) -> int:
        return self._room_station_consent_generation

    @property
    def fleet_sharing_consent_generation(self) -> int:
        return self._fleet_sharing_consent_generation

    @property
    def fleet_social_autonomy_generation(self) -> int:
        return self._fleet_social_autonomy_generation

    @property
    def fleet_auto_fanout_consent_generation(self) -> int:
        return self._fleet_auto_fanout_consent_generation

    def robot(self, robot_id: str) -> RobotConfig:
        for robot in self.robots:
            if robot.id == robot_id:
                return robot
        raise KeyError(robot_id)


def secret(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if len(value) < 32:
        raise ValueError(f"Set {name} to a unique token of at least 32 characters")
    if not re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", value):
        raise ValueError(f"Set {name} to a valid ASCII bearer token")
    return value


def api_credentials(settings: Settings) -> tuple[str, str]:
    """Reject configured bearer reuse before the Mac starts serving requests."""
    operator = secret(settings.coordinator_token_env)
    tool = secret(settings.tools_token_env)
    if secrets.compare_digest(operator, tool):
        raise ValueError("Operator and tool tokens must be different")
    seen = {operator: settings.coordinator_token_env, tool: settings.tools_token_env}
    for name in (settings.speech_bridge_token_env, *(r.token_env for r in settings.robots)):
        # Simulation and unused transports need not configure a credential.
        if not os.environ.get(name, "").strip():
            continue
        value = secret(name)
        if value in seen:
            raise ValueError(f"Credential values must be distinct: {seen[value]} and {name}")
        seen[value] = name
    return operator, tool


class ConfigurationError(ValueError):
    """Rejected local configuration, safe to render in startup diagnostics."""


def _validation_diagnostic(error: ValidationError) -> str:
    issues = []
    for item in error.errors(include_input=False, include_context=False, include_url=False):
        loc = item["loc"]
        fields = Settings.model_fields
        parts = []
        for part in loc:
            if isinstance(part, int):
                parts.append(str(part))
            elif part in fields:
                parts.append(part)
                fields = RobotConfig.model_fields if part == "robots" else {}
            else:
                parts.append("unknown field")
                break
        issues.append(f"{'.'.join(parts) or 'configuration'} ({item['type']})")
    return "Invalid configuration: " + "; ".join(issues)


def _resolve_config_path(path: Path) -> Path:
    # Filesystem errors can contain private filenames or symlink targets.
    try:
        return path.resolve()
    except (OSError, RuntimeError, ValueError):
        pass
    raise ConfigurationError("Cannot resolve configuration path")


def load_settings(
    path: str | Path, *, overrides: Mapping[str, object] | None = None,
) -> Settings:
    """Load local settings with explicit, validated startup overrides.

    Overrides replace entire top-level values, including the robot list.
    They come from the trusted local caller, never environment or remote data.
    """
    path = _resolve_config_path(Path(path))
    try:
        with path.open("rb") as stream:
            data = tomllib.load(stream)
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        diagnostic = "invalid TOML or UTF-8"
    except (OSError, ValueError):
        diagnostic = "file unavailable"
    else:
        diagnostic = None
    if diagnostic is not None:
        raise ConfigurationError(f"Cannot read configuration: {diagnostic}")
    if overrides is not None:
        data.update(overrides)
    try:
        settings = Settings.model_validate(data)
    except ValidationError as error:
        diagnostic = _validation_diagnostic(error)
    else:
        diagnostic = None
    if diagnostic is not None:
        raise ConfigurationError(diagnostic)
    for robot in settings.robots:
        if robot.calibration and not robot.calibration.is_absolute():
            robot.calibration = _resolve_config_path(path.parent / robot.calibration)
    for robot in settings.robots:
        if robot.dock_calibration and not robot.dock_calibration.is_absolute():
            robot.dock_calibration = _resolve_config_path(path.parent / robot.dock_calibration)
    if settings.vision_weights and not settings.vision_weights.is_absolute():
        settings.vision_weights = _resolve_config_path(path.parent / settings.vision_weights)
    if not settings.trials_file.is_absolute():
        settings.trials_file = _resolve_config_path(path.parent / settings.trials_file)
    if not settings.memory_dir.is_absolute():
        # Keep lexical ancestors visible to MemoryStore's private-path guard.
        # resolve() would erase a symlink in the configured directory chain.
        settings.memory_dir = path.parent / settings.memory_dir
    return settings
