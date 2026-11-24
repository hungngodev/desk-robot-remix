"""Three low-cost VL53L0X side/rear directions emit read-only pet events."""
import asyncio
from pathlib import Path

import pytest
from desk_robot.config import load_settings
from desk_robot.conversation import Conversation
from desk_robot.memory import MemoryStore
from desk_robot.pet import PetController
from desk_robot.side_ranging import SideRangeEvents
from desk_robot.simulator import SimulatedChat, SimulatedScene, SimulatedSpeaker


def body(*, mm=(600, 600, 600), ages=(30, 30, 30),
         present=7, valid=7, sample_ms=None, boot_id=None):
    side = {
        "mm": list(mm), "age_ms": list(ages),
        "present_mask": present, "valid_mask": valid,
        "motion_certified": False,
    }
    if sample_ms is not None:
        side.update(sample_ms=list(sample_ms), boot_id=boot_id)
        return {"side_ranges": side, "imu": {"boot_id": boot_id}}
    return {"side_ranges": side}


def test_side_near_requires_two_independent_new_samples_and_far_rearm():
    tracker = SideRangeEvents()
    assert tracker.observe(body(), now=10.00, near_mm=170) == []
    assert tracker.observe(body(mm=(100, 600, 600)), now=10.10, near_mm=170) == []
    # Duplicate body status with stale 130ms age is not a second ADC reading.
    assert tracker.observe(body(mm=(100, 600, 600), ages=(130, 30, 30)),
                           now=10.20, near_mm=170) == []
    assert tracker.observe(body(mm=(95, 600, 600)), now=10.26,
                           near_mm=170) == [("left", 95)]
    # Repeated near data do not make new events.
    assert tracker.observe(body(mm=(90, 600, 600)), now=10.40,
                           near_mm=170) == []
    assert tracker.observe(body(), now=10.54, near_mm=170) == []
    assert tracker.observe(body(), now=10.68, near_mm=170) == []
    assert tracker.observe(body(mm=(100, 600, 600)), now=10.82,
                           near_mm=170) == []
    assert tracker.observe(body(mm=(105, 600, 600)), now=10.96,
                           near_mm=170) == [("left", 105)]


def test_invalid_channel_and_stale_age_cannot_invent_rearm_events():
    tracker = SideRangeEvents()
    tracker.observe(body(), now=1.0, near_mm=180)
    assert tracker.observe(body(mm=(120, 600, 600), valid=6),
                           now=1.2, near_mm=180) == []
    assert tracker.observe(body(mm=(120, 600, 600)), now=1.3,
                           near_mm=180) == []  # first sample is baseline
    assert tracker.observe(body(mm=(120, 600, 600), ages=(600, 30, 30)),
                           now=1.5, near_mm=180) == []
    assert tracker.observe(body(mm=(120, 600, 600)), now=1.7,
                           near_mm=180) == []
    assert tracker.observe(body(mm=(110, 600, 600)), now=1.9,
                           near_mm=180) == []


def test_side_masks_and_untrusted_ranges_fail_closed():
    tracker = SideRangeEvents()
    for invalid in (
        {"mm": [100, 100], "age_ms": [20, 20, 20],
         "present_mask": 7, "valid_mask": 7,
         "motion_certified": False},
        {"mm": [100, 100, 100], "age_ms": [20, 20, 20],
         "present_mask": 0, "valid_mask": 7,
         "motion_certified": False},
        {"mm": [100, 100, 100], "age_ms": [20, 20, 20],
         "present_mask": 7, "valid_mask": 7,
         "motion_certified": True},
    ):
        assert tracker.observe({"side_ranges": invalid}, now=1.0,
                               near_mm=180) == []
    assert tracker.observe({"side_ranges": "forged"}, now=1.0,
                           near_mm=180) == []


async def test_real_side_event_is_one_robot_memory_not_motion(tmp_path):
    settings = load_settings(
        Path(__file__).resolve().parents[1] / "config/fleet.simulation.toml"
    )
    settings.mode = "hardware"
    settings.robots[0].side_interactions_qualified = True
    settings.robots[0].side_near_threshold_mm = 180
    memory = MemoryStore(tmp_path, [r.id for r in settings.robots])
    speaker = SimulatedSpeaker()
    conversation = Conversation(
        settings, SimulatedChat(), speaker, memory=memory
    )
    pet = PetController(settings, {}, conversation, memory, SimulatedScene())
    state = pet.states["robot-01"]
    state.enabled, state.quiet, state.generation = True, True, 3
    try:
        await pet._observe_side_ranges(
            "robot-01", 3, body(sample_ms=(100, 100, 100), boot_id=901)
        )
        await asyncio.sleep(.08)
        await pet._observe_side_ranges(
            "robot-01", 3, body(mm=(600, 75, 600),
                                sample_ms=(200, 200, 200), boot_id=901)
        )
        await asyncio.sleep(.08)
        await pet._observe_side_ranges(
            "robot-01", 3, body(mm=(600, 80, 600),
                                sample_ms=(300, 300, 300), boot_id=901)
        )
        records = [m for m in memory.recent("robot-01")
                   if m.kind == "side_object"]
        assert len(records) == 1
        assert "right" in records[0].summary
        assert records[0].witnessed
        assert memory.count("robot-02") == 0
        assert not speaker.spoken
        # A model event cannot arm WROOM or claim this direction motion safe.
        assert state.last_aux_kind == "side_object"
    finally:
        state.enabled = False
        await pet.close()


def test_threshold_change_cannot_fabricate_new_side_arrival():
    tracker = SideRangeEvents()
    # A stationary object is far with the original measured threshold.
    assert tracker.observe(body(mm=(220, 600, 600)), now=1.00,
                           near_mm=170) == []
    # Operator updates the threshold; the same range is now classed near,
    # but it is a fresh baseline, not evidence that the object moved.
    assert tracker.observe(body(mm=(220, 600, 600)), now=1.12,
                           near_mm=250) == []
    assert tracker.observe(body(mm=(220, 600, 600)), now=1.24,
                           near_mm=250) == []
    # After the threshold change, two genuinely far readings rearm the
    # transition and two new near readings admit exactly one event.
    assert tracker.observe(body(mm=(400, 600, 600)), now=1.36,
                           near_mm=250) == []
    assert tracker.observe(body(mm=(400, 600, 600)), now=1.48,
                           near_mm=250) == []
    assert tracker.observe(body(mm=(220, 600, 600)), now=1.60,
                           near_mm=250) == []
    assert tracker.observe(body(mm=(215, 600, 600)), now=1.72,
                           near_mm=250) == [("left", 215)]


def test_real_wroom_side_acquisition_identity_rejects_polling_jitter():
    tracker = SideRangeEvents()

    def sample(mm, stamp, boot=901):
        return body(mm=(mm, 600, 600), sample_ms=(stamp, stamp, stamp),
                    boot_id=boot)

    assert tracker.observe(sample(600, 100), now=1.0, near_mm=170) == []
    assert tracker.observe(sample(100, 200), now=1.2, near_mm=170) == []
    # Two HTTP responses with different latency are not two conversions.
    assert tracker.observe(body(mm=(100, 600, 600), ages=(0, 0, 0),
                                sample_ms=(200, 200, 200), boot_id=901),
                           now=1.5, near_mm=170) == []
    assert tracker.observe(sample(105, 300), now=1.6,
                           near_mm=170) == [("left", 105)]
    assert tracker.observe(sample(600, 250), now=1.8, near_mm=170) == []
    assert tracker.observe(sample(90, 100), now=2.0, near_mm=170) == []

    # Reboot establishes a new baseline, not an immediate rearming event.
    assert tracker.observe(sample(90, 500, boot=902), now=2.1,
                           near_mm=170) == []
    assert tracker.observe(sample(90, 600, boot=901), now=2.2,
                           near_mm=170) == []
    assert tracker.observe(sample(600, 600, boot=902), now=2.3,
                           near_mm=170) == []
    assert tracker.observe(sample(600, 700, boot=902), now=2.4,
                           near_mm=170) == []
    assert tracker.observe(sample(110, 800, boot=902), now=2.5,
                           near_mm=170) == []
    assert tracker.observe(sample(112, 900, boot=902), now=2.6,
                           near_mm=170) == [("left", 112)]
    # Metadata downgrade after a real WROOM boot must also fail closed.
    assert tracker.observe(body(mm=(90, 600, 600)), now=2.7,
                           near_mm=170) == []


def test_invalid_side_acquisition_metadata_cannot_create_an_event():
    tracker = SideRangeEvents()
    assert tracker.observe(body(sample_ms=(100, 100, 100), boot_id=3),
                           now=1.0, near_mm=170) == []
    for tampered in (
        body(sample_ms=(200, 200), boot_id=3),
        body(sample_ms=(200, 200, 200), boot_id=0),
        body(sample_ms=(True, 200, 200), boot_id=3),
        body(sample_ms=(200, 200, 200), boot_id="foreign"),
    ):
        assert tracker.observe(tampered, now=1.2, near_mm=170) == []


def test_hardware_side_proximity_requires_wroom_conversion_identity():
    tracker = SideRangeEvents()
    assert tracker.observe(body(), now=1.0, near_mm=170,
                           require_hardware_identity=True) == []
    assert tracker.observe(body(mm=(100, 600, 600)), now=1.1,
                           near_mm=170, require_hardware_identity=True) == []
    assert tracker.observe(body(mm=(90, 600, 600)), now=1.2,
                           near_mm=170, require_hardware_identity=True) == []
    # A validated boot and real acquisitions recover normal event delivery.
    assert tracker.observe(body(sample_ms=(100, 100, 100), boot_id=2),
                           now=1.3, near_mm=170,
                           require_hardware_identity=True) == []
    assert tracker.observe(body(mm=(100, 600, 600),
                                sample_ms=(200, 200, 200), boot_id=2),
                           now=1.4, near_mm=170,
                           require_hardware_identity=True) == []
    assert tracker.observe(body(mm=(95, 600, 600),
                                sample_ms=(300, 300, 300), boot_id=2),
                           now=1.5, near_mm=170,
                           require_hardware_identity=True) == [("left", 95)]


def test_hardware_side_source_rejects_conflicting_imu_boot_identity():
    tracker = SideRangeEvents()
    trusted = body(sample_ms=(100, 100, 100), boot_id=17)
    assert tracker.observe(trusted, now=1, near_mm=170,
                           require_hardware_identity=True) == []
    mismatch = body(mm=(100, 600, 600),
                    sample_ms=(200, 200, 200), boot_id=17)
    mismatch["imu"]["boot_id"] = 18
    assert tracker.observe(mismatch, now=1.1, near_mm=170,
                           require_hardware_identity=True) == []
    incomplete = body(mm=(100, 600, 600),
                      sample_ms=(300, 300, 300), boot_id=17)
    incomplete.pop("imu")
    assert tracker.observe(incomplete, now=1.2, near_mm=170,
                           require_hardware_identity=True) == []
    # A subsequent intact response begins afresh instead of inheriting a
    # near hit from the mismatched or missing hardware identity.
    assert tracker.observe(body(mm=(100, 600, 600),
                                sample_ms=(400, 400, 400), boot_id=17),
                           now=1.3, near_mm=170,
                           require_hardware_identity=True) == []
    assert tracker.observe(body(mm=(95, 600, 600),
                                sample_ms=(500, 500, 500), boot_id=17),
                           now=1.4, near_mm=170,
                           require_hardware_identity=True) == []


def test_twelve_valid_reboots_recover_without_retired_identity_replay():
    """Never brick read-only proximity after eight boots or reuse retired data."""
    tracker = SideRangeEvents()

    def sample(distance, acquisition, boot_id):
        return body(mm=(distance, 600, 600),
                    sample_ms=(acquisition, acquisition, acquisition),
                    boot_id=boot_id)

    for index in range(12):
        boot_id = 5000 + index
        t = index * 2.0 + 1.0
        assert tracker.observe(sample(600, 100, boot_id), now=t,
                               near_mm=170, require_hardware_identity=True) == []
        assert tracker.observe(sample(90, 200, boot_id), now=t + .1,
                               near_mm=170, require_hardware_identity=True) == []
        assert tracker.observe(sample(95, 300, boot_id), now=t + .2,
                               near_mm=170,
                               require_hardware_identity=True) == [("left", 95)]
        # An old boot packet is never permission to generate a new observation
        # or to reset the active boot's proximity transition history.
        for retired in range(5000, boot_id):
            assert tracker.observe(sample(88, 400, retired), now=t + .3,
                                   near_mm=170,
                                   require_hardware_identity=True) == []
        assert tracker.active_boot_id == boot_id
        assert len(tracker.retired_boot_ids) == index
        assert tracker.observe(sample(600, 400, boot_id), now=t + .4,
                               near_mm=170, require_hardware_identity=True) == []
        assert tracker.observe(sample(600, 500, boot_id), now=t + .5,
                               near_mm=170, require_hardware_identity=True) == []
        assert tracker.observe(sample(100, 600, boot_id), now=t + .6,
                               near_mm=170, require_hardware_identity=True) == []
        assert tracker.observe(sample(95, 700, boot_id), now=t + .7,
                               near_mm=170,
                               require_hardware_identity=True) == [("left", 95)]


@pytest.mark.parametrize("now", [10 ** 1000, -(10 ** 1000)])
def test_unrepresentably_large_side_event_clock_fails_closed(now):
    """One malformed host clock must not crash the five-pet side observer."""
    tracker = SideRangeEvents()
    with pytest.raises(ValueError, match="finite clock"):
        tracker.observe(body(), now=now, near_mm=170)
    # The next real timestamp must remain a baseline and not invent motion.
    assert tracker.observe(body(), now=1.0, near_mm=170) == []


def test_transport_delay_does_not_make_serialized_side_sample_fresh():
    tracker = SideRangeEvents()
    def sample(mm, stamp):
        return body(
            mm=(mm, 600, 600),
            sample_ms=(stamp, stamp, stamp),
            boot_id=901,
        )
    assert tracker.observe(sample(600, 100), now=10.0, near_mm=170,
                           require_hardware_identity=True) == []
    assert tracker.observe(sample(100, 200), now=11.1, near_mm=170,
                           require_hardware_identity=True,
                           request_elapsed_ms=1100.0) == []
    assert tracker.observe(sample(100, 300), now=12.2, near_mm=170,
                           require_hardware_identity=True,
                           request_elapsed_ms=1100.0) == []
    # A new immediate far baseline followed by two genuinely fresh
    # conversions may still produce the same source-qualified cue.
    assert tracker.observe(sample(600, 400), now=12.3, near_mm=170,
                           require_hardware_identity=True) == []
    assert tracker.observe(sample(100, 500), now=12.4, near_mm=170,
                           require_hardware_identity=True) == []
    assert tracker.observe(sample(95, 600), now=12.5, near_mm=170,
                           require_hardware_identity=True) == [("left", 95)]
    for bad in (-1, float("nan"), float("inf"), True, "5", 10 ** 500):
        with pytest.raises(ValueError, match="request duration"):
            tracker.observe(sample(100, 700), now=13.0, near_mm=170,
                            request_elapsed_ms=bad)


async def test_real_side_status_slow_transport_never_records_stale_firsthand_event(
    tmp_path,
):
    """The actual Mac status await must contribute to the side freshness gate."""
    settings = load_settings(
        Path(__file__).resolve().parents[1] / "config/fleet.simulation.toml"
    )
    settings.mode = "hardware"
    settings.robots[0].side_interactions_qualified = True
    settings.robots[0].side_near_threshold_mm = 180
    memory = MemoryStore(tmp_path, [r.id for r in settings.robots])
    conversation = Conversation(
        settings, SimulatedChat(), SimulatedSpeaker(), memory=memory
    )
    pet = PetController(settings, {}, conversation, memory, SimulatedScene())
    state = pet.states["robot-01"]
    state.enabled, state.quiet, state.generation = True, True, 3

    steps = [
        (0, 600, 100),
        (0.38, 100, 200),
        (0.38, 100, 300),
        (0, 600, 400),
        (0, 100, 500),
        (0, 95, 600),
    ]

    class DelayedHead:
        async def status(self):
            delay, mm, stamp = steps.pop(0)
            result = body(
                mm=(mm, 600, 600),
                sample_ms=(stamp, stamp, stamp),
                boot_id=901,
            )
            result["robot_id"] = "robot-01"
            # The device serialized the acquisition BEFORE network/host
            # latency; the Mac receives that same older response afterward.
            if delay:
                await asyncio.sleep(delay)
            return result

    pet.heads["robot-01"] = DelayedHead()
    try:
        for _ in range(3):
            await pet._touch_from_body("robot-01", 3)
        assert [m for m in memory.recent("robot-01")
                if m.kind == "side_object"] == []
        for _ in range(3):
            await pet._touch_from_body("robot-01", 3)
        events = [m for m in memory.recent("robot-01")
                  if m.kind == "side_object"]
        assert len(events) == 1
        assert "left" in events[0].summary
        assert events[0].witnessed
        assert memory.count("robot-02") == 0
    finally:
        state.enabled = False
        await pet.close()


def test_rollback_receive_clock_disarms_side_event_votes():
    tracker = SideRangeEvents()

    def sample(mm, stamp):
        return body(mm=(mm, 600, 600), sample_ms=(stamp, stamp, stamp),
                    boot_id=901)

    def observe(mm, stamp, now):
        return tracker.observe(sample(mm, stamp), now=now, near_mm=170,
                               require_hardware_identity=True)

    assert observe(600, 100, 10.0) == []
    assert observe(100, 200, 10.1) == []
    # Newer physical conversions cannot create a Mac clock-rollback event.
    assert observe(95, 300, 9.9) == []
    assert observe(95, 400, 10.2) == []  # fresh baseline after reset
    assert observe(600, 500, 10.3) == []
    assert observe(600, 600, 10.4) == []
    assert observe(100, 700, 10.5) == []
    assert observe(95, 800, 10.6) == [("left", 95)]


@pytest.mark.parametrize("reset", ["invalid_lane", "invalid_response", "threshold", "rollback"])
def test_same_boot_reset_cannot_replay_previously_seen_acquisitions(reset):
    tracker = SideRangeEvents()
    threshold = 170

    def sample(distance, stamp, valid=7):
        return body(mm=(distance, 600, 600), sample_ms=(stamp,) * 3,
                    boot_id=901, valid=valid)

    def observe(data, now):
        return tracker.observe(data, now=now, near_mm=threshold,
                               require_hardware_identity=True)

    assert observe(sample(600, 400), 10.0) == []
    assert observe(sample(100, 500), 10.1) == []
    if reset == "invalid_lane":
        assert observe(sample(100, 500, valid=6), 10.2) == []
    elif reset == "invalid_response":
        assert observe({}, 10.2) == []
    elif reset == "threshold":
        threshold = 180
        assert observe(sample(600, 50), 10.2) == []
    else:
        assert observe(sample(100, 500), 9.9) == []
    # Resetting proximity votes must not forget the boot's acquisition fence.
    assert observe(sample(600, 100), 10.3) == []
    assert observe(sample(100, 200), 10.4) == []
    assert observe(sample(95, 300), 10.5) == []
    # A fresh baseline and two newer conversions still recover normally.
    assert observe(sample(600, 600), 10.6) == []
    assert observe(sample(100, 700), 10.7) == []
    assert observe(sample(95, 800), 10.8) == [("left", 95)]


def test_subminimum_range_clears_only_its_lane_and_recovers_at_valid_boundary():
    tracker = SideRangeEvents()

    def observe(left, right, stamp):
        return tracker.observe(body(mm=(left, right, 600), sample_ms=(stamp,) * 3,
                                    boot_id=901), now=10.0 + stamp / 1000,
                               near_mm=170, require_hardware_identity=True)

    assert observe(600, 600, 100) == []
    assert observe(29, 80, 200) == []
    assert observe(28, 85, 300) == [("right", 85)]
    assert observe(600, 85, 400) == []
    assert observe(30, 85, 500) == []
    assert observe(30, 85, 600) == [("left", 30)]


@pytest.mark.parametrize("valid", [6, 7])
@pytest.mark.parametrize("sentinel", [8190, 65535])
def test_invalid_raw_range_does_not_suppress_healthy_directions(valid, sentinel):
    tracker = SideRangeEvents()

    def observe(left, right, stamp, mask):
        return tracker.observe(body(mm=(left, right, 600), sample_ms=(stamp,) * 3,
                                    boot_id=901, valid=mask),
                               now=10.0 + stamp / 1000, near_mm=170,
                               require_hardware_identity=True)

    assert observe(600, 600, 100, 7) == []
    assert observe(sentinel, 80, 200, valid) == []
    assert observe(sentinel, 85, 300, valid) == [("right", 85)]
    assert observe(600, 85, 400, 7) == []
    assert observe(100, 85, 500, 7) == []
    assert observe(95, 85, 600, 7) == [("left", 95)]


@pytest.mark.parametrize("malformed", [-1, 65536, True, "8190"])
def test_side_ranges_still_reject_nonuint16_raw_data(malformed):
    tracker = SideRangeEvents()

    def observe(left, right, stamp):
        return tracker.observe(body(mm=(left, right, 600), sample_ms=(stamp,) * 3,
                                    boot_id=901, valid=6),
                               now=10.0 + stamp / 1000, near_mm=170,
                               require_hardware_identity=True)

    assert observe(600, 600, 100) == []
    assert observe(600, 80, 200) == []
    assert observe(malformed, 85, 300) == []
    assert observe(600, 85, 400) == []
