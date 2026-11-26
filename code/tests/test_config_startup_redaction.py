import traceback

import pytest
from desk_robot.config import load_settings


@pytest.mark.parametrize(
    "suffix, diagnostic",
    [
        ('\n"synthetic-private-marker" = "synthetic-private-value"\n', "unknown field"),
        ('\nmotion_enabled = "synthetic-private-value"\n', "robots.0.motion_enabled"),
        ('\n["synthetic-private-marker"]\n["synthetic-private-marker"]\n', "invalid TOML"),
    ],
)
def test_rejected_config_diagnostic_is_safe(tmp_path, suffix, diagnostic):
    from desk_robot.config import ConfigurationError

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
