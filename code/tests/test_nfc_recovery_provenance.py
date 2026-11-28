"""Guard PN532 presentation provenance across a recoverable transport fault.

The optional PN532 is a toy input, never user authentication or motor authority.
These host checks do not qualify the installed antenna or RF behavior.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ACCESSORIES = ROOT / "code/firmware/body/lib/AccessorySensors"


def test_nfc_transport_failure_preserves_confirmed_presentation(tmp_path):
    """A failed ACK must not manufacture a second physical tag arrival."""
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("C++17 compiler unavailable for PN532 host regression")
    source = tmp_path / "nfc_recovery.cc"
    binary = tmp_path / "nfc_recovery"
    source.write_text(
        r'''#include <cstdint>
#include "AccessoryReadings.h"

int main() {
  desk_robot::NfcRaw sample{};
  constexpr std::uint32_t a = 0x12345678U;
  constexpr std::uint32_t b = 0xFEDCBA98U;
  sample.completed_scan(true, a, 4, 100);
  if (!sample.valid || !sample.tag_visible || sample.tag_token != a ||
      sample.tag_events != 1 || sample.scan_seq != 1) return 1;

  // PN532 rejects an ACK or transport read while A stays on the antenna.
  sample.transport_failed();
  if (sample.valid || sample.present || sample.tag_visible ||
      sample.tag_token != 0 || sample.uid_length != 0 || sample.tag_events != 1 ||
      sample.scan_seq != 1 || sample.at_ms != 100) return 2;
  sample.transport_failed();
  sample.completed_scan(true, a, 4, 200);
  if (!sample.valid || sample.tag_events != 1 ||
      sample.scan_seq != 2 || sample.at_ms != 200) return 3;

  // A different UID is genuinely new, even without an intervening absent scan.
  sample.transport_failed();
  sample.completed_scan(true, b, 7, 300);
  if (sample.tag_events != 2 || sample.tag_token != b ||
      sample.uid_length != 7 || sample.scan_seq != 3) return 4;

  // Only a complete valid Absent followed by Present(B) creates another edge.
  sample.completed_scan(false, 0, 0, 400);
  if (sample.tag_visible || sample.tag_token != 0 || sample.uid_length != 0 ||
      sample.tag_events != 2 || sample.scan_seq != 4) return 5;
  sample.completed_scan(true, b, 7, 500);
  if (sample.tag_events != 3 || sample.scan_seq != 5) return 6;

  // Wrap may not reuse zero, which is the unset sequence sentinel.
  sample.scan_seq = 0xffffffffU;
  sample.completed_scan(false, 0, 0, 600);
  if (sample.scan_seq != 1 || sample.tag_events != 3) return 7;
  return 0;
}
''',
        encoding="utf-8",
    )
    command = [
        compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
        "-I", str(ACCESSORIES), str(source), "-o", str(binary),
    ]
    built = subprocess.run(
        command, capture_output=True, text=True, check=False, timeout=30,
    )
    assert built.returncode == 0, (
        f"PN532 host fixture compile failed: {' '.join(command)}\n"
        f"{built.stdout}\n{built.stderr}"
    )
    ran = subprocess.run(
        [str(binary)], capture_output=True, text=True, check=False, timeout=5,
    )
    assert ran.returncode == 0, (
        f"PN532 edge invariant {ran.returncode} failed: {ran.stderr}"
    )


def test_nfc_runtime_uses_the_provenance_helper_after_bad_ack():
    """The poller must invalidate live evidence without inventing an arrival."""
    source = (ACCESSORIES / "AccessorySensors.cpp").read_text()
    poll = source.split("void AccessorySensors::nfc_poll(", 1)[1].split(
        "void AccessorySensors::", 1
    )[0]
    assert "tag.transport_failed();" in poll
    assert "ready != 1 || !pn532_ack(frame, 7)" in poll
    assert "if (ready != 1 ||" in poll
    assert "tag.completed_scan(result == Pn532TagResult::Present," in poll
    assert "tag.tag_visible = false;" not in poll
    assert "tag.tag_events =" not in poll
