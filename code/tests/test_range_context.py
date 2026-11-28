"""Receipt-time correlation never converts a camera guess into motor authority."""
import time

import pytest
from desk_robot.range_context import visual_range_caveat


def visual(**changes):
    return {
        "channel": "tool", "kind": "visual_look", "source": "local_vlm_interpretation",
        "age_ms": 2000, "content": "Nothing here", **changes,
    }


def edge(**changes):
    return {
        "channel": "sensor", "kind": "safety_fault", "source": "wroom_event",
        "age_ms": 1000, "fault_detail": "front_obstacle_ch4", **changes,
    }


@pytest.mark.parametrize("age", [1000, 2000, 3000])
@pytest.mark.parametrize("detail", ["front_obstacle", "front_obstacle_ch4"])
def test_front_obstacle_within_receipt_window(age, detail):
    assert visual_range_caveat(visual(), [edge(age_ms=age, fault_detail=detail)]) == (
        "WROOM front obstacle edge near VLM receipt; no clearance inference. "
    )


@pytest.mark.parametrize("changes", [
    {"age_ms": 999}, {"age_ms": 3001}, {"age_ms": 8001}, {"age_ms": -1},
    {"age_ms": True}, {"age_ms": "2000"}, {"age_ms": None},
    {"source": "peer_report"}, {"source": None}, {"channel": "sensor_history"},
    {"fault_detail": "front_out_of_range"}, {"fault_detail": "floor_out_of_range_ch2"},
    {"fault_detail": ["front_obstacle"]}, {"kind": "nearby_object"},
])
def test_reject_unrelated_stale_or_untrusted_range(changes):
    assert visual_range_caveat(visual(), [edge(**changes)]) == ""


@pytest.mark.parametrize("changes", [
    {"age_ms": 8001}, {"age_ms": True}, {"age_ms": None}, {"age_ms": -1},
    {"source": "peer_report"}, {"kind": "memory_recall"}, {"channel": "camera"},
    {"source": "mac_visual_observation_unavailable"},
    {"content": "observation_unavailable"}, {"content": None},
    {"content": ""}, {"content": "  "}, {"content": []},
])
def test_reject_untrusted_visual_receipt(changes):
    assert visual_range_caveat(visual(**changes), [edge()]) == ""


def test_side_range_is_not_a_forward_obstacle_or_visual_identity():
    side = edge(kind="side_object", fault_detail=None)
    assert visual_range_caveat(visual(), [side]) == (
        "WROOM side range edge near VLM receipt; camera coverage uncertain. "
    )
    assert "front obstacle" in visual_range_caveat(visual(), [side, edge()])
    assert "front obstacle" in visual_range_caveat(visual(), [edge(), side])


@pytest.mark.parametrize("kind, detail, caveat", [
    ("safety_fault", "front_obstacle_ch4", "no clearance inference"),
    ("side_object", None, "camera coverage uncertain"),
])
def test_integration_real_hub_composes_coherent_robot_local_evidence(kind, detail, caveat):
    from desk_robot.brain_context import compose_brain_context
    from desk_robot.multimodal import CameraFrameHub

    robot = "robot-01"
    hub = CameraFrameHub([robot, "robot-02"])
    now = time.monotonic()
    hub.notify(robot, kind, now - 0.7, detail=detail)
    hub.remember_tool(robot, "visual_look", "Nothing here", now - 0.2)
    timeline = hub.interaction_timeline(robot, now)
    prompt = compose_brain_context([], [], timeline).interaction
    assert caveat in prompt
    assert "Earlier local VLM guess, not fresh sighting: Nothing here" in prompt
    assert len(prompt) <= 400
    if kind == "safety_fault":
        assert prompt.startswith("WROOM reported latched safety fault (front_obstacle_ch4)")
        assert "do not drive, reverse, rearm" in prompt
    else:
        assert "Physical sensor edge: side_object" in prompt
        assert "latched safety fault" not in prompt
    other = hub.interaction_timeline("robot-02", now)
    assert compose_brain_context([], [], other).interaction == ""
    # Revoking visual context must not remove the physical range evidence.
    nonvisual = [item for item in timeline if item["kind"] != "visual_look"]
    physical_only = compose_brain_context([], [], nonvisual).interaction
    assert "Nothing here" not in physical_only
    assert caveat not in physical_only
    assert kind in physical_only or "latched safety fault" in physical_only


def test_integration_unavailable_visual_result_is_not_correlated_as_an_observation():
    from desk_robot.brain_context import compose_brain_context
    from desk_robot.multimodal import CameraFrameHub

    robot = "robot-01"
    hub = CameraFrameHub([robot])
    now = time.monotonic()
    hub.notify(robot, "safety_fault", now - 0.7, detail="front_obstacle_ch4")
    hub.remember_tool(robot, "visual_look", "observation_unavailable", now - 0.2)
    prompt = compose_brain_context([], [], hub.interaction_timeline(robot, now)).interaction
    assert prompt.startswith("WROOM reported latched safety fault (front_obstacle_ch4)")
    assert "Visual observation_unavailable; no current sighting" in prompt
    assert "no clearance inference" not in prompt
    assert "Earlier local VLM guess" not in prompt
