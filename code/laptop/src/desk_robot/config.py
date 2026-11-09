from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RobotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    name: str
    persona: str = "You are a friendly desk companion. Keep replies to one short sentence."
    head_url: str = "http://127.0.0.1:8081"
    token_env: str
    device_id: str = ""
    motion_enabled: bool = False
    calibration: Path | None = None
    voice: str = "af_heart"

    @model_validator(mode="after")
    def local_http(self):
        from urllib.parse import urlparse

        u = urlparse(self.head_url)
        if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
            raise ValueError("head_url must be an http(s) URL without embedded credentials")
        return self


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
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
    max_job_seconds: float = Field(default=45, ge=1, le=120)
    trials_file: Path = Path("data/physical-trials.jsonl")
    memory_dir: Path = Path("../data/private/memory")

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [r.id for r in self.robots]
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("At least one robot and unique robot IDs are required")
        device_ids = [r.device_id for r in self.robots if r.device_id]
        if len(set(device_ids)) != len(device_ids):
            raise ValueError("device_id must uniquely identify a robot")
        return self

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
    if settings.vision_weights and not settings.vision_weights.is_absolute():
        settings.vision_weights = (path.parent / settings.vision_weights).resolve()
    if not settings.trials_file.is_absolute():
        settings.trials_file = (path.parent / settings.trials_file).resolve()
    if not settings.memory_dir.is_absolute():
        settings.memory_dir = (path.parent / settings.memory_dir).resolve()
    return settings
