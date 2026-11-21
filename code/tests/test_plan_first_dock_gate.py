"""Docking is a first robot release gate, not an optional fleet expansion."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "docs/PLAN.md"


def _stages(markdown):
    lines = markdown.splitlines()
    table = [line for line in lines if line.startswith("| ") and " | " in line]
    return {
        int(line.split("|")[1].strip().split(".")[0]): line.casefold()
        for line in table
        if line.split("|")[1].strip().split(".")[0].isdigit()
    }


def test_first_robot_plan_requires_dock_before_qualification():
    stages = _stages(PLAN.read_text())
    assert len(stages) >= 13
    assert "first dock" in stages[2]
    assert "protected 1s charging" in stages[2]
    assert "eight-sensor vl53l0x" in stages[3]
    assert "supervised terminal dock approach" in stages[8]
    assert "first dock" in stages[9]
    for phrase in ("measured net cell current", "departure", "recovery"):
        assert phrase in stages[9]
    assert "five" in stages[10] and "docks" in stages[10]
    assert "five independently qualified docks" in stages[11]
    assert "one approved shared station" in stages[11]
    assert "already mandatory" in stages[12]


def test_optional_research_row_cannot_qualify_or_defer_required_dock():
    rows = _stages(PLAN.read_text())
    assert "alternate experimental docking methods" in rows[12]
    assert "advanced games/docking/navigation" not in rows[12]
    assert "first assigned dock" in rows[9]
    fake = PLAN.read_text().replace(
        "alternate experimental docking methods", "advanced games/docking/navigation",
    )
    assert "advanced games/docking/navigation" in _stages(fake)[12]
    assert "advanced games/docking/navigation" not in rows[12]


def test_cad_register_rejects_obsolete_power_bank_assembly_instructions():
    cad = (ROOT / "docs/cad/README.md").read_text(encoding="utf-8")
    circuit = (ROOT / "docs/hardware/"
               "2026-11-17-one-pet-protected-power-circuit.md").read_text(
                   encoding="utf-8",
               )
    assert "protected 1S power circuit" in cad
    assert "BQ24075" in cad and "regulated 5V" in cad
    assert "3.3V sensor" in cad and "NOT qualified for purchase" in cad
    assert "protected single-cell pack" in circuit
    assert "BQ24075" in circuit and "NOT A FABRICATED OR TESTED PCB" in circuit
    for obsolete in ("bank-based plan", "physical bank size", "WROOM/bank"):
        assert obsolete not in cad


def test_builder_plan_consistently_selects_mpu6050_with_berryimu_as_spare():
    plan_text = PLAN.read_text(encoding="utf-8")
    feature_plan_json = (ROOT / "docs/hardware/full-feature-plan.json").read_text(encoding="utf-8")
    parts_md = (ROOT / "docs/hardware/parts.md").read_text(encoding="utf-8")

    # 1. Feature plan JSON freezes MPU6050 GY521 with BerryIMU as spare
    assert '"id": "imu"' in feature_plan_json
    assert "MPU6050 GY521 compatible six axis breakout" in feature_plan_json
    assert "BerryIMU preserved as spare" in feature_plan_json

    # 2. parts.md confirms supersession
    assert "MPU6050" in parts_md
    assert "BerryIMU first choice references later in this document are superseded" in parts_md

    # 3. PLAN.md Stage 7 qualifies MPU6050, notes BerryIMU superseded
    assert "qualified MPU6050 (GY521 compatible WHO_AM_I 0x68 on 3.3V WROOM path; BerryIMU superseded and retained only as spare)" in plan_text

    # 4. PLAN.md Stage 2 schematic requires MPU6050
    assert "MPU6050, servos, motors, touch, and the separate 0x71 accessory mux" in plan_text

    # 5. PLAN.md Stage 4 summary table notes supersession
    assert "verify MPU6050 GY521 (BerryIMU superseded / retained as spare)" in plan_text

    # 6. No unannotated "version-confirmed BerryIMU handling/tilt/shake" remains
    assert "version-confirmed BerryIMU handling/tilt/shake" not in plan_text

    # 7. The linked assembly/interaction guide must match the selected IMU.
    guide = (ROOT / "docs/hardware/interaction-sensors.md").read_text(
        encoding="utf-8",
    )
    body = (ROOT / "code/firmware/body/src/main.cpp").read_text(
        encoding="utf-8",
    )
    assert "MPU6050 GY521 compatible six axis breakout" in feature_plan_json
    assert "**Selected first robot and fleet IMU**" in guide
    assert "BerryIMU remains an optional spare" in guide
    assert "BerryImu::decode_mpu6050" in guide
    assert "local software attitude guard" in guide
    assert "physical_qualification_pass=false" in guide
    assert "require_imu_attitude_guard(true)" in body
    for outdated in (
        "not the new five-unit baseline",
        "identify the owned BerryIMU version first",
        "requires an identified fresh BerryIMU",
        "does not read actual acceleration/gyro data",
        "No calibrated safety reaction is enabled",
    ):
        assert outdated not in guide


def test_product_acceptance_requires_first_dock_charge_not_expansion():
    """Do not silently defer the actual first robot's mandatory own dock."""
    product = (ROOT / "docs/product-definition.md").read_text(encoding="utf-8")
    acceptance = product.split("## Acceptance before duplication", 1)[1].split(
        "## What the eventual print-and-assemble package must contain", 1
    )[0]
    a6 = next(
        row.casefold() for row in acceptance.splitlines()
        if row.startswith("| A6 Power/mechanics |")
    )
    for required in (
        "its own dock",
        "safe approach",
        "seated alignment",
        "normally unpowered contacts",
        "measured net pack charge",
        "temperature",
        "safe departure",
    ):
        assert required in a6
    exclusion = acceptance.split("Initial success excludes", 1)[1].casefold()
    assert "automatic charging" not in exclusion.split(
        "**autonomous docking", 1
    )[0]
    for required in (
        "autonomous docking and protected automatic charging",
        "physical hold",
        "software simulation or a passing ci run cannot satisfy a6",
    ):
        assert required in acceptance.casefold()
    # The original acceptance IDs remain present and separate.
    for number in range(1, 13):
        assert f"| A{number} " in acceptance
