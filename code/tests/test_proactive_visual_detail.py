"""Host-only checks for truthful proactive visual admission."""

import json
from io import BytesIO

import httpx
import pytest
from desk_robot.vision import OllamaScene
from PIL import Image, ImageDraw, ImageFilter


def _jpeg(image):
    output = BytesIO()
    image.save(output, "JPEG", quality=25)
    return output.getvalue()


def _clear():
    image = Image.new("RGB", (128, 96), "gray")
    ImageDraw.Draw(image).rectangle((56, 42, 72, 54), fill=(150, 150, 150))
    return image


@pytest.mark.parametrize("condition", ["dark", "overexposed", "covered", "blurred"])
async def test_proactive_comparison_rejects_near_flat_latest_image(condition):
    images = {
        "dark": Image.new("RGB", (128, 96), "black"),
        "overexposed": Image.new("RGB", (128, 96), "white"),
        "covered": Image.new("RGB", (128, 96), (70, 40, 20)),
        "blurred": _clear().filter(ImageFilter.GaussianBlur(20)),
    }
    calls = []

    def handler(request):
        calls.append(request)
        # Deliberately untrustworthy, confident VLM: it must not even be asked.
        return httpx.Response(200, json={"message": {"content": json.dumps({
            "notable": True, "kind": "person",
            "description": "A person appeared", "confidence": 0.99,
        })}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        scene = OllamaScene(client, url="http://local:11434", model="local-vlm")
        assert await scene.compare(_jpeg(_clear()), _jpeg(images[condition])) is None
        assert calls == []
        # Recovery from a flat earlier exposure must not disable useful new frames.
        recovered = await scene.compare(_jpeg(images[condition]), _jpeg(_clear()))
        assert recovered is not None
        assert len(calls) == 1
