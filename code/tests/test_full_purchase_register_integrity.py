"""Guard all 63 candidate purchase rows, not merely the 49 generated BOM roles.

These are structural evidence checks, not proof of an electrical part or a
released order. The extra rows describe physical subassemblies, alternatives,
or references to already counted shared station components. Never add their
quantities blindly to the robot/room totals.
"""
from pathlib import Path


HARDWARE = Path(__file__).resolve().parents[2] / "docs" / "hardware"
REGISTER = HARDWARE / "2026-11-16-five-pet-purchase-register.md"
PLAN = HARDWARE / "full-feature-plan.json"

# Exact headings and lineage are intentional: changing physical architecture
# or turning an alternative into a selected motor/charger needs a reviewed
# decision and code change, not a silent edit to a Markdown shopping table.
EXTRA = {
    "N20 100:1 MP 6V motors": (2, 10, "stepper", "alternative"),
    "DRV8833 dual H bridge": (1, 5, "stepper", "alternative"),
    "BQ24075 battery power path and BQ27441 gauge": (
        1, 5, "cap_power", "alternative"
    ),
    "5V switching regulator": (1, 5, "cap_power", "candidate"),
    "Protected NTC 1S battery pack": (1, 5, "cap_power", "required_subassembly"),
    "Independent 5V dock adapter": (
        1, 5, "dock_fixture", "required_subassembly"
    ),
    "Dock IR LED transistor/resistor driver channel": (
        2, 10, "dock_ir_emitter_channels", "required_subassembly"
    ),
    "Shared room controller": (1, 1, "room_controller", "already_counted"),
    "True room CO2 sensor": (1, 1, "scd40", "already_counted"),
    "Room gas/environment sensor": (1, 1, "bme688", "already_counted"),
    "Room presence radar": (1, 1, "ld2410c", "already_counted"),
    "Room thermal 8x8 array": (1, 1, "amg8833", "already_counted"),
    "Optional capacitive soil probe": (1, 1, "soil_probe", "already_counted"),
    "Optional NFC toy stickers": (10, 10, "nfc_game_props", "already_counted"),
}


def supplemental_rows():
    text = REGISTER.read_text(encoding="utf-8")
    header = "## Explicit drivetrain, 1S power path and one shared station add-ons"
    end = "## Price and source-first purchase overrides"
    assert text.count(header) == 1 and text.count(end) == 1
    section = text.split(header, 1)[1].split(end, 1)[0]
    rows = {}
    for line in section.splitlines():
        if not line.startswith("| "):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        assert len(cells) == 7, f"Malformed subassembly candidate row: {line}"
        if cells[0] in ("Item", "---"):
            continue
        if cells[0].startswith("---"):
            continue
        assert cells[0] not in rows, f"Duplicate subassembly: {cells[0]}"
        rows[cells[0]] = cells
    return rows


def test_every_supplemental_purchase_row_has_one_parent_and_quantity():
    import json

    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    rows = supplemental_rows()
    assert len(rows) == len(EXTRA) == 14
    assert set(rows) == set(EXTRA), "Unknown or forgotten supplementary purchase"
    pet = {part["id"]: part for part in plan["parts"]}
    room = {part["id"]: part for part in plan["room_pod"]["modules"]}
    assert len(pet) == 42 and len(room) == 7
    for name, (per, count, parent, disposition) in EXTRA.items():
        cells = rows[name]
        assert (int(cells[2]), int(cells[3])) == (per, count), name
        assert 0 <= int(cells[5]) <= count, name
        assert cells[1], f"Missing source/candidate for {name}"
        assert cells[6], f"Missing qualification note for {name}"
        if disposition == "already_counted":
            assert room[parent]["quantity_per_room"] == count, name
        else:
            assert parent in pet, name
            assert pet[parent]["per_robot"] > 0, name


def test_unselected_expensive_alternatives_are_not_silent_pilot_orders():
    rows = supplemental_rows()
    for name, (_, _, _, disposition) in EXTRA.items():
        if disposition in ("alternative", "candidate"):
            assert int(rows[name][5]) == 0, (
                f"Unselected motor, gauge, or regulator has pilot quantity: {name}"
            )


def test_supplemental_subassemblies_do_not_count_as_extra_robots():
    rows = supplemental_rows()
    assert len(rows) == 14
    for name, (_, count, _, disposition) in EXTRA.items():
        if disposition == "already_counted":
            assert count in (1, 10)
            assert "one station" not in name.casefold() or count == 1
    # A 5V dock adapter or LED driver is not itself a charger,
    # protected battery, or physical charge-completion receipt.
    for name in (
        "Independent 5V dock adapter",
        "Dock IR LED transistor/resistor driver channel",
        "Protected NTC 1S battery pack",
    ):
        assert "qualif" in rows[name][6].casefold() or (
            "unselected" in rows[name][1].casefold()
            or "verify" in rows[name][6].casefold()
            or "validated" in rows[name][6].casefold()
            or "order only" in rows[name][6].casefold()
            or "5 eventual" in rows[name][6].casefold()
            or "current and switching" in rows[name][6].casefold()
        )


def test_active_two_watt_speaker_register_and_wiring_are_one_fixed_selection():
    """Reject the exact mismatch recently introduced by parallel PR edits.

    This tests consistency of the CURRENT active selection, not a measured
    5V amplifier, speaker enclosure or any physical purchasing acceptance.
    """
    import json

    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    speaker = next(p for p in plan["parts"] if p["id"] == "speaker")
    amp = next(p for p in plan["parts"] if p["id"] == "amp")
    audio = plan["audio_output_power_contract"]
    assert "MAX98357A" in amp["name"]
    assert "CS20-02P110-04-1X" in speaker["name"]
    assert "8 ohm 2 watt" in speaker["name"]
    assert audio["amplifier_ic"] == "MAX98357A"
    assert audio["speaker_nominal_impedance_ohm"] == 8
    assert audio["speaker_nominal_rating_w"] == 2
    assert audio["amplifier_vdd_v"] == 5
    assert "HOLD" in audio["physical_release"]

    text = REGISTER.read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if line.startswith("| `speaker` |")]
    assert len(rows) == 1
    assert "CS20-02P110-04-1X" in rows[0]
    assert "2 watt" in rows[0]
    assert "HOLD" in rows[0] or "NOT RELEASED" in rows[0]
    assert "formerly proposed 1 W" not in speaker["name"]

    harness = (HARDWARE / "one-robot-signal-harness.generated.md").read_text()
    assert "Rated, isolated 5V audio power rail" in harness
    assert "8 ohm 2 W CS20-02P110-04-1X" in harness
    assert "NEVER connect either output to GND" in harness
    assert "speaker heat HOLD" not in harness or "heat HOLD" in harness
