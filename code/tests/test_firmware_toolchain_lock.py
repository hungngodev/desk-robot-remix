"""Guard the exact framework and compiler pins inherited by PlatformIO profiles."""

import configparser
import json
import re
from pathlib import Path

import pytest

_STACKS = {
    "body": ("espressif32", {
        "platformio/framework-arduinoespressif32", "espressif/toolchain-xtensa-esp32",
    }),
    "dock": ("atmelavr", {
        "platformio/framework-arduino-avr", "platformio/toolchain-atmelavr",
    }),
    "room_station": ("nordicnrf52", {
        "platformio/framework-arduinoadafruitnrf52", "platformio/framework-cmsis",
        "platformio/toolchain-gccarmnoneeabi",
    }),
}
_EXACT = re.compile(r"\d+\.\d+\.\d+(?:\+[A-Za-z0-9.-]+)?")


def _assert_locked(source, lock, platform, required):
    config = configparser.ConfigParser(interpolation=None)
    config.read_string(source)
    assert not config.defaults()
    assert not config.has_option("platformio", "extra_configs")
    assert _EXACT.fullmatch(lock[platform])
    common = config["env"]
    assert common["platform"] == f"{platform}@{lock[platform]}"
    assert common["framework"] == "arduino"
    packages = lock["platform_packages"]
    assert required <= packages.keys()
    assert all(_EXACT.fullmatch(version) for version in packages.values())
    actual = [line.strip() for line in common["platform_packages"].splitlines() if line.strip()]
    assert sorted(actual) == sorted(f"{name} @ {version}" for name, version in packages.items())
    profiles = {section for section in config.sections() if section.startswith("env:")}
    assert profiles
    for section in profiles:
        options = config[section]
        assert not {"platform", "framework", "platform_packages"} & options.keys(), section
        parents = options.get("extends", "").replace(",", " ").split()
        assert set(parents) <= profiles, section


@pytest.mark.parametrize("stack", _STACKS)
def test_firmware_profiles_inherit_exact_toolchain_lock(stack):
    code = Path(__file__).resolve().parents[1]
    lock = json.loads((code / "toolchain-lock.json").read_text())
    platform, required = _STACKS[stack]
    source = (code / "firmware" / stack / "platformio.ini").read_text()
    _assert_locked(source, lock[stack], platform, required)


@pytest.mark.parametrize("fault", ["range", "missing", "override", "external", "mismatch"])
def test_toolchain_lock_rejects_drift(fault):
    platform = "espressif32"
    package = "platformio/framework-arduinoespressif32"
    lock = {platform: "6.9.0", "platform_packages": {package: "3.20017.241212+sha.dcc1105b"}}
    version = lock["platform_packages"][package]
    source = (
        f"[platformio]\n[env]\nplatform = {platform}@6.9.0\nframework = arduino\n"
        f"platform_packages =\n  {package} @ {version}\n[env:base]\n[env:lab]\n"
        "extends = env:base\n"
    )
    _assert_locked(source, lock, platform, {package})
    if fault == "range":
        lock["platform_packages"][package] = "~3.20017.0"
        source = source.replace(version, "~3.20017.0")
    elif fault == "missing":
        del lock["platform_packages"][package]
        source = source.replace(f"  {package} @ {version}\n", "")
    elif fault == "override":
        source += f"platform_packages = {package} @ 3.20017.0\n"
    elif fault == "external":
        source = source.replace("[platformio]\n", "[platformio]\nextra_configs = extra.ini\n")
    elif fault == "mismatch":
        source = source.replace(version, "3.20017.0")
    with pytest.raises(AssertionError):
        _assert_locked(source, lock, platform, {package})
