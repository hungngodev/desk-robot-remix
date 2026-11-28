"""Synthetic optical isolation for the first two assigned fleet docks."""

from dataclasses import replace

import pytest
from desk_robot.dock_vision import DockCameraCalibration, detect_apriltag


def _scene(*markers):
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    canvas = np.full((480, 640), 255, dtype=np.uint8)
    for marker_id, x, size in markers:
        y = 240 - size // 2
        canvas[y:y + size, x:x + size] = cv2.aruco.generateImageMarker(
            dictionary, marker_id, size,
        )
    ok, jpeg = cv2.imencode(".jpg", canvas)
    assert ok
    # A passing test must actually contain every requested optical identity.
    detector = cv2.aruco.ArucoDetector(dictionary)
    _, ids, _ = detector.detectMarkers(cv2.imdecode(jpeg, cv2.IMREAD_GRAYSCALE))
    assert ids is not None
    assert sorted(ids.ravel().tolist()) == sorted(marker[0] for marker in markers)
    return jpeg.tobytes()


@pytest.mark.parametrize(("assigned", "peer"), [(12, 13), (13, 12)])
def test_peer_dock_nearer_than_assigned_dock_never_wins(assigned, peer):
    camera = DockCameraCalibration(410, 410, 320, 240, 60, assigned)
    own = (assigned, 150, 80)
    foreign = (peer, 360, 160)
    own_only = detect_apriltag(_scene(own), camera, captured_at=1.0)
    peer_only = detect_apriltag(
        _scene(foreign), replace(camera, marker_id=peer), captured_at=1.0,
    )
    assert own_only is not None and peer_only is not None
    assert peer_only.z_mm < own_only.z_mm
    assert detect_apriltag(_scene(foreign), camera, captured_at=1.0) is None
    mixed = detect_apriltag(_scene(own, foreign), camera, captured_at=1.0)
    assert mixed is not None
    assert mixed.z_mm == pytest.approx(own_only.z_mm, abs=2)
    assert mixed.x_mm == pytest.approx(own_only.x_mm, abs=2)


def test_duplicate_assigned_marker_is_ambiguous_even_with_peer_present():
    camera = DockCameraCalibration(410, 410, 320, 240, 60, 12)
    jpeg = _scene((12, 70, 80), (12, 240, 80), (13, 400, 120))
    assert detect_apriltag(jpeg, camera, captured_at=1.0) is None
