from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Protocol

from PIL import Image


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    box: tuple[float, float, float, float]

    @property
    def center(self):
        x0, y0, x1, y1 = self.box
        return ((x0 + x1) / 2, (y0 + y1) / 2)


class Vision(Protocol):
    async def detect(self, jpeg: bytes, label: str) -> list[Detection]: ...


class YoloWorldVision:
    """Existing Ultralytics detector. An explicitly supplied local weights file is required."""

    def __init__(self, weights: Path | None):
        self.weights = weights
        self.model = None
        self.lock = asyncio.Lock()

    async def detect(self, jpeg: bytes, label: str) -> list[Detection]:
        async with self.lock:
            return await asyncio.to_thread(self._detect, jpeg, label)

    def _detect(self, jpeg: bytes, label: str) -> list[Detection]:
        if self.weights is None or not self.weights.is_file():
            raise RuntimeError(
                "Install vision extra and explicitly download/set local YOLO-World weights"
            )
        if self.model is None:
            from ultralytics import YOLOWorld

            self.model = YOLOWorld(str(self.weights))
        self.model.set_classes([label])
        # Letterbox/coordinate restoration is handled by the upstream model, not guessed here.
        image = Image.open(BytesIO(jpeg)).convert("RGB")
        result = self.model.predict(image, verbose=False, device="cpu")[0]
        return [
            Detection(label, float(box.conf.item()), tuple(map(float, box.xyxy[0].tolist())))
            for box in result.boxes
        ]


def image_size(jpeg: bytes) -> tuple[int, int]:
    with Image.open(BytesIO(jpeg)) as im:
        im.verify()
    with Image.open(BytesIO(jpeg)) as im:
        return im.size
