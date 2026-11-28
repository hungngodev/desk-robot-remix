"""Keep standalone bench entry points outside every production body image."""

import configparser
from pathlib import Path

import pytest

CONFIG = Path(__file__).resolve().parents[1] / "firmware/body/platformio.ini"
BODY_FILTER = "-<*> +<main.cpp>"
BENCH_FILTERS = {
    "env:esp32_vl53l0x_bench": "-<*> +<vl53l0x_bench.cpp>",
    "env:esp32_servo_center_bench": "-<*> +<servo_center_bench.cpp>",
}


def load_config():
    config = configparser.ConfigParser(interpolation=None)
    assert config.read(CONFIG, encoding="utf-8")
    return config


def source_filter(config, section, seen=()):
    """Resolve the current single-parent PlatformIO profile convention."""
    assert section not in seen, f"cyclic profile inheritance: {section}"
    profile = config[section]
    if "build_src_filter" in profile:
        return " ".join(profile["build_src_filter"].split())
    parent = profile.get("extends", "env")
    assert parent in config, f"unsupported source filter inheritance: {parent}"
    return source_filter(config, parent, (*seen, section))


def check_isolation(config):
    assert config["platformio"]["default_envs"].strip() == "esp32_full"
    assert set(BENCH_FILTERS) <= set(config.sections())
    assert source_filter(config, "env") == BODY_FILTER
    for section in config.sections():
        if section.startswith("env:"):
            expected = BENCH_FILTERS.get(section, BODY_FILTER)
            assert source_filter(config, section) == expected, section


def test_every_body_profile_has_one_explicit_entry_point():
    check_isolation(load_config())


@pytest.mark.parametrize(
    "section,option,value",
    [
        ("env", "build_src_filter", "+<*> -<vl53l0x_bench.cpp> -<servo_center_bench.cpp>"),
        ("env:esp32_full", "build_src_filter", "+<*>"),
        ("env:esp32_full_interaction_lab", "extends", "env:esp32_vl53l0x_bench"),
        ("env:esp32_dc_full", "build_src_filter", "-<*> +<main.cpp> +<vl53l0x_bench.cpp>"),
        ("env:esp32_vl53l0x_bench", "build_src_filter", "-<*> +<main.cpp>"),
        ("env:esp32_servo_center_bench", "build_src_filter", "-<*> +<vl53l0x_bench.cpp>"),
        ("platformio", "default_envs", "esp32_vl53l0x_bench"),
    ],
)
def test_entry_point_leak_mutations_are_rejected(section, option, value):
    config = load_config()
    config[section][option] = value
    with pytest.raises(AssertionError):
        check_isolation(config)


def test_future_body_profile_cannot_inherit_a_bench_entry_point():
    config = load_config()
    config["env:future_body"] = {"extends": "env:esp32_vl53l0x_bench"}
    with pytest.raises(AssertionError, match="env:future_body"):
        check_isolation(config)
