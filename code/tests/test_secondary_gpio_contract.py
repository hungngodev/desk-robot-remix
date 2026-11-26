"""Keep polled accessory control pins out of the WROOM GPIO allocation."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "emit_wiring_manifest", ROOT / "code/scripts/emit_wiring_manifest.py"
)
assert SPEC is not None and SPEC.loader is not None
manifest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manifest)

CONTROL_PINS = (
    ("CAP1188 ALERT (0x71 CH0)", "kCap1188AlertPin"),
    ("MAX30102 INT (0x71 CH0)", "kMax30102IntPin"),
    ("APDS9960 INT (0x71 CH1)", "kApds9960IntPin"),
    ("PN532 IRQ (0x71 CH5)", "kPn532IrqPin"),
    ("PN532 RESET (0x71 CH5)", "kPn532ResetPin"),
    ("MCP23017 INTA (0x71 CH5)", "kMcp23017IntAPin"),
    ("MCP23017 INTB (0x71 CH5)", "kMcp23017IntBPin"),
)


def test_polled_control_pins_are_explicit_in_rendered_harness():
    body = (ROOT / manifest.BODY_PINS).read_text()
    head = (ROOT / manifest.HEAD_PINS).read_text()
    plan = manifest.read_wiring_plan(ROOT / manifest.PLAN)
    rendered = manifest.render(plan, body, head)
    checked_in = (ROOT / "docs/hardware/one-robot-signal-harness.generated.md").read_text()
    for label, _ in CONTROL_PINS:
        prefix = f"| {label} | No WROOM GPIO |"
        assert rendered.count(prefix) == 1
        assert checked_in.count(prefix) == 1


@pytest.mark.parametrize("label,symbol", CONTROL_PINS)
@pytest.mark.parametrize("gpio", [13, 34, 36, 39])
def test_polled_control_pin_cannot_claim_a_gpio(label, symbol, gpio):
    body = (ROOT / manifest.BODY_PINS).read_text()
    plan = manifest.read_wiring_plan(ROOT / manifest.PLAN)
    declaration = f"constexpr int {symbol} = -1;"
    assert body.count(declaration) == 1
    changed = body.replace(declaration, f"constexpr int {symbol} = {gpio};")
    with pytest.raises(ValueError, match="Accessory control pin must remain unallocated"):
        manifest._verify_body_profiles(plan["bus"]["body_gpio"], changed)
