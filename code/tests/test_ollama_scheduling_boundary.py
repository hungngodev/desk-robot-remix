"""Foreign provider scheduling cannot authorize local speech."""
import json

import pytest
from desk_robot.streamed_ollama import ollama_speech_segments


async def _lines(packet):
    yield json.dumps(packet)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["scheduling", "functionResponseScheduling",
                                   "function_response_scheduling"])
@pytest.mark.parametrize("value", ["SILENT", "INTERRUPT", "WHEN_IDLE", None])
@pytest.mark.parametrize("nested", [False, True])
async def test_foreign_scheduling_is_not_speech_authority(field, value, nested):
    packet = {"message": {"role": "assistant", "content": "Do not speak. "}, "done": True}
    (packet["message"] if nested else packet)[field] = value
    stream = ollama_speech_segments(_lines(packet))
    with pytest.raises(RuntimeError, match="scheduling"):
        await anext(stream)


@pytest.mark.asyncio
async def test_thinking_metadata_remains_private():
    packet = {"message": {"role": "assistant", "thinking": "Private reasoning",
                          "content": "Hello."}, "done": True}
    assert [s async for s in ollama_speech_segments(_lines(packet))] == ["Hello."]
