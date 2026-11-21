"""Explicit operator-only XIAO checkerboard capture; no motion or background video.

Copies original authenticated JPEG bytes to a new private folder. Each image
requires a new operator confirmation and a disarmed WROOM status. The captured
images are private local media; review and delete them after calibration.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
from pathlib import Path
from typing import Awaitable, Callable

from PIL import Image


async def capture_checkerboards(
    head, folder: Path, *, count: int,
    prompt: Callable[[int], Awaitable[None]],
) -> dict:
    """One read-only fresh JPEG per confirmed board placement, all or nothing."""
    if type(count) is not int or not 12 <= count <= 40:
        raise ValueError("Require 12 to 40 distinct checkerboard captures")
    if not callable(prompt):
        raise ValueError("Explicit placement confirmation required")
    # Do not merge private images with an existing folder or other session.
    folder.mkdir(mode=0o700)
    saved = []
    size = None
    success = False
    try:
        for index in range(count):
            await prompt(index + 1)
            status = await asyncio.wait_for(head.status(), timeout=3)
            if not isinstance(status, dict) or status.get("armed") is not False:
                raise RuntimeError("Disarm the physical WROOM before positioning checkerboard")
            # HttpHead(strict_capture=True) rejects reused camera sequence IDs.
            jpeg = await asyncio.wait_for(head.snapshot(), timeout=4)
            if (not isinstance(jpeg, bytes) or not 100 <= len(jpeg) <= 512000
                    or not jpeg.startswith(b"\xff\xd8")
                    or not jpeg.endswith(b"\xff\xd9")):
                raise ValueError("Incomplete or oversized real camera JPEG")
            with Image.open(io.BytesIO(jpeg)) as image:
                if image.format != "JPEG":
                    raise ValueError("Expected original XIAO JPEG capture")
                frame_size = image.size
                image.verify()
            if size is not None and frame_size != size:
                raise ValueError("XIAO camera resolution changed during calibration")
            size = frame_size
            target = folder / f"{index+1:02d}.jpg"
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            saved.append(target)  # Also remove a partially written private JPEG.
            with os.fdopen(fd, "wb") as file:
                file.write(jpeg)
        success = True
        return {
            "images": len(saved), "image_width_px": size[0],
            "image_height_px": size[1], "private_directory": str(folder),
            "checkerboard_poses_verified": False,
            "calibration_approved": False, "motor_authorized": False,
            "charging_authorized": False,
        }
    finally:
        # A partial set has unknown independent placement/calibration value.
        # Never leave private partial image records after failure or cancel.
        if not success:
            for target in saved:
                target.unlink(missing_ok=True)
            folder.rmdir()


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--robot", required=True)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--count", type=int, default=16)
    parser.add_argument("--consent-to-save-private-jpegs", action="store_true")
    args = parser.parse_args()
    if not args.consent_to_save_private_jpegs:
        parser.error("Explicit local camera image recording consent required")
    import httpx
    from desk_robot.config import load_settings
    from desk_robot.transport import HttpHead

    settings = load_settings(args.config)
    if settings.mode != "hardware" or not settings.voice_vision_tools_enabled:
        parser.error("Physical camera permission required in hardware config")
    robot = settings.robot(args.robot)

    async def wait_for_board(index: int) -> None:
        await asyncio.to_thread(
            input, f"Position measured board for view {index}/{args.count}; press Enter: "
        )

    async with httpx.AsyncClient() as client:
        result = await capture_checkerboards(
            HttpHead(robot, client, strict_capture=True), args.images,
            count=args.count, prompt=wait_for_board,
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
