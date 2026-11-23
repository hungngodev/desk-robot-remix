"""Explicit operator-only XIAO checkerboard capture; no motion or background video.

Copies original authenticated JPEG bytes to a new private folder. Each image
requires a new operator confirmation and a disarmed WROOM status. The captured
images are private local media; review and delete them after calibration.
"""
from __future__ import annotations

import argparse
import asyncio
import errno
import hashlib
import io
import json
import os
from pathlib import Path
from typing import Awaitable, Callable

from PIL import Image


def _reject_private_output_symlink_ancestors(folder: Path) -> None:
    """Do not redirect operator-consented JPEGs through a linked parent."""
    # Path.absolute() preserves .. components. os.path.abspath() applies
    # normpath first and could hide `link/../` before link detection,
    # even though the filesystem traverses that symlink before `..`.
    absolute = folder.absolute()
    if any(parent.is_symlink() for parent in absolute.parents):
        raise ValueError("Private checkerboard output has a symlink ancestor")


def _open_new_private_folder(folder: Path) -> tuple[int, int]:
    """Anchor the capture folder to verified directories, not a mutable path."""
    absolute = folder.absolute()
    if ".." in absolute.parts:
        raise ValueError("Private checkerboard output may not traverse parent directories")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    parent_fd = os.open(absolute.anchor, flags)
    try:
        for component in absolute.parts[1:-1]:
            child_fd = os.open(component, flags, dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = child_fd
        # mkdir through the held parent cannot follow a substituted ancestor.
        os.mkdir(absolute.name, mode=0o700, dir_fd=parent_fd)
        try:
            capture_fd = os.open(absolute.name, flags, dir_fd=parent_fd)
        except BaseException:
            os.rmdir(absolute.name, dir_fd=parent_fd)
            raise
        return parent_fd, capture_fd
    except OSError as exc:
        os.close(parent_fd)
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise ValueError("Private checkerboard output has a symlink ancestor") from exc
        raise
    except BaseException:
        os.close(parent_fd)
        raise


def _same_inode(one: os.stat_result, two: os.stat_result) -> bool:
    return (one.st_dev, one.st_ino) == (two.st_dev, two.st_ino)


def _capture_path_still_original(folder: Path, capture_fd: int) -> bool:
    """A swapped alias must not be reported as the private capture location."""
    try:
        _reject_private_output_symlink_ancestors(folder)
        return _same_inode(
            os.stat(folder, follow_symlinks=False), os.fstat(capture_fd)
        )
    except (OSError, ValueError):
        return False


async def capture_checkerboards(
    head, folder: Path, *, count: int,
    prompt: Callable[[int], Awaitable[None]],
) -> dict:
    """One read-only fresh JPEG per confirmed board placement, all or nothing."""
    if type(count) is not int or not 12 <= count <= 40:
        raise ValueError("Require 12 to 40 distinct checkerboard captures")
    if not callable(prompt):
        raise ValueError("Explicit placement confirmation required")
    # A string precheck alone is insufficient after the first awaited prompt.
    _reject_private_output_symlink_ancestors(folder)
    # Do not merge sessions; pin both the parent and new folder descriptors.
    parent_fd, capture_fd = _open_new_private_folder(folder)
    saved: list[str] = []
    size = None
    seen_pixels = set()
    success = False
    try:
        for index in range(count):
            await prompt(index + 1)
            status = await asyncio.wait_for(head.status(), timeout=3)
            if not isinstance(status, dict) or status.get("armed") is not False:
                raise RuntimeError("Disarm the physical WROOM before positioning checkerboard")
            # HttpHead(strict_capture=True) rejects reused camera sequence IDs.
            jpeg = await asyncio.wait_for(head.snapshot(), timeout=4)
            # JPEG IO may take four seconds. Reject a calibration sample if
            # the independent WROOM armed or its status disappeared mid-read.
            after_capture = await asyncio.wait_for(head.status(), timeout=3)
            if (not isinstance(after_capture, dict)
                    or after_capture.get("armed") is not False):
                raise RuntimeError(
                    "WROOM armed or status lost during checkerboard capture"
                )
            if (not isinstance(jpeg, bytes) or not 100 <= len(jpeg) <= 512000
                    or not jpeg.startswith(b"\xff\xd8")
                    or not jpeg.endswith(b"\xff\xd9")):
                raise ValueError("Incomplete or oversized real camera JPEG")
            with Image.open(io.BytesIO(jpeg)) as image:
                if image.format != "JPEG":
                    raise ValueError("Expected original XIAO JPEG capture")
                frame_size = image.size
                image.verify()
            # A fresh stream sequence and operator prompt do not prove a
            # different checkerboard image: a stuck camera can replay the
            # same pixels with different JPEG metadata or encoded bytes.
            with Image.open(io.BytesIO(jpeg)) as decoded:
                pixel_hash = hashlib.sha256(decoded.convert("RGB").tobytes()).digest()
            if pixel_hash in seen_pixels:
                raise ValueError("Duplicate checkerboard pixels; reposition board and retry")
            seen_pixels.add(pixel_hash)
            if size is not None and frame_size != size:
                raise ValueError("XIAO camera resolution changed during calibration")
            size = frame_size
            filename = f"{index+1:02d}.jpg"
            fd = os.open(
                filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600, dir_fd=capture_fd,
            )
            saved.append(filename)  # Also remove a partially written private JPEG.
            with os.fdopen(fd, "wb") as file:
                file.write(jpeg)
        if not _capture_path_still_original(folder, capture_fd):
            raise ValueError("Private checkerboard folder changed during capture")
        success = True
        return {
            "images": len(saved), "image_width_px": size[0],
            "image_height_px": size[1], "private_directory": str(folder),
            "checkerboard_poses_verified": False,
            "calibration_approved": False, "motor_authorized": False,
            "charging_authorized": False,
        }
    finally:
        # The held directory FD keeps cleanup on the original private inode
        # even if a parent is renamed or replaced during an operator prompt.
        try:
            if not success:
                for filename in saved:
                    try:
                        os.unlink(filename, dir_fd=capture_fd)
                    except FileNotFoundError:
                        pass
                try:
                    entry = os.stat(
                        folder.name, dir_fd=parent_fd, follow_symlinks=False
                    )
                    if _same_inode(entry, os.fstat(capture_fd)):
                        os.rmdir(folder.name, dir_fd=parent_fd)
                except FileNotFoundError:
                    pass
        finally:
            os.close(capture_fd)
            os.close(parent_fd)


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

    # Device bearer traffic must bypass ambient HTTP(S)/ALL_PROXY settings.
    async with httpx.AsyncClient(trust_env=False) as client:
        result = await capture_checkerboards(
            HttpHead(robot, client, strict_capture=True), args.images,
            count=args.count, prompt=wait_for_board,
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
