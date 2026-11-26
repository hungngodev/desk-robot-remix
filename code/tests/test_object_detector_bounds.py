"""Boundaries of the object detector's original pixel-coordinate contract."""

import math

import pytest
from desk_robot.object_detector import _checked_detection
from desk_robot.vision import Detection


@pytest.mark.parametrize("box", [
    (-0.01, 0, 40, 30),
    (0, -0.01, 40, 30),
    (0, 0, 40.01, 30),
    (0, 0, 40, 30.01),
    (0, 0, 0, 30),
    (0, 0, 40, 0),
    (0, 0, 40, float("inf")),
])
def test_invalid_box_does_not_become_a_partial_observation(box):
    good = Detection("key", 0.95, (0, 0, 40, 30))
    bad = Detection("key", 0.95, box)
    for detections in ([good, bad], [bad, good]):
        assert _checked_detection(detections, "key", 40, 30, 0.85) == (
            "invalid_detector_result", None,
        )


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -0.01, 0, 1.01])
def test_invalid_score_does_not_become_absence(score):
    assert _checked_detection([Detection("key", score, (0, 0, 40, 30))],
                              "key", 40, 30, 0.85) == ("invalid_detector_result", None)


@pytest.mark.parametrize("score, expected", [
    (math.nextafter(0.85, 0), "inconclusive_low_confidence"),
    (0.85, "camera_seen"),
    (math.nextafter(0.85, 1), "camera_seen"),
    (1, "camera_seen"),
])
def test_confidence_threshold_is_inclusive(score, expected):
    outcome, best = _checked_detection([Detection("key", score, (0, 0, 40, 30))],
                                       "key", 40, 30, 0.85)
    assert outcome == expected
    assert (best is not None) == (expected == "camera_seen")


def test_empty_result_is_distinct_from_empty_prediction_label():
    assert _checked_detection([], "key", 40, 30, 0.85) == ("camera_not_seen", None)
    assert _checked_detection([Detection("", 0.95, (0, 0, 40, 30))],
                              "key", 40, 30, 0.85) == ("invalid_detector_result", None)


def test_equal_boxes_have_canonical_numeric_representation_in_either_order():
    integer = Detection("key", 1, (0, 0, 40, 30))
    floating = Detection("key", 1.0, (-0.0, -0.0, 40.0, 30.0))
    for detections in ([integer, floating], [floating, integer]):
        outcome, best = _checked_detection(detections, "key", 40, 30, 0.85)
        assert outcome == "camera_seen"
        assert best is not None
        assert type(best.confidence) is float
        assert all(type(value) is float for value in best.box)
        assert best.box == (0.0, 0.0, 40.0, 30.0)
        assert all(math.copysign(1, value) == 1 for value in best.box[:2])
