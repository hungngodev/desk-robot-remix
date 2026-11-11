"""Opt-in vLLM-Omni realtime wire protocol for native audio/video duplex.

Adapted to the documented upstream OpenAI Realtime-compatible protocol:
https://github.com/vllm-project/vllm-omni/blob/main/docs/serving/realtime_duplex_api.md

This module does NOT drive the XIAO speaker or bypass the pinned Xiaozhi
session. An actual adapter must bring real, authenticated head PCM and camera
frames, route generated 24 kHz PCM through the existing Opus speaker owner,
and report only physically acknowledged playback. Nothing here can arm,
charge or move a robot. Default deployment remains Xiaozhi + Ollama.
"""
from __future__ import annotations

import base64
import binascii
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class OmniAudioDelta:
    """Actual model PCM16 output, not a playback acknowledgement."""

    response_id: str
    pcm24k: bytes
    total_generated_ms: int


class OmniDuplexWire:
    INPUT_RATE = 16000
    OUTPUT_RATE = 24000
    MAX_INPUT_MS = 1000
    MAX_IMAGE_BYTES = 1_000_000
    MAX_OUTPUT_BYTES = 96_000  # A two-second 24k PCM16 response unit.

    def __init__(self, *, model: str = "openbmb/MiniCPM-o-4_5",
                 instructions: str = "You are a helpful desk companion."):
        if (not isinstance(model, str) or not 1 <= len(model) <= 150
                or not isinstance(instructions, str)
                or not 1 <= len(instructions) <= 2000):
            raise ValueError("Invalid local omni model or instruction bounds")
        self.model = model
        self.instructions = instructions
        self.input_ms = 0
        self.epoch = 0
        self.response_id: str | None = None
        self.generated_bytes = 0
        self.played_ms = 0
        self.accept_output = True
        self.frames_sent = 0
        self._needs_new_input = False
        self._input_after_interrupt = False
        self._server_response_epoch: int | None = None

    def session_update(self) -> dict:
        return {
            "type": "session.update",
            "session": {
                "model": self.model,
                "modalities": ["audio", "text"],
                "instructions": self.instructions,
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "turn_detection": None,
                "overlap_policy": "listen_only",
                # Do not silently mark audio 'heard' when merely queued or sent.
                "playback_commit_policy": "ack_only",
                "extra_body": {"auto_response": True},
            },
        }

    def append_audio(self, pcm16: bytes, *, speech: bool,
                     jpeg: bytes | None = None,
                     camera_age_ms: int | None = None) -> dict:
        """One 1..1000 ms mono 16 kHz chunk, with at most one timely camera JPEG.

        vLLM Omni packs a visual frame onto the append closing a 1 s model
        unit. Keeping one image per unit avoids the long-video queue growth
        reported upstream for stacked frames.
        """
        if type(speech) is not bool or not isinstance(pcm16, bytes):
            raise ValueError("Speech must be real PCM16 and VAD must be boolean")
        if not 32 <= len(pcm16) <= self.INPUT_RATE * 2:
            raise ValueError("PCM input must be between 1 and 1000 ms")
        if len(pcm16) % 32:
            raise ValueError("PCM must contain an integral millisecond at 16 kHz")
        duration = len(pcm16) // 32
        previous_ms = self.input_ms
        self.input_ms += duration
        event = {
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(pcm16).decode("ascii"),
            "format": "pcm16",
            "sample_rate_hz": self.INPUT_RATE,
            "duration_ms": duration,
            "audio_end_ms": self.input_ms,
            "is_speech": speech,
        }
        if self._needs_new_input:
            self._input_after_interrupt = True
        if jpeg is not None:
            if (not isinstance(jpeg, bytes)
                    or not 10 <= len(jpeg) <= self.MAX_IMAGE_BYTES
                    or not jpeg.startswith(b"\xff\xd8")
                    or type(camera_age_ms) is not int
                    or not 0 <= camera_age_ms <= 1000):
                raise ValueError("Only fresh bounded JPEG from current head allowed")
            if self.input_ms // 1000 > previous_ms // 1000:
                event["video_frames"] = [base64.b64encode(jpeg).decode("ascii")]
                self.frames_sent += 1
        return event

    def commit(self, *, final: bool = True) -> dict:
        if type(final) is not bool:
            raise ValueError("Final must be a boolean")
        if self._needs_new_input and self._input_after_interrupt:
            self._needs_new_input = False
        return {
            "type": "input_audio_buffer.commit",
            "final": final,
            "response_create": False,  # Model-native turn-taking.
        }

    def interrupt(self) -> tuple[dict, ...]:
        """Cancel stale backend speech; the separate head MUST flush its DMA."""
        self.epoch += 1
        self.accept_output = False
        self.response_id = None
        self.generated_bytes = 0
        self.played_ms = 0
        self._needs_new_input = True
        self._input_after_interrupt = False
        self._server_response_epoch = None
        return (
            {"type": "response.cancel"},
            {"type": "output_audio_buffer.clear"},
        )

    def handle_event(self, event: dict) -> OmniAudioDelta | None:
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise ValueError("Invalid realtime backend event")
        kind = event["type"]
        if kind == "error":
            raise RuntimeError("Realtime backend reported a protocol error")
        if kind == "session.created":
            self.accept_output = True
            return None
        if kind == "response.created":
            # A queued response from before an interruption must not restart
            # physical speech while the new human turn is still being heard.
            if self._needs_new_input:
                return None
            response = event.get("response")
            response_id = (
                event.get("response_id") or (
                    response.get("id") if isinstance(response, dict) else None
                )
            )
            if not isinstance(response_id, str) or not 1 <= len(response_id) <= 128:
                raise ValueError("Missing realtime response identity")
            metadata = response.get("metadata") if isinstance(response, dict) else None
            server_epoch = (
                metadata.get("epoch") if isinstance(metadata, dict)
                else event.get("epoch")
            )
            if server_epoch is not None and type(server_epoch) is not int:
                raise ValueError("Invalid realtime response epoch")
            self._server_response_epoch = server_epoch
            self.response_id = response_id
            self.generated_bytes = 0
            self.played_ms = 0
            self.accept_output = True
            return None
        if kind == "response.output_audio.delta":
            if not self.accept_output or self.response_id is None:
                return None
            if event.get("response_id") != self.response_id:
                return None  # Old backend response after a new human turn.
            meta = event.get("metadata")
            if isinstance(meta, dict) and meta.get("epoch") is not None:
                if (type(meta["epoch"]) is not int
                        or (self._server_response_epoch is not None
                            and meta["epoch"] != self._server_response_epoch)):
                    return None
            if event.get("format") != "pcm16" or event.get("sample_rate_hz") != 24000:
                raise ValueError("Unrecognized realtime audio codec or sample rate")
            encoded = event.get("delta")
            if not isinstance(encoded, str) or len(encoded) > 130_000:
                raise ValueError("Unbounded realtime audio delta")
            try:
                pcm = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError("Invalid base64 audio from realtime model") from exc
            if not pcm or len(pcm) % 2 or len(pcm) > self.MAX_OUTPUT_BYTES:
                raise ValueError("Malformed or oversized 24 kHz audio PCM")
            self.generated_bytes += len(pcm)
            return OmniAudioDelta(
                response_id=self.response_id,
                pcm24k=pcm,
                total_generated_ms=self.generated_bytes * 1000
                // (self.OUTPUT_RATE * 2),
            )
        if kind == "response.done" and event.get("response_id") == self.response_id:
            self.accept_output = False
        if kind == "output_audio_buffer.cleared":
            self.accept_output = False
        return None

    def playback_ack(self, *, response_id: str, actually_played_ms: int,
                     truncate: bool = False) -> dict:
        """Only call from actual speaker playback progress, never from HTTP send.

        This function intentionally cannot guess progress or mark generated
        audio as heard without a caller-provided physical playback measurement.
        """
        if (type(actually_played_ms) is not int
                or type(truncate) is not bool
                or self.response_id != response_id
                or actually_played_ms < self.played_ms
                or actually_played_ms > self.generated_bytes * 1000
                   // (self.OUTPUT_RATE * 2)):
            raise ValueError("No actual monotonic playback evidence")
        self.played_ms = actually_played_ms
        return {
            "type": "playback.ack",
            "response_id": response_id,
            "played_ms": actually_played_ms,
            "committed_ms": actually_played_ms,
            "truncate": truncate,
        }
