"""Speech frames must be valid Unicode before reaching the Xiaozhi owner."""
import json

import pytest
from desk_robot.streamed_ollama import ollama_speech_segments


async def _frames(*texts):
    for index, text in enumerate(texts):
        yield json.dumps({
            "message": {"role": "assistant", "content": text},
            "done": index == len(texts) - 1,
        })


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["\ud800", "\udfff"])
async def test_invalid_unicode_frame_cannot_emit_even_a_valid_prefix(invalid):
    stream = ollama_speech_segments(_frames("A good sentence. " + invalid))
    with pytest.raises(RuntimeError, match="UTF-8"):
        await anext(stream)


@pytest.mark.asyncio
async def test_invalid_later_frame_does_not_promote_partial_turn():
    stream = ollama_speech_segments(_frames("Already sent. ", "\ud800"))
    assert await anext(stream) == "Already sent."
    with pytest.raises(RuntimeError, match="UTF-8"):
        await anext(stream)


@pytest.mark.asyncio
async def test_valid_non_ascii_and_supplementary_unicode_remain_speakable():
    assert [s async for s in ollama_speech_segments(_frames("Chào bạn 😀."))] == [
        "Chào bạn 😀."
    ]
