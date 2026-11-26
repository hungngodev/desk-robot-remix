"""Direct visual questions abstain before guessing from an obscured latest frame."""
import json
from io import BytesIO
from unittest.mock import AsyncMock, Mock

import pytest
from desk_robot.vision import OllamaScene
from PIL import Image


ABSTENTION = "I can't tell from my camera right now."


def jpeg(color: int, *, detail: bool = False) -> bytes:
    image = Image.new("RGB", (64, 48), (color,) * 3)
    if detail:
        image.paste((220, 220, 220), (0, 0, 32, 48))
    output = BytesIO()
    image.save(output, "JPEG")
    return output.getvalue()


def model_reply(confidence: float, supported: bool = True) -> AsyncMock:
    response = Mock()
    response.json.return_value = {"message": {"content": json.dumps({
        "answer": "A red key is visible.", "confidence": confidence,
        "visually_supported": supported,
    })}}
    return AsyncMock(return_value=response)


@pytest.mark.parametrize("color", [0, 4, 128, 255])
@pytest.mark.parametrize("historical", [False, True])
async def test_flat_latest_frame_never_reaches_model(color, historical):
    client = Mock(post=model_reply(0.99))
    scene = OllamaScene(client, url="http://local:11434", model="local-vlm")
    frames = [jpeg(20, detail=True)] if historical else []
    frames.append(jpeg(color))
    assert await scene.answer("What is on my desk?", frames) == ABSTENTION
    client.post.assert_not_awaited()


@pytest.mark.parametrize(("confidence", "supported", "expected"), [
    (0.64, True, ABSTENTION),
    (0.99, False, ABSTENTION),
    (0.65, True, "A red key is visible."),
])
async def test_supported_detail_retains_existing_confidence_gate(confidence, supported, expected):
    client = Mock(post=model_reply(confidence, supported))
    scene = OllamaScene(client, url="http://local:11434", model="local-vlm")
    assert await scene.answer("What is on my desk?", [jpeg(20, detail=True)]) == expected
    client.post.assert_awaited_once()
    prompt = client.post.call_args.kwargs["json"]["messages"][0]["content"]
    assert "low light, blur, occlusion" in prompt
    assert "visually_supported=false" in prompt


async def test_obscured_answer_still_rechecks_consent():
    client = Mock(post=model_reply(0.99))
    scene = OllamaScene(client, url="http://local:11434", model="local-vlm")
    admissions = iter((True, False))
    with pytest.raises(RuntimeError, match="invalidated before model submission"):
        await scene.answer("What is on my desk?", [jpeg(0)], admit=lambda: next(admissions))
    client.post.assert_not_awaited()
