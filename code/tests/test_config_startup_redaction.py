import traceback
from pathlib import Path

import pytest
from desk_robot.config import ConfigurationError, load_settings


@pytest.mark.parametrize(
    "suffix, diagnostic",
    [
        ('\n"synthetic-private-marker" = "synthetic-private-value"\n', "unknown field"),
        ('\nmotion_enabled = "synthetic-private-value"\n', "robots.0.motion_enabled"),
        ('\n["synthetic-private-marker"]\n["synthetic-private-marker"]\n', "invalid TOML"),
    ],
)
def test_rejected_config_diagnostic_is_safe(tmp_path, suffix, diagnostic):
    path = tmp_path / "robots.toml"
    valid = 'mode = "simulation"\n[[robots]]\nid = "pip"\nname = "Pip"\ntoken_env = "HEAD_TOKEN"\n'
    path.write_text(valid + suffix)
    with pytest.raises(ConfigurationError, match=diagnostic) as caught:
        load_settings(path)
    error = caught.value
    rendered = "".join(traceback.format_exception(error))
    assert "synthetic-private" not in rendered
    assert error.__context__ is None
    assert error.__cause__ is None
    path.write_text(valid)
    assert load_settings(path).robots[0].motion_enabled is False


@pytest.mark.parametrize("failure", [FileNotFoundError, PermissionError, IsADirectoryError])
def test_config_open_error_is_safe(tmp_path, monkeypatch, failure):
    marker = "synthetic-private-path"
    path = tmp_path / marker

    def reject(*args, **kwargs):
        raise failure(13, "Cannot open", str(path))

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", reject)
        with pytest.raises(ConfigurationError, match="Cannot read configuration") as caught:
            load_settings(path)
    error = caught.value
    assert marker not in "".join(traceback.format_exception(error))
    assert error.__context__ is None
    assert error.__cause__ is None


@pytest.mark.parametrize(
    "field", ["config", "calibration", "dock_calibration", "vision_weights", "trials_file"],
)
@pytest.mark.parametrize("failure", [OSError, RuntimeError, ValueError])
def test_config_resolution_error_is_safe(tmp_path, monkeypatch, field, failure):
    marker = "synthetic-private-path"
    path = tmp_path / (marker if field == "config" else "robots.toml")
    valid = 'mode = "simulation"\n[[robots]]\nid = "pip"\nname = "Pip"\ntoken_env = "HEAD_TOKEN"\n'
    overrides = None
    if field in {"calibration", "dock_calibration"}:
        valid += f'{field} = "{marker}"\n'
    elif field != "config":
        overrides = {field: marker}
    path.write_text(valid)
    original = Path.resolve

    def reject(self, *args, **kwargs):
        if self.name == marker:
            raise failure(f"Cannot resolve {self}")
        return original(self, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "resolve", reject)
        with pytest.raises(ConfigurationError, match="Cannot resolve configuration path") as caught:
            load_settings(path, overrides=overrides)
    error = caught.value
    assert marker not in "".join(traceback.format_exception(error))
    assert error.__context__ is None
    assert error.__cause__ is None
