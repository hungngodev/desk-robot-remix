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
from dataclasses import dataclass


def verify_native_server(greeting: dict, requested_model: str) -> None:
    """Strict upstream vLLM-Omni capability negotiation, not model guessing.

    Reuse docs/serving/realtime_duplex_api.md's session.created contract.
    An arbitrary Realtime-compatible text backend must never receive XIAO PCM
    or claim native camera and duplex support by returning only an event type.
    """
    if not isinstance(greeting, dict) or greeting.get("type") != "session.created":
        raise RuntimeError("Native realtime server did not create a session")
    session = greeting.get("session")
    if not isinstance(session, dict) or session.get("model") != requested_model:
        raise RuntimeError("Model identity mismatch in native session.created")
    capabilities = session.get("capabilities")
    if (not isinstance(capabilities, dict)
            or capabilities.get("implementation_level") != "model_native_duplex"
            or capabilities.get("supports_input_append") is not True
            or capabilities.get("supports_barge_in") is not True
            or type(capabilities.get("chunk_period_ms")) is not int
            or capabilities["chunk_period_ms"] != 1000):
        raise RuntimeError("Model lacks required native duplex or 1s video/audio capability")
    if (session.get("input_audio_format") != "pcm16"
            or session.get("output_audio_format") != "pcm16"):
        raise RuntimeError("Native model did not negotiate PCM16 input and output")
    audio = session.get("audio")
    input_fmt = audio.get("input") if isinstance(audio, dict) else None
    output_fmt = audio.get("output") if isinstance(audio, dict) else None
    input_hz = input_fmt.get("sample_rate_hz") if isinstance(input_fmt, dict) else None
    output_codec = output_fmt.get("format") if isinstance(output_fmt, dict) else None
    output_hz = (
        output_codec.get("rate") if isinstance(output_codec, dict) else None
    )
    if (type(input_hz) is not int or input_hz != 16000
            or not isinstance(output_codec, dict)
            or output_codec.get("type") != "audio/pcm"
            or type(output_hz) is not int or output_hz != 24000):
        raise RuntimeError("Native model PCM rates incompatible with XIAO Opus bridge")


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
    MAX_RESPONSES_PER_EPOCH = 4096  # Bound replay state; reconnect on exhaustion.

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
        # Real Mac reception identity, not the position in an audio byte
        # counter. The same JPEG cannot be forwarded twice as fresh video.
        self._last_video_receipt_us = 0
        self._video_resume_audio_ms = 0  # one complete fresh unit after interruption
        self._needs_new_input = False
        self._input_after_interrupt = False
        self._server_response_epoch: int | None = None
        self._server_epoch_seen = 0
        self._session_created = False
        self._min_server_epoch: int | None = None
        self._interrupted = False
        self._response_ids_epoch: int | None = None
        self._response_ids_seen: set[str] = set()

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
                     camera_age_ms: int | None = None,
                     frame_receipt_us: int | None = None) -> dict:
        """One 1..1000 ms mono 16 kHz chunk with provenance-tagged JPEG.

        vLLM-Omni duplex consumes video with the append that CLOSES each
        complete one-second model unit. Unlike Gemini Live's independent
        video input, a short unfinished audio unit cannot truthfully carry
        a processed video frame. Pick a fresh distinct frame at that boundary.
        """
        if type(speech) is not bool or not isinstance(pcm16, bytes):
            raise ValueError("Speech must be real PCM16 and VAD must be boolean")
        if not 32 <= len(pcm16) <= self.INPUT_RATE * 2:
            raise ValueError("PCM input must be between 1 and 1000 ms")
        if len(pcm16) % 32:
            raise ValueError("PCM must contain an integral millisecond at 16 kHz")
        duration = len(pcm16) // 32
        if jpeg is not None and (
            not isinstance(jpeg, bytes)
            or not 10 <= len(jpeg) <= self.MAX_IMAGE_BYTES
            or not jpeg.startswith(b"\xff\xd8")
            or not jpeg.endswith(b"\xff\xd9")
            or type(camera_age_ms) is not int
            or not 0 <= camera_age_ms <= 1000
            or type(frame_receipt_us) is not int
            or frame_receipt_us <= 0
        ):
            raise ValueError("Only fresh bounded JPEG from current head allowed")
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
            if (not speech and self.input_ms >= self._video_resume_audio_ms):
                # A quiet room must not permanently disable native proactive
                # output after a brief interruption. Re-enable only after one
                # full NEW unit of authenticated PCM; during actual speech,
                # retain the existing commit/turn-end barrier.
                self._needs_new_input = False
        # The upstream MiniCPM-o duplex prefill groups one FULL second of
        # audio with the chosen frame. Never strand a JPEG on a partial unit.
        # Live video is NOT contingent on human speech. MiniCPM-o is a
        # proactive full-duplex audio/video model; it must see real quiet-room
        # visual changes alongside continuous silent/background PCM. After
        # a barge, first complete a fresh audio unit before sending images.
        if (jpeg is not None
                and self.input_ms // 1000 > previous_ms // 1000
                and self.input_ms >= self._video_resume_audio_ms
                and frame_receipt_us > self._last_video_receipt_us):
            event["video_frames"] = [base64.b64encode(jpeg).decode("ascii")]
            self._last_video_receipt_us = frame_receipt_us
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
        self._interrupted = True
        # Both response.cancel AND output_audio_buffer.clear advance the
        # upstream native server epoch. Count both, including consecutive
        # barge-ins before any newly created response has arrived.
        self._min_server_epoch = max(
            self._min_server_epoch or 0,
            self._server_response_epoch or 0,
            self._server_epoch_seen,
        ) + 2
        self.accept_output = False
        self.response_id = None
        self.generated_bytes = 0
        self.played_ms = 0
        self._needs_new_input = True
        self._input_after_interrupt = False
        # An interrupted fractional audio unit cannot borrow a prior JPEG.
        # Resume proactive vision after one entire new model audio unit,
        # regardless of whether anyone is speaking.
        self._video_resume_audio_ms = self.input_ms + 1000
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
            if self._session_created:
                raise ValueError("Duplicate native session.created")
            session = event.get("session")
            initial = session.get("epoch", 0) if isinstance(session, dict) else 0
            if type(initial) is not int or initial < 0:
                raise ValueError("Invalid native session epoch")
            self._server_epoch_seen = initial
            self._session_created = True
            # A native session is new, so a local audio abort issued before
            # connection cannot fence every future legitimate model reply.
            self._min_server_epoch = None
            self._interrupted = False
            self._needs_new_input = False
            self._input_after_interrupt = False
            self.accept_output = True
            return None
        if kind == "response.listen":
            # Model-native silence can arrive without response.created. Its
            # accepted epoch still advances the monotonic session fence, so
            # a delayed older listen cannot later count as a fresh decision.
            if self.model_listen_current(event):
                self._server_epoch_seen = event["epoch"]
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
            # Official vLLM-Omni OpenAI-compatible envelope nests the raw
            # duplex event under response.metadata.duplex_event, not directly
            # in response.metadata. Without this our first barge-in would
            # permanently suppress otherwise valid subsequent responses.
            native = (
                metadata.get("duplex_event")
                if isinstance(metadata, dict) else None
            )
            server_epoch = (
                native.get("epoch") if isinstance(native, dict)
                else event.get("epoch")
            )
            if server_epoch is not None and (
                type(server_epoch) is not int or server_epoch < 0
            ):
                raise ValueError("Invalid realtime response epoch")
            if self._session_created and server_epoch is None:
                # The authenticated model-native server advertises epochs.
                # A response without one cannot establish speech authority.
                return None
            # Never allow an old response to regain the speaker owner, even
            # AFTER a newer epoch has already been accepted. The two urgent
            # cancellation events advance the upstream epoch independently.
            if (server_epoch is not None and (
                server_epoch < self._server_epoch_seen or (
                    self._min_server_epoch is not None
                    and server_epoch < self._min_server_epoch
                )
            )) or (self._min_server_epoch is not None and server_epoch is None):
                # Once a physical barge/cancel established an epoch floor,
                # an epochless response is never safe, even after a valid new
                # response cleared _interrupted. vLLM-Omni advertises epoch
                # in response.metadata.duplex_event for native sessions.
                return None
            # Several utterances can share a server epoch. Retain accepted
            # identities so A -> B -> delayed A cannot resurrect old output.
            if response_id == self.response_id:
                return None
            if server_epoch != self._response_ids_epoch:
                self._response_ids_seen.clear()
                self._response_ids_epoch = server_epoch
            if response_id in self._response_ids_seen:
                return None
            if len(self._response_ids_seen) >= self.MAX_RESPONSES_PER_EPOCH:
                raise RuntimeError("Native response replay window exhausted; reconnect")
            self._response_ids_seen.add(response_id)
            self._interrupted = False
            if server_epoch is not None:
                self._server_epoch_seen = server_epoch
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
            # The native server supplies a per-delta epoch. After a barge,
            # an epochless delta cannot prove it belongs to the freshly
            # accepted response, even if its response_id looks plausible.
            if ((self._session_created or self._min_server_epoch is not None)
                    and (not isinstance(meta, dict)
                         or type(meta.get("epoch")) is not int)):
                return None
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
            cleared_id = event.get("response_id")
            # Upstream clear acknowledgements can arrive after a newer
            # response.created. An old or unidentifiable acknowledgement
            # cannot revoke that newer response's physical speaker lease.
            # Our own interrupt() already stops output synchronously.
            if (self.response_id is None
                    or cleared_id == self.response_id):
                self.accept_output = False
        return None

    def model_listen_current(self, event: dict) -> bool:
        """Count only native model silence belonging to the current input.

        Model-owned listen decisions can arrive with no response.created, but
        always carry the upstream epoch. Delayed prior-turn decisions may not
        be counted as current speech arbitration after a physical barge.
        """
        if not isinstance(event, dict) or event.get("type") != "response.listen":
            return False
        epoch = event.get("epoch")
        response_id = event.get("response_id")
        return (
            type(epoch) is int and epoch >= self._server_epoch_seen
            and (self._min_server_epoch is None
                 or epoch >= self._min_server_epoch)
            and not self._needs_new_input
            and (response_id is None or response_id == self.response_id)
        )

    def playback_ack(self, *, response_id: str, actually_played_ms: int,
                     truncate: bool = False) -> dict:
        """Only call from actual speaker playback progress, never from HTTP send.

        This function intentionally cannot guess progress or mark generated
        audio as heard without a caller-provided physical playback measurement.
        """
        if (not isinstance(response_id, str) or not response_id
                or self.response_id is None
                or self._interrupted
                or self.generated_bytes <= 0
                or type(actually_played_ms) is not int
                or type(truncate) is not bool
                or self.response_id != response_id
                # Duplicate or zero progress is not evidence that any
                # additional audio played. A final increasing drain receipt
                # remains valid even after response.done disabled generation.
                or actually_played_ms <= self.played_ms
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
