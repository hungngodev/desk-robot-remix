"""Image-generating mock head for development; never a physical acceptance result."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from copy import deepcopy
from io import BytesIO

import numpy as np
from PIL import Image, ImageDraw

from .transport import HeadError, drive_duration_ms, expected_ack, validate_command
from .vision import Detection, SceneChange

# Mirror guarded WROOM timing for development only; the body owns real safety.
# Quantize the sampled monotonic clock to integer milliseconds once per operation
# so rounding cannot extend a control lease at an exact expiration boundary.
BODY_IDLE_WATCHDOG_MS = 500
BODY_ACTIVE_WHEEL_WATCHDOG_MS = 200
DEFAULT_MAX_SIMULATOR_HISTORY = 1000


def _validate_max_history(max_history: int | None) -> int | None:
    if max_history is not None and (type(max_history) is not int or max_history < 0):
        raise ValueError("max_history must be a non-negative integer or None")
    return max_history


def _append_bounded(history: list, item: object, max_history: int | None) -> None:
    history.append(item)
    if max_history is not None and len(history) > max_history:
        del history[: len(history) - max_history]


class SimulatedHead:
    def __init__(self, robot_id: str, *, max_history: int | None = DEFAULT_MAX_SIMULATOR_HISTORY):
        self.id = robot_id
        self.armed = False
        self._max_history = _validate_max_history(max_history)
        self.commands: list[str] = []
        self._last_control_ms = 0
        self._motor = (0, 0)
        self._drive_deadline_ms = 0
        self.position = [130.0, 120.0]
        self.gripped = False
        self.lifted = False
        self.fail_command: str | None = None
        self.fail_snapshot = False
        self.fail_status = False
        self.show_target = True
        self._body_replay: dict | None = None

    def replay_body_status(self, sample: dict) -> None:
        """Install one raw synthetic receipt; replay grants no motor authority.

        Preserve caller-provided identity, missing fields and bad readings so
        the actual Mac validators, not this fixture, decide what to accept.
        A new head is required to resume ordinary movement simulation.
        """
        if not isinstance(sample, dict):
            raise ValueError("Simulated body replay requires a status dictionary")
        self._body_replay = deepcopy(sample)
        self.armed = False
        self._stop_motion()

    def _stop_motion(self) -> None:
        self._motor = (0, 0)
        self._drive_deadline_ms = 0

    def _watchdog(self, now: int) -> int:
        if not self.armed:
            self._stop_motion()
            return 0
        idle_deadline = self._last_control_ms + BODY_IDLE_WATCHDOG_MS
        active_deadline = self._last_control_ms + BODY_ACTIVE_WHEEL_WATCHDOG_MS
        # Simulate the first expiry even when no status poll occurred at that
        # instant. WROOM checks the active watchdog before drive expiry on a tie.
        active_expired = (
            any(self._motor)
            and self._drive_deadline_ms >= active_deadline
            and now >= active_deadline
        )
        if active_expired or now >= idle_deadline:
            self.armed = False
            self._stop_motion()
            return 0
        if now >= self._drive_deadline_ms:
            self._stop_motion()
        limit = BODY_ACTIVE_WHEEL_WATCHDOG_MS if any(self._motor) else BODY_IDLE_WATCHDOG_MS
        return limit - (now - self._last_control_ms)

    async def status(self):
        now = round(time.monotonic() * 1000)
        watchdog_ms = self._watchdog(now)
        if self.fail_status:
            raise HeadError("Simulated body status failure")
        if self._body_replay is not None:
            return deepcopy(self._body_replay)
        return {
            "robot_id": self.id,
            "armed": self.armed,
            "motor": {"m0": self._motor[0], "m1": self._motor[1]},
            "drive_ms": max(0, self._drive_deadline_ms - now),
            "servo": {"position_source": "commanded"},
            "watchdog_ms": watchdog_ms,
        }

    async def command(self, command):
        op = validate_command(command)
        _append_bounded(self.commands, command, self._max_history)
        now = round(time.monotonic() * 1000)
        self._watchdog(now)
        if self.fail_command and command.startswith(self.fail_command):
            raise HeadError("Simulated uncertain ACK")
        if self._body_replay is not None and op in {"arm", "drive", "lift", "grip", "keepalive"}:
            raise HeadError("Simulated body replay has no motion authority")
        if op == "arm":
            self._stop_motion()
            self.armed = True
        elif op in {"disarm", "halt"}:
            self._stop_motion()
            self.armed = False
        elif op == "stop":
            self._stop_motion()
        elif op in {"drive", "lift", "grip", "keepalive"} and not self.armed:
            raise HeadError("Body disarmed")
        if op in {"arm", "drive", "lift", "grip", "keepalive"} or (
            op == "stop" and self.armed
        ):
            self._last_control_ms = now
        if op == "drive":
            args = command.split()[1:]
            left, right = map(int, args[:2])
            duration = drive_duration_ms(command)
            self._motor = (left, right)
            self._drive_deadline_ms = now + duration
            if left or right:
                if left == -right:
                    self.position[0] -= 10 if left > 0 else -10
                else:
                    self.position[1] -= 10 if left > 0 else -10
        elif op == "grip":
            self.gripped = int(command.split()[1]) > 90
        elif op == "lift":
            self.lifted = self.gripped and int(command.split()[1]) > 90
        return {"ok": True, "reply": expected_ack(command), "robot_id": self.id}

    async def snapshot(self):
        if self.fail_snapshot:
            raise HeadError("Simulated camera failure")
        image = Image.new("RGB", (200, 200), "white")
        if self.show_target:
            x, y = (100, 65) if self.lifted else self.position
            ImageDraw.Draw(image).rectangle((x - 7, y - 5, x + 7, y + 5), fill=(240, 0, 0))
        out = BytesIO()
        image.save(out, "JPEG")
        return out.getvalue()


class SimulationVision:
    async def detect(self, jpeg, label):
        pixels = np.array(Image.open(BytesIO(jpeg)).convert("RGB"))
        yy, xx = np.where((pixels[:, :, 0] > 150) & (pixels[:, :, 1] < 80) & (pixels[:, :, 2] < 80))
        if len(xx) == 0:
            return []
        return [
            Detection(
                label,
                0.99,
                (float(xx.min()), float(yy.min()), float(xx.max() + 1), float(yy.max() + 1)),
            )
        ]


class SimulatedSpeaker:
    # Test-only capability: mirrors checks at the nonblocking simulated send.
    # It does not assert any physical decoder, DMA, or loudspeaker state.
    supports_permission_checks = True

    def __init__(self, *, max_history: int | None = DEFAULT_MAX_SIMULATOR_HISTORY):
        self._max_history = _validate_max_history(max_history)
        self.spoken = []

    @asynccontextmanager
    async def session(self, robots):
        yield

    async def say(self, robot, text, *, permission_check=None):
        if permission_check is not None and not permission_check():
            raise RuntimeError("Simulated speech permission revoked")
        _append_bounded(self.spoken, (robot.id, text), self._max_history)


class SimulatedChat:
    async def reply(self, history):
        return "I see a candy on the desk." if len(history) <= 2 else "Let us take turns exploring."



class SimulatedScene:
    """Deterministic fake semantics for tests only; never evidence of real vision."""

    async def compare(self, before: bytes, after: bytes) -> SceneChange | None:
        if before == after:
            return None
        return SceneChange("object", "A red desk object changed position", 0.99)
