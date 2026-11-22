"""Explicit XIAO checkerboard captures protect private media and physical safety."""
import importlib.util
import io
from pathlib import Path

import pytest
from PIL import Image


def capture_module():
    source = Path(__file__).resolve().parents[1] / "scripts/capture_dock_checkerboard.py"
    spec = importlib.util.spec_from_file_location("desk_dock_capture", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def capture_checkerboards(*args, **kwargs):
    return capture_module().capture_checkerboards(*args, **kwargs)


def jpeg(width=640, height=480, color=(100, 110, 120)):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_capture_private_original_jpeg_bytes_while_disarmed(tmp_path):
    originals = [jpeg(color=(60 + i * 12, 110, 120)) for i in range(12)]

    class Head:
        n = 0

        async def status(self):
            return {"armed": False}

        async def snapshot(self):
            self.n += 1
            return originals[self.n - 1]

    seen = []

    async def confirm(index):
        seen.append(index)

    folder = tmp_path / "new-private"
    result = await capture_checkerboards(Head(), folder, count=12, prompt=confirm)
    assert result["images"] == 12
    assert result["image_width_px"] == 640
    assert result["motor_authorized"] is False
    assert result["calibration_approved"] is False
    assert seen == list(range(1, 13))
    assert all((folder / f"{index:02}.jpg").read_bytes() == originals[index - 1]
               for index in range(1, 13))
    assert folder.stat().st_mode & 0o777 == 0o700
    assert all((folder / f"{index:02}.jpg").stat().st_mode & 0o777 == 0o600
               for index in range(1, 13))


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata_changed", [False, True])
async def test_repeated_checkerboard_pixels_abort_and_remove_private_media(
    tmp_path, metadata_changed,
):
    """Frame sequence and JPEG metadata cannot fake distinct board views."""
    original = jpeg()
    # Valid JPEG COM marker alters the bytes without changing RGB pixels.
    replay = (
        original[:2] + b"\xff\xfe\x00\x04ok" + original[2:]
        if metadata_changed else original
    )
    if metadata_changed:
        assert replay != original

    class Head:
        n = 0

        async def status(self):
            return {"armed": False}

        async def snapshot(self):
            self.n += 1
            return original if self.n == 1 else replay

    async def confirm(_index):
        pass

    folder = tmp_path / "private"
    with pytest.raises(ValueError, match="Duplicate checkerboard pixels"):
        await capture_checkerboards(Head(), folder, count=12, prompt=confirm)
    assert not folder.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["armed", "wrongmode", "badjpeg"])
async def test_capture_aborts_and_removes_partial_private_media(tmp_path, failure):
    data = jpeg()

    class Head:
        n = 0

        async def status(self):
            return {"armed": self.n >= 1 and failure == "armed"}

        async def snapshot(self):
            self.n += 1
            if self.n == 2 and failure == "wrongmode":
                return jpeg(320, 240)
            if self.n == 2 and failure == "badjpeg":
                return b"not a jpeg"
            return data

    async def confirm(_index):
        pass

    folder = tmp_path / "private"
    with pytest.raises((RuntimeError, ValueError)):
        await capture_checkerboards(Head(), folder, count=12, prompt=confirm)
    assert not folder.exists()


@pytest.mark.asyncio
async def test_existing_private_folder_is_never_overwritten(tmp_path):
    folder = tmp_path / "private"
    folder.mkdir()
    (folder / "01.jpg").write_bytes(b"original")

    async def prompt(_index):
        raise AssertionError("Should not prompt for preexisting folder")

    with pytest.raises(FileExistsError):
        await capture_checkerboards(object(), folder, count=12, prompt=prompt)
    assert (folder / "01.jpg").read_bytes() == b"original"


@pytest.mark.asyncio
async def test_disk_write_failure_cleans_partial_private_image(tmp_path, monkeypatch):
    """Private raw JPEG must be removed even when its write fails mid-frame."""
    import os

    module = capture_module()

    class FailedWrite:
        def __init__(self, fd):
            self.fd = fd

        def __enter__(self):
            return self

        def __exit__(self, *_):
            os.close(self.fd)

        def write(self, _blob):
            raise OSError("disk full")

    monkeypatch.setattr(
        module.os, "fdopen", lambda fd, *_args, **_kwargs: FailedWrite(fd)
    )

    class Head:
        async def status(self):
            return {"armed": False}

        async def snapshot(self):
            return jpeg()

    async def prompt(_):
        pass

    folder = tmp_path / "private"
    with pytest.raises(OSError, match="disk full"):
        await module.capture_checkerboards(
            Head(), folder, count=12, prompt=prompt
        )
    assert not folder.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("relative,nested", [(False, False), (False, True),
                                              (True, False)])
async def test_checkerboard_private_images_reject_symlink_ancestor(
    tmp_path, monkeypatch, relative, nested,
):
    external = tmp_path / "shared-destination"
    external.mkdir()
    linked = tmp_path / "redirect"
    linked.symlink_to(external, target_is_directory=True)
    if nested:
        (external / "nested").mkdir()
    if relative:
        monkeypatch.chdir(tmp_path)
        folder = Path("redirect") / "capture"
    else:
        folder = linked / "nested" / "capture" if nested else linked / "capture"

    async def no_prompt(_index):
        raise AssertionError("No physical capture before path check")

    with pytest.raises(ValueError, match="symlink ancestor"):
        await capture_checkerboards(object(), folder, count=12, prompt=no_prompt)
    assert not (external / "capture").exists()
    assert not (external / "nested" / "capture").exists()
