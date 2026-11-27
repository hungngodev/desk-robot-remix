"""Deterministic native turn fencing after cancellation."""
import base64

import pytest
from desk_robot.realtime_omni_protocol import OmniDuplexWire


def _created(response_id, epoch):
    return {"type": "response.created", "response_id": response_id, "epoch": epoch}


def _delta(response_id, epoch):
    return {
        "type": "response.output_audio.delta",
        "response_id": response_id,
        "metadata": {"epoch": epoch},
        "format": "pcm16",
        "sample_rate_hz": 24000,
        "delta": base64.b64encode(bytes(4800)).decode("ascii"),
    }


@pytest.mark.parametrize("interrupts", [1, 2])
def test_nonfinal_commit_cannot_release_interrupted_turn(interrupts):
    wire = OmniDuplexWire()
    wire.handle_event({"type": "session.created", "session": {"epoch": 0}})
    wire.handle_event(_created("old", 0))
    assert wire.handle_event(_delta("old", 0)) is not None
    for _ in range(interrupts):
        wire.interrupt()
    epoch = 2 * interrupts
    wire.append_audio(bytes(3200), speech=True)
    assert wire.commit(final=False)["final"] is False
    wire.handle_event(_created("premature", epoch))
    assert wire.response_id is None
    assert not wire.accept_output
    assert wire.handle_event(_delta("premature", epoch)) is None
    assert not wire.model_listen_current({"type": "response.listen", "epoch": epoch})
    assert wire.generated_bytes == 0

    assert wire.commit(final=True)["final"] is True
    wire.handle_event(_created("stale", epoch - 1))
    assert wire.response_id is None
    wire.handle_event(_created("current", epoch))
    assert wire.response_id == "current"
    assert wire.handle_event(_delta("current", epoch)) is not None
    assert wire.played_ms == 0


def test_final_commit_without_fresh_audio_cannot_release_interrupt():
    wire = OmniDuplexWire()
    wire.interrupt()
    wire.commit(final=True)
    wire.handle_event(_created("premature", 2))
    assert wire.response_id is None
    assert not wire.accept_output
    assert wire.handle_event(_delta("premature", 2)) is None
    wire.append_audio(bytes(32000), speech=False)
    wire.handle_event(_created("quiet", 2))
    assert wire.handle_event(_delta("quiet", 2)) is not None
