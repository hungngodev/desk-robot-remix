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
async def test_arming_during_snapshot_discards_all_private_calibration_frames(
    tmp_path,
):
    """Source disarm must still hold after a slow camera snapshot."""

    class Head:
        captured = 0
        checks = 0

        async def status(self):
            self.checks += 1
            # Pre and post checks for each JPEG. Motion begins while
            # snapshot number two is pending, after one frame was saved.
            return {"armed": self.captured >= 2 and self.checks % 2 == 0}

        async def snapshot(self):
            self.captured += 1
            return jpeg(color=(70 + self.captured * 10, 90, 110))

    async def confirm(_index):
        pass

    head = Head()
    folder = tmp_path / "private"
    with pytest.raises(RuntimeError, match="during checkerboard capture"):
        await capture_checkerboards(head, folder, count=12, prompt=confirm)
    assert head.captured == 2
    assert head.checks == 4
    # A failed session cannot leave an earlier successful JPEG behind as
    # misleading calibration input.
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


@pytest.mark.asyncio
@pytest.mark.parametrize("relative", [False, True])
async def test_checkerboard_private_images_reject_symlink_parent_dotdot(
    tmp_path, monkeypatch, relative,
):
    external = tmp_path / "shared-destination"
    nested = external / "nested"
    nested.mkdir(parents=True)
    linked = tmp_path / "redirect"
    linked.symlink_to(nested, target_is_directory=True)
    if relative:
        monkeypatch.chdir(tmp_path)
        folder = Path("redirect") / ".." / "private-capture"
    else:
        folder = linked / ".." / "private-capture"

    async def no_prompt(_index):
        raise AssertionError("No physical capture before path check")

    # The filesystem follows redirect to external/nested before applying ..,
    # but os.path.abspath would hide redirect during the privacy preflight.
    with pytest.raises(ValueError, match="symlink ancestor"):
        await capture_checkerboards(object(), folder, count=12, prompt=no_prompt)
    assert not (external / "private-capture").exists()


@pytest.mark.asyncio
async def test_parent_swap_during_prompt_cannot_redirect_private_jpegs(tmp_path):
    """The actual operator wait is a path substitution boundary."""
    trusted_parent = tmp_path / "trusted"
    trusted_parent.mkdir()
    relocated = tmp_path / "moved"
    untrusted = tmp_path / "shared"
    untrusted.mkdir()
    (untrusted / "capture").mkdir()
    folder = trusted_parent / "capture"
    originals = [jpeg(color=(50 + i * 10, 90, 130)) for i in range(12)]

    class Head:
        next_image = 0

        async def status(self):
            return {"armed": False}

        async def snapshot(self):
            image = originals[self.next_image]
            self.next_image += 1
            return image

    async def confirm(index):
        if index == 1:
            # An alias appears AFTER folder preflight, during the real prompt.
            trusted_parent.rename(relocated)
            trusted_parent.symlink_to(untrusted, target_is_directory=True)

    with pytest.raises(ValueError, match="changed during capture"):
        await capture_checkerboards(Head(), folder, count=12, prompt=confirm)
    assert not list((untrusted / "capture").glob("*.jpg"))
    assert not (relocated / "capture").exists()


@pytest.mark.asyncio
async def test_operator_cli_disables_ambient_proxy_for_device_bearer(
    tmp_path, monkeypatch, capsys,
):
    """The real operator CLI must not proxy private authenticated JPEG IO."""
    import httpx
    import sys
    from desk_robot import config, transport

    module = capture_module()
    monkeypatch.setenv("HTTPS_PROXY", "http://untrusted-proxy.invalid:8080")
    monkeypatch.setenv("ALL_PROXY", "http://untrusted-proxy.invalid:8080")
    monkeypatch.setattr(sys, "argv", [
        "capture_dock_checkerboard.py",
        "--config", str(tmp_path / "local.toml"),
        "--robot", "robot-01",
        "--images", str(tmp_path / "private-frames"),
        "--consent-to-save-private-jpegs",
    ])

    class Settings:
        mode = "hardware"
        voice_vision_tools_enabled = True

        def robot(self, robot_id):
            assert robot_id == "robot-01"
            return robot_id

    monkeypatch.setattr(config, "load_settings", lambda _path: Settings())
    clients = []

    class Client:
        def __init__(self, **kwargs):
            clients.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(httpx, "AsyncClient", Client)

    def head_factory(robot, client, *, strict_capture):
        assert robot == "robot-01"
        assert isinstance(client, Client)
        assert strict_capture is True
        return object()

    monkeypatch.setattr(transport, "HttpHead", head_factory)
    calls = []

    async def fake_capture(head, folder, *, count, prompt):
        calls.append((head, folder, count, callable(prompt)))
        return {"images": 0, "calibration_approved": False}

    monkeypatch.setattr(module, "capture_checkerboards", fake_capture)
    await module.main()

    assert len(clients) == 1
    assert clients[0].get("trust_env") is False
    assert len(calls) == 1
    assert calls[0][1] == tmp_path / "private-frames"
    assert calls[0][2:] == (16, True)
    assert '"calibration_approved": false' in capsys.readouterr().out
