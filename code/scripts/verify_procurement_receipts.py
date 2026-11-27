"""Live evidence check for the irreversible five-robot purchasing release.

The ordinary procurement projection is intentionally pure and accepts
synthetic receipts in its regression tests. The *actual* --require-release
command must additionally resolve every recorded gate receipt to an existing
immutable project record at the clean current source revision.

File existence is not evidence that a physical trial was honest. A human
reviewer must inspect raw measurements and the exact received PCB/pack before
ordering. No physical or charging authorization is inferred by this script.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import re
import subprocess
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError

import verify_playbook_receipts
from procurement_release import (
    CONDITIONAL_ROOM_PER_STATION,
    FIRST_ROBOT_ROOM_GATE,  # noqa: F401 (public verifier constant)
    FLEET_ONLY_SYSTEM_GATES,
    PART_GATES,
    SUPPLEMENTAL_DECISIONS,
    SYSTEM_GATES,
    conditional_station_decision_ids,
    first_robot_room_receipt_gate,
)
from verify_playbook_receipts import (
    REPO,
    bounded_receipt_int,
    evidence_digest_matches,
    finite_receipt_float,
    reject_nonfinite_receipt_value,
    source_unchanged_since_test,
    strict_receipt_object,
    verified_raw_record,
    verified_regular_record_path,
)
from verify_system import source_snapshot

ROOT = Path(__file__).resolve().parents[2]
SHA = re.compile(r"^[0-9a-f]{40}$")


# Keep the existing procurement API backed by the shared procedure verifier.
REQUIRED_PURCHASE_CI_JOBS = verify_playbook_receipts.REQUIRED_PURCHASE_CI_JOBS
verified_required_ci_jobs = verify_playbook_receipts.verified_required_ci_jobs


def checkout_sha(lookup=None) -> str:
    """Require a clean complete tree, not a sparse/truncated Git index.

    Share the canonical host verification's real worktree presence checks.
    A clean SHA and 400 index entries alone previously missed directories
    removed by sparse checkout or an accidental partial repository tree.
    """
    snapshot = source_snapshot()
    sha = snapshot.get("sha")
    if (not isinstance(sha, str) or not SHA.fullmatch(sha)
            or snapshot.get("tracked_clean") is not True
            or snapshot.get("root_tree_intact") is not True):
        raise ValueError("A clean exact commit and full repository tree are required for ordering")
    # Source authority is the existing PR branch. A clean main checkout,
    # stale fork or detached synthetic merge is not the purchase baseline.
    try:
        current_branch = subprocess.check_output(
            ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
            cwd=ROOT, text=True, timeout=10,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        current_branch = ""
    if current_branch != "impl/mac-hardware-safety-preflight-2026-11-10":
        raise ValueError("Purchasing requires the canonical PR #17 branch")
    # A local branch name does not prove that the checkout is the live
    # reviewed draft. Ordering from an old clean SHA could bypass newer
    # power, charger, BOM or CAD blockers introduced on PR #17.
    from verify_playbook_receipts import github_json
    live_lookup = github_json if lookup is None else lookup
    try:
        pr = live_lookup(
            "https://api.github.com/repos/"
            "hungngodev/desk-robot-remix/pulls/17"
        )
    except (HTTPError, URLError, ValueError, TimeoutError, OSError) as exc:
        raise ValueError("Cannot verify live PR #17 purchasing revision") from exc
    if not isinstance(pr, dict):
        raise ValueError("Invalid live PR #17 purchasing revision")
    head = pr.get("head")
    base = pr.get("base")
    head_repo = head.get("repo") if isinstance(head, dict) else None
    base_repo = base.get("repo") if isinstance(base, dict) else None
    if (type(pr.get("number")) is not int or pr["number"] != 17
            or pr.get("state") != "open" or pr.get("draft") is not True
            or not isinstance(head, dict)
            or head.get("sha") != sha
            or head.get("ref") != current_branch
            or not isinstance(head_repo, dict)
            or head_repo.get("full_name") != "hungngodev/desk-robot-remix"
            or not isinstance(base_repo, dict)
            or base_repo.get("full_name") != "hungngodev/desk-robot-remix"):
        raise ValueError("Local checkout does not match live draft PR #17 head")
    return sha


def required_receipts(evidence: dict, *, first_robot: bool = False,
                      deferred_optional_ids: frozenset[str] = frozenset()):
    """Scope each receipt to its specific purchased part, station or gate."""
    for ident, record in evidence.get("parts", {}).items():
        for gate in PART_GATES:
            yield "part:" + ident, gate, record.get(gate)
    for ident, record in evidence.get("room_pod", {}).items():
        for gate in PART_GATES:
            yield "room:" + ident, gate, record.get(gate)
    for gate in SYSTEM_GATES:
        if first_robot and gate in FLEET_ONLY_SYSTEM_GATES:
            continue
        yield "system", gate, evidence.get("system", {}).get(gate)
    if first_robot:
        system = evidence.get("system", {})
        gate = first_robot_room_receipt_gate(system)
        yield "system", gate, system.get(gate)
    for ident in SUPPLEMENTAL_DECISIONS:
        if ident in deferred_optional_ids:
            # Generator already verified this optional parent is not selected.
            continue
        selection = evidence.get("supplemental_decisions", {}).get(ident, {})
        scope = "supplemental:" + ident
        yield scope, "decision_receipt", selection.get("decision_receipt")
        if selection.get("disposition") in {"selected", "reuse_existing"}:
            for gate in PART_GATES:
                yield scope, gate, selection.get(gate)
        else:
            yield scope, "alternative_or_parent_receipt", (
                selection.get("alternative_or_parent_receipt")
            )


def _completed_trial_date(value: object) -> bool:
    """Physical test receipt needs a real ISO date, not a future promise."""
    if not isinstance(value, str):
        return False
    try:
        tested = date.fromisoformat(value)
    except ValueError:
        return False
    return tested.isoformat() == value and tested <= date.today()



def _same_json_measurement(recorded: object, claimed: object) -> bool:
    """Compare immutable physical evidence without Python bool/int coercion.

    Int and float also remain distinct: a signoff must preserve the precise
    JSON type recorded by the reviewer, even when their numeric values match.
    """
    if type(recorded) is not type(claimed):
        return False
    if type(recorded) is dict:
        return (
            recorded.keys() == claimed.keys()
            and all(type(key) is str and _same_json_measurement(value, claimed[key])
                    for key, value in recorded.items())
        )
    if type(recorded) is list:
        return (
            len(recorded) == len(claimed)
            and all(_same_json_measurement(left, right)
                    for left, right in zip(recorded, claimed, strict=True))
        )
    return type(recorded) in (str, int, float, bool, type(None)) and recorded == claimed


# These are safety-critical physical quantities, not a narrative signoff.
# The limits are recorded observations against a reviewer-approved criterion;
# this structural check does not establish that the criterion is safe.
PHYSICAL_GATE_METRICS = {
    "loaded_drive_and_stopping": ("stopping_distance_mm", "mm"),
    "hardware_motor_driver_fails_low_after_cpu_stall": ("cutoff_latency_ms", "ms"),
    "full_power_load_and_faults": ("peak_pack_current_A", "A"),
    "protected_1s_charger_and_dock_contacts": ("net_pack_current_A", "A"),
    "battery_pack_ntc_to_charger_ts_thermal_fault_trial": (
        "thermal_cutoff_latency_ms", "ms",
    ),
    "amplifier_speaker_power_limit_and_thermal_trial": (
        "amplifier_case_temperature_C", "C",
    ),
}


# A signed immutable record is not a witnessed test. These physical product
# gates must at least contain inspectable measurements matching the published
# acceptance criteria; qualitative source/license decisions remain separate.
# Tuple: metric name, unit, minimum result, maximum result, integer-only.
CRITICAL_TRIAL_GATES = {
    "four_cliff_sensor_surface_trials": {
        "minimum_samples": 8,
        "quantities": (
            ("qualified_floor_sensors", "sensors", 4, 4, True),
            ("distinct_tested_surfaces", "surfaces", 2, None, True),
            ("surface_sensor_pairs_tested", "cases", 8, None, True),
            ("minimum_stopping_margin_mm", "mm", 0, None, False),
            ("measured_coast_distance_mm", "mm", 0, None, False),
        ),
    },
    "cliff_sensor_mount_height_and_stopping_geometry": {
        "minimum_samples": 8,
        "quantities": (
            ("installed_optical_height_mm", "mm", 0, None, False),
            ("minimum_measured_floor_range_mm", "mm", 0, None, False),
            ("loaded_coast_distance_mm", "mm", 0, None, False),
            ("minimum_edge_stop_margin_mm", "mm", 0, None, False),
            ("tested_surface_sensor_combinations", "cases", 8, None, True),
        ),
    },
    "four_floor_sensor_reverse_pivot_arc_sweep": {
        "minimum_samples": 8,
        "quantities": (
            ("reverse_direction_trials", "trials", 1, None, True),
            ("left_pivot_trials", "trials", 1, None, True),
            ("right_pivot_trials", "trials", 1, None, True),
            ("distinct_floor_sensors_observed", "sensors", 4, 4, True),
            ("minimum_reverse_pivot_stopping_margin_mm", "mm", 0, None, False),
            ("measured_pivot_coast_distance_mm", "mm", 0, None, False),
        ),
    },
    "sixteen_mux_channel_400khz_pullups_rise_and_sink_trials": {
        # Physical Fast-mode timing must hold on all 16 selected TCA9548A
        # branches, not merely on a convenient short upstream harness.
        # NXP UM10204 and TI TCA9548A: <=300 ns rise, <=400 pF bus load,
        # <=3 mA combined low sink and <=0.4 V LOW on each line.
        "minimum_samples": 16,
        "quantities": (
            ("distinct_mux_lanes_tested", "lanes", 16, 16, True),
            ("configured_clock_khz", "kHz", 400, 400, True),
            ("maximum_scl_rise_time_ns", "ns", 1, 300, False),
            ("maximum_sda_rise_time_ns", "ns", 1, 300, False),
            ("maximum_branch_bus_capacitance_pf", "pF", 1, 400, False),
            ("maximum_scl_sink_current_ma", "mA", 0, 3, False),
            ("maximum_sda_sink_current_ma", "mA", 0, 3, False),
            ("maximum_scl_low_voltage_v", "V", 0, 0.4, False),
            ("maximum_sda_low_voltage_v", "V", 0, 0.4, False),
            ("continuous_poll_cycles", "cycles", 10000, None, True),
            ("i2c_bus_recovery_events", "events", 0, 0, True),
        ),
    },
    "xiao_usb_backfeed_diode_and_servo_brownout_trial": {
        # The external diode is a design allocation, not a measured isolation
        # result. Check both reverse-current directions, attach/detach, loaded
        # startup, idle/active head current and a captured 3V3 ramp.
        # Include single-domain power tests with the installed signal harness.
        # Exact leakage, off-rail and ramp limits depend on the inspected board;
        # the immutable capture and reviewer must establish those limits.
        # ESP32-S3 hardware design guidelines: 3.0–3.6 V operating supply,
        # and t_STBL >= 50 us before CHIP_PU rises. Measure at the chip rail;
        # exclude the unpowered/startup interval from operating extrema.
        # https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32s3/schematic-checklist.html
        "minimum_samples": 6,
        "quantities": (
            ("head_only_power_trials", "trials", 1, None, True),
            ("body_only_power_trials", "trials", 1, None, True),
            ("unpowered_head_peak_rail_v", "V", 0, None, False),
            ("unpowered_body_peak_rail_v", "V", 0, None, False),
            ("unpowered_head_injection_current_ma", "mA", 0, None, False),
            ("unpowered_body_injection_current_ma", "mA", 0, None, False),
            ("unexpected_off_domain_energizations", "events", 0, 0, True),
            ("usb_attach_trials", "trials", 1, None, True),
            ("usb_detach_trials", "trials", 1, None, True),
            ("cold_start_trials", "trials", 1, None, True),
            ("loaded_servo_start_trials", "trials", 1, None, True),
            ("usb_to_boost_reverse_current_ma", "mA", 0, None, False),
            ("boost_to_usb_reverse_current_ma", "mA", 0, None, False),
            ("idle_head_current_ma", "mA", 0, None, False),
            ("active_head_peak_current_ma", "mA", 0, None, False),
            ("head_3v3_ramp_time_ms", "ms", 0, None, False),
            ("head_3v3_minimum_operating_v", "V", 3.0, 3.6, False),
            ("head_3v3_maximum_operating_v", "V", 3.0, 3.6, False),
            ("head_rail_stable_before_chip_enable_us", "us", 50, None, False),
            ("unexpected_head_resets", "events", 0, 0, True),
        ),
    },
    "signed_pack_current_three_new_samples_and_chg_mismatch_trial": {
        # CHG is status, never signed current. INA226's lab-only pack
        # direction needs the physical 5 mOhm Kelvin shunt and independent
        # ammeter agreement, including a net-discharge CHG conflict trial.
        "minimum_samples": 9,
        "quantities": (
            ("fresh_charge_pack_samples", "samples", 3, None, True),
            ("fresh_discharge_pack_samples", "samples", 3, None, True),
            ("fresh_chg_conflict_pack_samples", "samples", 3, None, True),
            ("distinct_pack_acquisition_sequences", "samples", 9, None, True),
            ("observed_charging_current_ma", "mA", 21, None, True),
            ("observed_discharge_magnitude_ma", "mA", 21, None, True),
            ("independent_ammeter_direction_checks", "checks", 2, None, True),
            ("charger_indicator_net_discharge_conflicts", "events", 1, None, True),
            ("inspected_kelvin_shunt_milliohm", "mOhm", 5, 5, False),
            ("charge_authorizations_from_chg_pin", "events", 0, 0, True),
        ),
    },
    "battery_pack_ntc_to_charger_ts_thermal_fault_trial": {
        # A real installed 10k R25 pack NTC must drive BQ24075 TS rather than
        # a fixed resistor. Four independent fault cases must inhibit charge
        # while CHG status alone never certifies net pack current.
        # t_DGL(TS)=50ms is typical, not a guaranteed universal max.
        "minimum_samples": 5,
        "quantities": (
            ("thermal_cutoff_latency_ms", "ms", 0, None, False),
            ("installed_pack_ntc_r25_ohm", "ohm", 10000, 10000, True),
            ("pack_ntc_third_lead_verified", "trials", 1, None, True),
            ("ts_open_suspends_charge_trials", "trials", 1, None, True),
            ("ts_short_suspends_charge_trials", "trials", 1, None, True),
            ("cold_ntc_suspends_charge_trials", "trials", 1, None, True),
            ("hot_ntc_suspends_charge_trials", "trials", 1, None, True),
            ("normal_ntc_resume_trials", "trials", 1, None, True),
            ("independent_ammeter_fault_direction_checks", "checks", 4, None, True),
            ("maximum_positive_pack_charge_during_fault_ma", "mA", 0, 0, False),
            ("chg_only_charge_authorization_events", "events", 0, 0, True),
        ),
    },
    "real_dual_ir_terminal_docking": {
        "minimum_samples": 3,
        "quantities": (
            ("left_ir_observed_trials", "trials", 1, None, True),
            ("center_ir_observed_trials", "trials", 1, None, True),
            ("right_ir_observed_trials", "trials", 1, None, True),
            ("both_seat_switches_confirmed_trials", "trials", 1, None, True),
            ("unpowered_contact_alignment_error_mm", "mm", 0, None, False),
        ),
    },
    "lift_and_grip_calibration": {
        "minimum_samples": 20,
        "quantities": (
            ("flat_key_attempts", "attempts", 10, 10, True),
            ("flat_key_unassisted_successes", "successes", 8, 10, True),
            ("wrapped_candy_attempts", "attempts", 10, 10, True),
            ("wrapped_candy_unassisted_successes", "successes", 8, 10, True),
            ("verified_lift_height_mm", "mm", 10, None, False),
            ("verified_hold_duration_s", "s", 3, None, False),
        ),
    },
    "sense_speaker_mic_double_talk": {
        # Twenty distinct human trials at EACH distance, plus a robot-only
        # echo control and an independent quiet-mode control. Acceptance is
        # physically scoped to the same installed head and audio settings.
        "minimum_samples": 42,
        "quantities": (
            ("ordinary_speech_attempts_50cm", "attempts", 20, 20, True),
            ("ordinary_speech_attempts_100cm", "attempts", 20, 20, True),
            ("audible_stops_within_500ms_50cm", "successes", 19, 20, True),
            ("audible_stops_within_500ms_100cm", "successes", 19, 20, True),
            ("new_intents_retained_50cm", "successes", 18, 20, True),
            ("new_intents_retained_100cm", "successes", 18, 20, True),
            ("robot_only_observation_seconds", "s", 600, None, False),
            ("robot_only_audible_speech_seconds", "s", 120, 600, False),
            ("robot_only_minutes_with_5s_speech", "min", 10, 10, True),
            ("robot_only_playback_volume_levels", "levels", 3, 3, True),
            ("robot_only_false_interruptions", "interruptions", 0, 0, True),
            ("quiet_observation_seconds", "s", 600, None, False),
            ("quiet_unsolicited_speech_events", "events", 0, 0, True),
            ("quiet_unsolicited_motion_events", "events", 0, 0, True),
        ),
    },
    "haptic_hc123_one_shot_stuck_i2c_and_motor_thermal_trial": {
        "minimum_samples": 6,
        "quantities": (
            ("normal_operation_trials", "trials", 3, None, True),
            ("stuck_i2c_fault_trials", "trials", 3, None, True),
            ("minimum_pulse_spacing_s", "s", 1.5, None, False),
            ("measured_pulse_duration_ms", "ms", 1, 200, False),
            ("measured_motor_current_ma", "mA", 1, 500, False),
            ("measured_motor_temperature_c", "C", 0, 85, False),
            ("unbounded_continuous_energizations", "events", 0, 0, True),
        ),
    },
}


# These geometry observations have to establish a positive installed
# clearance or stopping margin; zero is not a safety margin. The accepted
# clearance remains subject to real fitted geometry and physical review.
POSITIVE_CLEARANCE_METRICS = frozenset({
    "minimum_stopping_margin_mm",
    "installed_optical_height_mm",
    "minimum_measured_floor_range_mm",
    "minimum_edge_stop_margin_mm",
    "minimum_reverse_pivot_stopping_margin_mm",
})


def _qualified_trial_gate(gate: str, measurement: dict) -> bool:
    """Format screen only; device, calibration and witness still need review."""
    specification = CRITICAL_TRIAL_GATES[gate]
    if measurement["sample_count"] < specification["minimum_samples"]:
        return False
    conditions = measurement["conditions"]
    keys = ["installed_hardware", "procedure_revision"]
    if gate == "sense_speaker_mic_double_talk":
        firmware_commit = conditions.get("firmware_commit")
        if type(firmware_commit) is not str or not SHA.fullmatch(firmware_commit):
            return False
        keys.extend((
            "robot_id", "firmware_commit", "audio_config_id",
            "mic_speaker_placement_id", "trial_capture_id",
        ))
    if gate == "haptic_hc123_one_shot_stuck_i2c_and_motor_thermal_trial":
        keys.extend((
            "hc123_circuit_revision", "oscilloscope_capture_id",
            "current_capture_id", "thermal_capture_id",
        ))
    if gate == "sixteen_mux_channel_400khz_pullups_rise_and_sink_trials":
        keys.extend((
            "bus_topology_revision", "pullup_network_revision",
            "bench_fixture_id", "rise_capture_id", "sink_capture_id",
        ))
        if conditions.get("instrument_type") not in (
            "oscilloscope_and_ammeter", "oscilloscope_and_calibrated_shunt",
        ):
            return False
    if gate == "signed_pack_current_three_new_samples_and_chg_mismatch_trial":
        keys.extend((
            "wroom_boot_epoch", "raw_pack_sequence_capture",
            "ammeter_calibration_capture", "shunt_board_revision",
            "charger_indicator_conflict_fixture",
        ))
        if conditions.get("instrument_type") != "independent_ammeter":
            return False
    if gate == "battery_pack_ntc_to_charger_ts_thermal_fault_trial":
        keys.extend((
            "pack_thermistor_revision", "ts_network_schematic_revision",
            "thermal_capture_id", "independent_ammeter_capture_id",
            "charge_enable_fixture",
        ))
        if (conditions.get("instrument_type")
                != "temperature_chamber_and_independent_ammeter"
                or conditions.get("fixed_ts_bypass_removed") is not True):
            return False
    if gate == "xiao_usb_backfeed_diode_and_servo_brownout_trial":
        keys.extend((
            "power_path_revision", "oscilloscope_capture_id",
            "current_capture_id", "head_firmware_commit",
            "sense_j3_continuity_capture_id", "gpio_isolation_capture_id",
            "signal_harness_revision", "off_domain_limits_reference",
        ))
        if (conditions.get("sense_sd_j3_open") is not True
                or conditions.get("sense_sd_slot_empty") is not True):
            return False
        firmware_commit = conditions.get("head_firmware_commit")
        if (conditions.get("instrument_type") != "oscilloscope_and_ammeter"
                or type(firmware_commit) is not str
                or not SHA.fullmatch(firmware_commit)):
            return False
    for key in keys:
        value = conditions.get(key)
        if (type(value) is not str or not value.strip()
                or value.strip().casefold() in {"unknown", "tbd", "none", "pass"}):
            return False
    observations = measurement["quantities"]
    if len(observations) < len(specification["quantities"]):
        return False
    for name, unit, lower, upper, integer_only in specification["quantities"]:
        matches = [item for item in observations if item.get("name") == name]
        if len(matches) != 1 or matches[0].get("unit") != unit:
            return False
        numbers = (matches[0].get("value"), matches[0].get("minimum"),
                   matches[0].get("maximum"))
        permitted = (int,) if integer_only else (int, float)
        if any(type(number) not in permitted for number in numbers):
            return False
        try:
            if not all(math.isfinite(number) for number in numbers):
                return False
        except (OverflowError, ValueError):
            return False
        value, minimum, maximum = numbers
        if (minimum < 0 or minimum > value or value > maximum
                or value < lower or (upper is not None and value > upper)
                or (name in POSITIVE_CLEARANCE_METRICS and value <= 0)):
            return False
    if gate == "xiao_usb_backfeed_diode_and_servo_brownout_trial":
        values = {item["name"]: item["value"] for item in observations}
        phase_count = sum(values[name] for name in (
            "usb_attach_trials", "usb_detach_trials",
            "cold_start_trials", "loaded_servo_start_trials",
            "head_only_power_trials", "body_only_power_trials",
        ))
        if (phase_count > measurement["sample_count"]
                or not 0 < values["idle_head_current_ma"]
                <= values["active_head_peak_current_ma"]
                or values["head_3v3_ramp_time_ms"] <= 0
                or values["head_3v3_minimum_operating_v"]
                > values["head_3v3_maximum_operating_v"]):
            return False
    if gate == "signed_pack_current_three_new_samples_and_chg_mismatch_trial":
        values = {item["name"]: item["value"] for item in observations}
        phase_count = sum(values[name] for name in (
            "fresh_charge_pack_samples", "fresh_discharge_pack_samples",
            "fresh_chg_conflict_pack_samples",
        ))
        if (phase_count > measurement["sample_count"]
                or values["distinct_pack_acquisition_sequences"] < phase_count
                or values["distinct_pack_acquisition_sequences"]
                > measurement["sample_count"]):
            return False
    if gate == "battery_pack_ntc_to_charger_ts_thermal_fault_trial":
        values = {item["name"]: item["value"] for item in observations}
        fault_count = sum(values[name] for name in (
            "ts_open_suspends_charge_trials", "ts_short_suspends_charge_trials",
            "cold_ntc_suspends_charge_trials", "hot_ntc_suspends_charge_trials",
        ))
        phase_count = fault_count + values["normal_ntc_resume_trials"]
        # Separate fault and recovery trials cannot share a sample count,
        # and each claimed fault trial needs independent current evidence.
        if (phase_count > measurement["sample_count"]
                or values["independent_ammeter_fault_direction_checks"] < fault_count):
            return False
    return True


NONNEGATIVE_PHYSICAL_GATES = frozenset({
    "loaded_drive_and_stopping",
    "hardware_motor_driver_fails_low_after_cpu_stall",
    "full_power_load_and_faults",
    "battery_pack_ntc_to_charger_ts_thermal_fault_trial",
})


def _qualified_gate_measurement(gate: object, measurement: object) -> bool:
    """Reject text-only or out-of-limit critical physical gate signoffs.

    Numeric evidence is necessary but NOT sufficient for physical approval:
    a human must still inspect actual setup, instrument, calibration, limits
    and the installed hardware. Other gates retain their own open criteria.
    """
    expected = PHYSICAL_GATE_METRICS.get(gate) if isinstance(gate, str) else None
    trial_gate = isinstance(gate, str) and gate in CRITICAL_TRIAL_GATES
    if expected is None and not trial_gate:
        return True
    if type(measurement) is not dict:
        return False
    conditions = measurement.get("conditions")
    samples = measurement.get("sample_count")
    observations = measurement.get("quantities")
    if (type(samples) is not int or not 1 <= samples <= 100000
            or type(conditions) is not dict
            or not all(isinstance(conditions.get(key), str)
                       and conditions[key].strip()
                       and conditions[key].strip().casefold()
                       not in {"unknown", "tbd", "none", "pass"}
                       for key in ("setup", "instrument"))
            or type(observations) is not list
            or not 1 <= len(observations) <= 100):
        return False
    names = [item.get("name") for item in observations if type(item) is dict]
    if (len(names) != len(observations)
            or any(type(name) is not str or not name.strip() for name in names)
            or len(set(names)) != len(names)):
        return False
    matched = [
        item for item in observations
        if type(item) is dict
        and (item.get("name"), item.get("unit")) == expected
    ]
    if trial_gate:
        return _qualified_trial_gate(gate, measurement)
    if len(matched) != 1:
        return False
    item = matched[0]
    bounds = (item.get("value"), item.get("minimum"), item.get("maximum"))
    if not all(type(number) in (int, float) for number in bounds):
        return False
    try:
        if not all(math.isfinite(number) for number in bounds):
            return False
    except (OverflowError, ValueError):
        return False
    # A fitted distance, elapsed cutoff time or absolute peak current cannot
    # be negative even if the claimed acceptance range was also fabricated
    # with negative endpoints. Signed pack shunt current and Celsius case
    # temperature deliberately remain eligible for negative observations.
    if gate in NONNEGATIVE_PHYSICAL_GATES and any(n < 0 for n in bounds):
        return False
    if gate == "hardware_motor_driver_fails_low_after_cpu_stall":
        # The independent CD74HC123 / DRV8833 nSLEEP cutoff must be
        # observed within 100 ms of a deliberately stalled CPU, not within
        # an arbitrary reviewer-supplied maximum of e.g. 200 ms.
        if (item["value"] > 100
                or conditions.get("instrument_type") not in (
                    "logic_analyzer", "oscilloscope",
                )
                or conditions.get("fault_injection") not in (
                    "cpu_stall", "intentional_cpu_halt",
                )):
            return False
    return bounds[1] <= bounds[0] <= bounds[2]


def verified_scoped_record(receipt: dict, sha: str, lookup, *,
                           require_git_blob: bool = False) -> bool:
    """Require one matching record in a versioned docs/records/*.json file.

    The file must contain {"receipts": [record, ...]}, with an explicit
    result, reviewer, tested date, exact revision and measurement payload.
    Release audits additionally require the exact Git blob and a SHA-256
    digest of its bytes. Mere existence of a nonempty file never releases purchasing.
    """
    url = receipt.get("evidence_url")
    if not _completed_trial_date(receipt.get("tested_on")) or type(url) is not str:
        return False
    try:
        record_path = verify_playbook_receipts._canonical_record_path(url)
        match = (
            re.fullmatch(
                rf"/{REPO}/blob/([0-9a-f]{{40}})/docs/records/(.+)", record_path,
            )
            if record_path is not None else None
        )
        if (match is None or not match[2].lower().endswith(".json")
                or any(part in ("", ".", "..") for part in match[2].split("/"))):
            return False
        record_sha, suffix = match[1], match[2]
    except ValueError:
        return False
    response = {}

    def capture(target):
        data = lookup(target)
        response["file"] = data
        return data

    if not verified_raw_record(url, record_sha, capture):
        return False
    file = response.get("file")
    if (not isinstance(file, dict)
            or file.get("encoding") != "base64"
            or not isinstance(file.get("content"), str)
            or not 0 < file["size"] <= 1_000_000):
        return False
    try:
        raw = base64.b64decode("".join(file["content"].split()), validate=True)
        if len(raw) != file["size"]:
            return False
        source_revision = receipt.get("source_sha")
        digest = receipt.get("artifact_sha256")
        if (require_git_blob or digest is not None) and not evidence_digest_matches(raw, digest):
            return False
        if require_git_blob:
            # Git object identity binds the exact decoded bytes to the regular tree entry.
            blob_header = f"blob {len(raw)}\0".encode("ascii")
            blob_sha = hashlib.sha1(blob_header + raw, usedforsecurity=False).hexdigest()
            if not verified_regular_record_path(url, record_sha, lookup, expected_blob_sha=blob_sha):
                return False
            if record_sha != sha:
                if (not evidence_digest_matches(raw, digest)
                        or not source_unchanged_since_test(record_sha, sha, lookup)
                        or not verified_regular_record_path(
                            f"https://github.com/{REPO}/blob/{sha}/docs/records/{suffix}",
                            sha, lookup, expected_blob_sha=blob_sha,
                        )):
                    return False
        if source_revision != sha and (
            not evidence_digest_matches(raw, digest)
            or not source_unchanged_since_test(source_revision, sha, lookup)
        ):
            return False
        document = json.loads(
            raw.decode("utf-8"), object_pairs_hook=strict_receipt_object,
            parse_constant=reject_nonfinite_receipt_value,
            parse_float=finite_receipt_float,
            parse_int=bounded_receipt_int,
        )
    except (ValueError, TypeError, UnicodeError, binascii.Error, RecursionError):
        return False
    rows = document.get("receipts") if type(document) is dict else None
    if not isinstance(rows, list) or not 0 < len(rows) <= 2000:
        return False
    identifiers = [row.get("record_id") for row in rows if type(row) is dict]
    if (len(identifiers) != len(rows)
            or any(not isinstance(i, str) or not i.strip() for i in identifiers)
            or len(set(identifiers)) != len(identifiers)):
        return False
    matched = [
        row for row in rows
        if row.get("scope") == receipt.get("scope")
        and row.get("gate") == receipt.get("gate")
    ]
    if len(matched) != 1:
        return False
    record = matched[0]
    fields = (
        "record_id", "source_sha", "scope", "gate", "result",
        "reviewer", "tested_on", "device_revision",
    )
    measurement = record.get("measurement")
    return (record.get("result") == "pass"
            and all(record.get(key) == receipt.get(key) for key in fields)
            and isinstance(measurement, dict) and bool(measurement)
            and _qualified_gate_measurement(record.get("gate"), measurement)
            and _same_json_measurement(measurement, receipt.get("measurement")))


PROCUREMENT_REVIEW_LINE = re.compile(
    r"ACCEPTED procurement [A-Za-z0-9_.:-]+ [A-Za-z0-9_.:-]+ "
    r"at [0-9a-f]{40} digest [0-9a-f]{64}"
)


def procurement_review_statement(receipt: dict) -> str | None:
    """Canonical review text binds scope, source, artifact and measured values."""
    fields = (
        "record_id", "source_sha", "scope", "gate", "result", "reviewer",
        "tested_on", "device_revision", "measurement", "evidence_url", "artifact_sha256",
    )
    try:
        payload = json.dumps(
            {key: receipt.get(key) for key in fields},
            sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False,
        ).encode("ascii")
        digest = hashlib.sha256(payload).hexdigest()
        statement = (
            f"ACCEPTED procurement {receipt['scope']} {receipt['gate']} "
            f"at {receipt['source_sha']} digest {digest}"
        )
    except (AttributeError, KeyError, TypeError, ValueError, RecursionError):
        return None
    return statement if PROCUREMENT_REVIEW_LINE.fullmatch(statement) else None


def verified_procurement_review(receipt: dict, lookup) -> bool:
    """Require a deliberate PR #17 comment from the actual claimed reviewer."""
    if type(receipt) is not dict:
        return False
    url = receipt.get("review_url")
    reviewer = receipt.get("reviewer")
    if type(url) is not str or type(reviewer) is not str:
        return False
    match = re.fullmatch(
        rf"https://github\.com/{REPO}/pull/17#issuecomment-([0-9]+)", url,
    )
    expected = procurement_review_statement(receipt)
    if match is None or expected is None:
        return False
    comment = lookup(f"https://api.github.com/repos/{REPO}/issues/comments/{match[1]}")
    if type(comment) is not dict:
        return False
    actor = comment.get("user")
    body = comment.get("body")
    if (comment.get("html_url") != url or type(actor) is not dict
            or actor.get("type") != "User" or actor.get("login") != reviewer
            or comment.get("author_association") not in ("OWNER", "MEMBER", "COLLABORATOR")
            or type(body) is not str or not 0 < len(body) <= 65536):
        return False
    lines = body.strip().splitlines()
    return (expected in lines and len(lines) == len(set(lines))
            and all(PROCUREMENT_REVIEW_LINE.fullmatch(line) for line in lines))


def audit_release(evidence: dict, sha: str, lookup=None, *,
                  first_robot: bool = False,
                  deferred_optional_ids: frozenset[str] = frozenset()) -> list[str]:
    """Fail closed if a receipt is missing, mis-scoped or not actually present."""
    if (not isinstance(evidence, dict) or type(sha) is not str
            or not SHA.fullmatch(sha)):
        return ["missing exact checkout SHA or release evidence"]
    # These are untrusted machine-readable release receipts. A wrong JSON
    # section shape cannot turn into an uncaught .items()/.get() exception.
    for section in ("parts", "room_pod", "system", "supplemental_decisions"):
        records = evidence.get(section, {})
        if (not isinstance(records, dict)
                or (section != "system"
                    and any(not isinstance(r, dict)
                            for r in records.values()))):
            return [f"malformed {section} release evidence"]
    allowed_deferred = conditional_station_decision_ids(CONDITIONAL_ROOM_PER_STATION)
    if (not isinstance(deferred_optional_ids, frozenset)
            or not deferred_optional_ids <= allowed_deferred):
        return ["invalid deferred optional receipt scope"]
    if any(ident in evidence.get("supplemental_decisions", {})
           for ident in deferred_optional_ids):
        return ["deferred optional has conflicting purchase evidence"]
    from verify_playbook_receipts import github_json
    lookup = github_json if lookup is None else lookup
    errors = []
    seen = 0
    fetched = {}

    def cached_lookup(url):
        if url not in fetched:
            fetched[url] = lookup(url)
        return fetched[url]

    for scope, gate, receipt in required_receipts(
        evidence, first_robot=first_robot,
        deferred_optional_ids=deferred_optional_ids,
    ):
        seen += 1
        if not isinstance(receipt, dict):
            errors.append(f"{scope}.{gate}: missing receipt")
            continue
        if (receipt.get("result") != "pass"
                or not (
                    receipt.get("source_sha") == sha
                    or (
                        isinstance(receipt.get("artifact_sha256"), str)
                        and source_unchanged_since_test(
                            receipt.get("source_sha"), sha, cached_lookup
                        )
                    )
                )
                or receipt.get("scope") != scope
                or receipt.get("gate") != gate
                or not isinstance(receipt.get("reviewer"), str)
                or receipt["reviewer"].strip().casefold() in {
                    "", "unknown", "tbd", "operator", "tester", "fixture",
                }
                or not _completed_trial_date(receipt.get("tested_on"))
                or not isinstance(receipt.get("record_id"), str)
                or not receipt["record_id"].strip()
                or not isinstance(receipt.get("device_revision"), str)
                or receipt["device_revision"].strip().casefold() in {
                    "", "unknown", "tbd", "generic",
                }
                or not isinstance(receipt.get("measurement"), dict)
                or not receipt["measurement"]
                or not _qualified_gate_measurement(gate, receipt["measurement"])):
            errors.append(f"{scope}.{gate}: unpinned or generic signoff")
            continue
        try:
            if not verified_scoped_record(receipt, sha, cached_lookup, require_git_blob=True):
                errors.append(f"{scope}.{gate}: immutable scoped record absent or mismatched")
            elif not verified_procurement_review(receipt, cached_lookup):
                errors.append(f"{scope}.{gate}: authorized reviewer approval missing or mismatched")
        except (HTTPError, URLError, ValueError, TimeoutError, OSError, RecursionError):
            errors.append(f"{scope}.{gate}: record lookup unavailable")
    if seen == 0:
        errors.append("no release receipts recorded")
    return errors
