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
    "DRV8833 dual H bridge": (1, 5, "uln2003", "alternative"),
    "BQ24075 power-path source, NO second SoC gauge": (
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
    "Required shared-station capacitive soil probe": (1, 1, "soil_probe", "already_counted"),
    "Optional NFC toy stickers": (10, 10, "nfc_game_props", "already_counted"),
}


# The 14 human sourcing rows have distinct canonical JSON decisions. A
# component driver is not itself the motor, and duplicated parent inheritance
# must not let an agent declare a wrong combination "fully checked".
LINKED_IDS = {
    "N20 100:1 MP 6V motors": "n20_motor_candidate",
    "DRV8833 dual H bridge": "drv8833_driver_candidate",
    "BQ24075 power-path source, NO second SoC gauge": "bq24075_charger_candidate",
    "5V switching regulator": "boost_5v_candidate",
    "Protected NTC 1S battery pack": "protected_ntc_pack",
    "Independent 5V dock adapter": "dock_5v_adapter",
    "Dock IR LED transistor/resistor driver channel": "dock_ir_transistor_channels",
    "Shared room controller": "shared_room_controller",
    "True room CO2 sensor": "room_scd40",
    "Room gas/environment sensor": "room_bme688",
    "Room presence radar": "room_ld2410c",
    "Room thermal 8x8 array": "room_amg8833",
    "Required shared-station capacitive soil probe": "room_soil_probe",
    "Optional NFC toy stickers": "room_nfc_game_tokens",
}


def supplemental_rows():
    text = REGISTER.read_text(encoding="utf-8")
    header = "## Explicit drivetrain, 1S power path and one shared station add-ons"
    end = "## Price and source-first purchase overrides"
    assert text.count(header) == 1 and text.count(end) == 1
    section = text.split(header, 1)[1].split(end, 1)[0]
    # An adjacent source ownership table is documentation, not another
    # seven-column purchasing table. Parse only the first purchase section.
    section = section.split("## Actual source owner for every linked assembly detail", 1)[0]
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


def _validate_purchase_role_audit(audit_text: str, audit_dir: Path) -> None:
    import json
    import re

    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    expected_pet = {part["id"] for part in plan["parts"]}
    expected_room = {part["id"] for part in plan["room_pod"]["modules"]}
    assert len(expected_pet) == 42 and len(expected_room) == 7
    rows = [line for line in audit_text.splitlines()
            if line.startswith(("| Pet or dock |", "| Shared station |"))]
    assert len(rows) == 49
    actual_pet = set()
    actual_room = set()
    real_files = set()
    role_links: dict[str, list[str]] = {}
    root = HARDWARE.parents[1].resolve()
    for row in rows:
        cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
        assert len(cells) >= 6, f"Malformed integration row: {row}"
        role = cells[1].replace(chr(96), "")
        seen = actual_room if cells[0] == "Shared station" else actual_pet
        assert role not in seen, f"Duplicated physical role: {role}"
        seen.add(role)
        links = [
            target for target in re.findall(r"\[[^]]+\]\(([^)#]+)(?:#[^)]+)?\)", cells[3])
            if not target.startswith(("http://", "https://"))
        ]
        assert links, f"Unreferenced physical role: {role}"
        role_links[role] = links
        for reference in links:
            source = (audit_dir / reference).resolve()
            assert source.is_relative_to(root), f"Escaped repository root: {role}"
            assert source.is_file(), f"Missing real source path for {role}: {reference}"
            real_files.add(source)
        assert cells[4], f"No honest implementation status for {role}"
        assert cells[5], f"No qualification blocker for {role}"
    assert "haptic-one-shot-wiring.md" in role_links["haptic_motor"]
    assert actual_pet == expected_pet
    assert actual_room == expected_room
    assert len(real_files) >= 22


def test_all_63_purchase_roles_link_real_current_source_files():
    """Source coverage for 49 primary and 14 linked purchase roles, not HW signoff."""
    audit = HARDWARE / "2026-11-16-complete-63-row-integration-audit.md"
    _validate_purchase_role_audit(audit.read_text(encoding="utf-8"), audit.parent)
    assert len(supplemental_rows()) == 14


def test_purchase_role_audit_rejects_broken_or_missing_same_dir_wiring_links():
    import pytest

    audit = HARDWARE / "2026-11-16-complete-63-row-integration-audit.md"
    text = audit.read_text(encoding="utf-8")
    with pytest.raises(AssertionError):
        _validate_purchase_role_audit(
            text.replace("haptic-one-shot-wiring.md", "missing-wiring.md"),
            audit.parent,
        )
    with pytest.raises(AssertionError):
        _validate_purchase_role_audit(
            text.replace(", [lab wiring](haptic-one-shot-wiring.md)", ""),
            audit.parent,
        )


def test_every_supplemental_purchase_row_has_one_parent_and_quantity():
    import json

    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    rows = supplemental_rows()
    assert len(rows) == len(EXTRA) == len(LINKED_IDS) == 14
    assert set(rows) == set(EXTRA) == set(LINKED_IDS), (
        "Unknown or forgotten supplementary purchase")
    linked = {entry["id"]: entry for entry in plan["linked_subassemblies"]}
    assert set(linked) == set(LINKED_IDS.values())
    pet = {part["id"]: part for part in plan["parts"]}
    room = {part["id"]: part for part in plan["room_pod"]["modules"]}
    assert len(pet) == 42 and len(room) == 7
    for name, (per, count, parent, disposition) in EXTRA.items():
        cells = rows[name]
        if name == "Room thermal 8x8 array":
            assert cells[2:4] == ["1 if later selected", "1 visible option"]
            assert cells[5] == "0"
            assert "CONDITIONAL OPTIONAL, NOT SELECTED" in cells[6]
        else:
            assert (int(cells[2]), int(cells[3])) == (per, count), name
        assert 0 <= int(cells[5]) <= count, name
        detail = linked[LINKED_IDS[name]]
        assert detail["parent_role"] == parent, (
            name, parent, detail["parent_role"])
        assert detail["fleet_quantity"] == count, name
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
    assert "real carrier/rectangular baffle heat HOLD" in harness


def test_instructional_buy_wire_and_print_docs_do_not_name_retired_speaker():
    """The 63-entry cart and active assembly instructions are one design."""
    root = HARDWARE.parents[1]
    buying = (HARDWARE / "parts.md").read_text(encoding="utf-8")
    wiring = (HARDWARE / "wiring.md").read_text(encoding="utf-8")
    fusion = (root / "docs/cad/FUSION_ONE_ROBOT_ASSEMBLY.md").read_text(
        encoding="utf-8")
    adapter = (root / "docs/cad/remixes/one_robot_adapter_kit.scad").read_text(
        encoding="utf-8")
    for source in (buying, wiring, fusion, adapter):
        assert "CS20-02P110-04-1X" in source
    assert "20mm8ohm1W is the existing candidate" not in buying
    assert "set volume for the 8 Ω / 1 W speaker" not in wiring
    assert "speaker diameter/depth" not in fusion
    assert "speaker_od=20;" not in adapter


def test_source_ownership_has_exact_unique_roles_and_in_tree_paths():
    """Reject duplicate JSON keys, missing role owners and out-of-tree paths."""
    import json

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            assert key not in result, f"Duplicate JSON key: {key}"
            result[key] = value
        return result

    plan = json.loads(PLAN.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
    owners = json.loads(
        (HARDWARE / "full-63-role-source-ownership.json").read_text(encoding="utf-8"),
        object_pairs_hook=unique_pairs,
    )
    groups = {
        "pet_roles": [item["id"] for item in plan["parts"]],
        "room_roles": [item["id"] for item in plan["room_pod"]["modules"]],
        "linked_roles": [item["id"] for item in plan["linked_subassemblies"]],
    }
    root = HARDWARE.parents[1].resolve()
    all_ids = []
    for group, ids in groups.items():
        assert len(ids) == len(set(ids))
        assert set(owners[group]) == set(ids)
        all_ids.extend(ids)
        for owner in owners[group].values():
            for key in ("source", "host_test"):
                path = root / owner[key]
                assert path.resolve().is_relative_to(root)
                assert path.is_file()
    assert len(all_ids) == len(set(all_ids)) == 63


_EXPECTED_PILOT_ROWS = {
    "cliff_obstacle": (
        "SEN-19-006", 1, "https://electropeak.com/gy-530-vl53l0x-laser-range-finder",
    ),
    "i2c_mux": (
        "COM-05-067", 2,
        "https://electropeak.com/tca9548a-1-to-8-i2c-8-way-multi-channel-expansion-board",
    ),
    "cap1188": ("SEN-25-020", 1, "https://electropeak.com/cap1188-capacitive-touch-module"),
    "apds9960": (
        "SEN-24-027", 1, "https://electropeak.com/apds-9960-infrared-gesture-sensor-module",
    ),
    "ads1115": (
        "COM-05-045", 1,
        "https://electropeak.com/ads1115-16-bit-adc-4-channel-programmable-gain-amplifier-b00soy52cu",
    ),
    "mcp23017": (
        "COM-05-093", 1,
        "https://electropeak.com/mcp23017-e-ss-16-channel-i-o-expansion-module-i2c-interface",
    ),
    "amp": ("DFR0954", 1, "https://www.dfrobot.com/product-2614.html"),
    "bumper": (
        "D2F-01L3", 2,
        "https://www.newark.com/aratas/d2f-01l3/microswitch-d2f-01l3/dp/45Y5018",
    ),
    "speaker": (
        "CS20-02P110-04-1X", 1,
        "https://www.digikey.com/en/products/detail/"
        "challenge-electronics/CS20-02P110-04-1X/30407069",
    ),
    "sensor_3v3": ("2873", 1, "https://www.pololu.com/product/2873"),
    "rgb": (
        "BOB-13282", 1, "https://www.sparkfun.com/sparkfun-rgb-led-breakout-ws2812b.html",
    ),
    "dock_ir_receivers": (
        "TSOP38438", 2,
        "https://www.digikey.com/en/products/detail/"
        "vishay-semiconductor-opto-division/TSOP38438/4073478",
    ),
    "dock_ir_emitter_channels": (
        "TSAL6200", 2,
        "https://www.digikey.com/en/products/detail/"
        "vishay-semiconductor-opto-division/TSAL6200/1681339",
    ),
}


def _assert_pilot_cart_markdown(markdown: str, expected_by_sku: dict[str, tuple[int, str]]) -> None:
    header = (
        "| Candidate checkout seller | Brand or manufacturer | SKU | Part "
        "| Qty | Historical USD each | Link | Engineering source | Supplier status |"
    )
    lines = markdown.splitlines()
    starts = [i for i, line in enumerate(lines) if line == header]
    assert len(starts) == 1, "Missing or duplicate pilot table header"
    rows: dict[str, tuple[int, str]] = {}
    for line in lines[starts[0] + 2:]:
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        assert len(cells) == 9, line
        sku = cells[2]
        assert sku not in rows, f"Duplicate pilot row for SKU {sku}"
        rows[sku] = (int(cells[4]), cells[6])
    assert rows == expected_by_sku


def test_first_unit_shopping_scopes_and_pilot_source_links():
    """Keep historical sample references distinct from complete build quantities."""
    import ast
    import json
    import sys

    import pytest

    root = HARDWARE.parents[1]
    scripts_dir = str(root / "code/scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from procurement_release import generate, render_pilot_supplier_cart

    checklist = (root / "docs/plans/first-unit-shopping-agent-checklist.md").read_text(
        encoding="utf-8"
    )
    register = REGISTER.read_text(encoding="utf-8")
    for doc in (checklist, register):
        assert 'costs.scope = "evaluation"' in doc
        assert "exactly one GY-530 and one mux" in doc
        assert "one GY-530 and two muxes" in doc
        assert "eight GY-530 and two muxes" in doc
        assert "--format pilot-cart-markdown" in doc
        assert "--format first-robot-markdown" in doc
        assert "not additive carts" in doc
        assert "strict physical release remains HOLD" in doc
    assert register.count("| Legacy fit target |") == 2
    assert "| Pilot |" not in register
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    parts = {part["id"]: part for part in plan["parts"]}
    source = (root / "code/scripts/procurement_release.py").read_text(encoding="utf-8")
    assignments = [
        node.value for node in ast.parse(source).body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "PILOT_SAMPLE_PRODUCTS"
                for target in node.targets)
    ]
    assert len(assignments) == 1
    pilot = ast.literal_eval(assignments[0])
    assert set(pilot) == set(_EXPECTED_PILOT_ROWS)
    for role, (exp_sku, exp_qty, exp_url) in _EXPECTED_PILOT_ROWS.items():
        assert (pilot[role][2], pilot[role][4], pilot[role][3]) == (exp_sku, exp_qty, exp_url), role
    for role, full_qty, sample_qty in (("cliff_obstacle", 8, 1), ("i2c_mux", 2, 2)):
        assert parts[role]["per_robot"] == full_qty
        assert pilot[role][4] == sample_qty
    for role in ("cliff_obstacle", "i2c_mux", "amp", "speaker", "dock_ir_receivers"):
        assert pilot[role][3] in checklist, role
        assert pilot[role][3] in register, role

    expected_by_sku = {sku: (qty, url) for sku, qty, url in _EXPECTED_PILOT_ROWS.values()}
    markdown = render_pilot_supplier_cart(generate(plan, {}))
    _assert_pilot_cart_markdown(markdown, expected_by_sku)

    lines = markdown.splitlines()
    mux_row = next(line for line in lines if "| COM-05-067 |" in line)
    mux_cells = [cell.strip() for cell in mux_row.strip("|").split("|")]
    bad_qty = mux_cells.copy()
    bad_qty[4] = "1"
    with pytest.raises(AssertionError):
        _assert_pilot_cart_markdown(
            markdown.replace(mux_row, "| " + " | ".join(bad_qty) + " |", 1), expected_by_sku,
        )
    bad_url = mux_cells.copy()
    bad_url[6] = "https://example.invalid/wrong"
    with pytest.raises(AssertionError):
        _assert_pilot_cart_markdown(
            markdown.replace(mux_row, "| " + " | ".join(bad_url) + " |", 1), expected_by_sku,
        )
    amp_row = next(line for line in lines if "| DFR0954 |" in line)
    with pytest.raises(AssertionError):
        _assert_pilot_cart_markdown(
            markdown.replace(amp_row, amp_row + "\n" + amp_row, 1), expected_by_sku,
        )
    with pytest.raises(AssertionError):
        _assert_pilot_cart_markdown(
            markdown.replace("| Candidate checkout seller |", "| Wrong header |", 1),
            expected_by_sku,
        )


def test_audit_supplemental_lineage_matches_current_register_contract():
    """The audit must cover all linked roles without reviving retired selections."""
    audit = HARDWARE / "2026-11-16-complete-63-row-integration-audit.md"
    text = audit.read_text(encoding="utf-8")
    section = text.split("## Additional fourteen rows, without duplicate buying", 1)[1]
    section = section.split("## ", 1)[0]
    rows = {}
    for line in section.splitlines():
        if not line.startswith("| ") or line.startswith(("| ---", "| Supplementary")):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        assert len(cells) == 6, line
        assert cells[0] not in rows, cells[0]
        rows[cells[0]] = cells
    assert set(rows) == set(EXTRA)
    register_rows = supplemental_rows()
    for name, (_, count, parent, _) in EXTRA.items():
        assert int(rows[name][1]) == count, name
        assert rows[name][2] == f"`{parent}`", name
        assert int(rows[name][4]) == int(register_rows[name][5]), name
    assert "BQ27441 excluded" in rows["BQ24075 power-path source, NO second SoC gauge"][5]
    assert "Required role" in rows["Required shared-station capacitive soil probe"][5]
    assert "not selected" in rows["Room thermal 8x8 array"][3]
    assert "require measured pilot validation" in rows[
        "Dock IR LED transistor/resistor driver channel"
    ][5]
