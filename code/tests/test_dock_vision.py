"""Docking cannot gain motion or charger authority from image geometry."""
import math

import pytest
from desk_robot.dock_vision import (
    DockAssessment,
    DockCameraCalibration,
    DockPose,
    assess_dock,
    detect_apriltag,
)


def calibration():
    return DockCameraCalibration(
        fx=410, fy=410, cx=320, cy=240,
        tag_side_mm=60, marker_id=12,
    )



@pytest.mark.parametrize(("offset", "yaw", "expected"), [
    (40.0, 0.0, 40.0),
    (-40.0, 0.0, -40.0),
    (0.0, 5.0, 500 * math.sin(math.radians(5))),
    (0.0, -5.0, -500 * math.sin(math.radians(5))),
])
def test_measured_camera_mount_maps_tag_into_chassis_centerline(
    offset, yaw, expected,
):
    from dataclasses import replace

    camera = replace(
        calibration(),
        mount_lateral_offset_mm=offset, mount_yaw_deg=yaw,
    )
    pose = DockPose(0, 0, 500, 0.5, 1)
    assert abs(camera.chassis_lateral_mm(pose) - expected) < 1e-6
    # Reprojection error alone describes the CAMERA, not robot centerline.
    assert pose.x_mm == 0


@pytest.mark.parametrize(("offset", "yaw"), [
    (None, 0.0), (0.0, None), (True, 0), (0, False),
    ("20", 0), (0, "5"), (101, 0), (-101, 0),
    (0, 21), (0, -21), (float("nan"), 0),
    (0, float("inf")), (10 ** 1000, 0),
])
def test_unmeasured_or_invalid_camera_mount_cannot_be_used_to_steer(
    offset, yaw,
):
    from dataclasses import replace

    with pytest.raises(ValueError):
        replace(calibration(), mount_lateral_offset_mm=offset,
                mount_yaw_deg=yaw)
    with pytest.raises(ValueError, match="mounting geometry"):
        calibration().chassis_lateral_mm(
            DockPose(0, 0, 500, 0.5, 1),
        )




@pytest.mark.parametrize(("x_mm", "z_mm", "yaw_deg"), [
    (1.7e308, 1.7e308, 20.0),
    (-1.7e308, 1.7e308, -20.0),
])
def test_dock_camera_mount_transform_overflow_fails_closed(
    x_mm, z_mm, yaw_deg,
):
    """Finite pose components must not become infinite chassis steering data."""
    from dataclasses import replace

    camera = replace(calibration(), mount_lateral_offset_mm=0.0,
                     mount_yaw_deg=yaw_deg)
    pose = DockPose(x_mm, 0, z_mm, 0.5, 1)
    with pytest.raises(ValueError, match="lateral transform"):
        camera.chassis_lateral_mm(pose)
    assessment = assess_dock(None, now=1.1, target_distance_mm=120)
    assert assessment.phase == "hold"
    assert not assessment.motor_authorized and not assessment.charging_authorized


def test_camera_calibration_never_guesses_zero_or_nan_geometry():
    assert calibration().tag_side_mm == 60
    for value in (0, -10, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            DockCameraCalibration(value, 410, 320, 240, 60, 12)
    with pytest.raises(ValueError):
        DockCameraCalibration(410, 410, 320, 240, 0, 12)


def test_docking_assessment_never_returns_motor_or_charger_permission():
    assert assess_dock(None, now=1, target_distance_mm=120).phase == "hold"
    for x, z, error, at, phase in (
        (80, 400, 0.5, 1, "align"),
        (0, 400, 0.5, 1, "approach"),
        (0, 80, 0.5, 1, "hold"),
        (0, 400, 5.0, 1, "hold"),
        (0, 400, 0.5, 0, "hold"),
        (0, 400, 0.5, 2, "hold"),
    ):
        assessment = assess_dock(
            DockPose(x, 0, z, error, at),
            now=1.1, target_distance_mm=120,
        )
        assert assessment.phase == phase
        assert assessment.motor_authorized is False
        assert assessment.charging_authorized is False


def test_dock_pose_rejects_bad_geometry():
    for z in (0, -1, math.nan, math.inf):
        with pytest.raises(ValueError):
            DockPose(0, 0, z, 1, 1)
    assert not DockAssessment("align", "not a command").motor_authorized


def test_dock_vision_rejects_bad_frames_without_cv2_or_io():
    with pytest.raises(ValueError):
        detect_apriltag(b"", calibration(), captured_at=1)
    with pytest.raises(ValueError):
        detect_apriltag(b"hello", calibration(), captured_at=float("nan"))


def test_dock_vision_rejects_nonnumeric_timing_without_loading_cv2():
    for value in (None, "1", True, float("inf")):
        with pytest.raises(ValueError):
            detect_apriltag(b"jpeg", calibration(), captured_at=value)
        with pytest.raises(ValueError):
            detect_apriltag(b"jpeg", calibration(), captured_at=1,
                            max_reprojection_error_px=value)


def test_distortion_coefficients_are_validated_without_motion_authority():
    from dataclasses import replace

    base = calibration()
    assert replace(base, distortion_coeffs=(0.1, -0.05, 0.001, 0.002, 0.0)).distortion_coeffs[0] == 0.1
    for invalid in ((1.0,), (0.0, 0.0, float("nan"), 0.0),
                    (0.0, 0.0, True, 0.0), [0.0] * 5):
        with pytest.raises(ValueError):
            replace(base, distortion_coeffs=invalid)
    assessment = assess_dock(DockPose(0, 0, 300, 0.5, 1),
                             now=1.1, target_distance_mm=120)
    assert not assessment.motor_authorized and not assessment.charging_authorized




@pytest.mark.parametrize(("width", "height"), [
    (640, None), (None, 480), (True, 480),
    (640, "480"), (79, 480), (640, 1600),
])
def test_dock_calibration_refuses_incomplete_or_invalid_image_mode(width, height):
    from dataclasses import replace
    with pytest.raises(ValueError):
        replace(calibration(), image_width_px=width, image_height_px=height)


def test_dock_detector_rejects_camera_mode_change_before_apriltag_pose():
    """Matching distortion and focal lengths are invalid at another JPEG size."""
    from dataclasses import replace

    cv2 = pytest.importorskip("cv2", reason="dock vision tests require the optional vision extra")
    import numpy as np

    measured = replace(
        calibration(), image_width_px=640, image_height_px=480,
        distortion_coeffs=(0.18, -0.07, 0.003, -0.002, 0.01),
    )
    ok, jpeg = cv2.imencode(".jpg", np.zeros((240, 320), dtype=np.uint8))
    assert ok
    with pytest.raises(ValueError, match="resolution differs"):
        detect_apriltag(jpeg.tobytes(), measured, captured_at=5.0)


def test_measured_distortion_recovers_synthetic_apriltag_pose(monkeypatch):
    """Exercise the real OpenCV PnP path with projected distorted corners.

    This is synthetic geometry, not a calibrated XIAO camera or dock trial.
    """
    cv2 = pytest.importorskip("cv2", reason="dock vision tests require the optional vision extra")
    import numpy as np

    distortion = (0.18, -0.07, 0.003, -0.002, 0.01)
    camera = DockCameraCalibration(
        fx=410, fy=410, cx=320, cy=240, tag_side_mm=60,
        marker_id=12, distortion_coeffs=distortion,
        image_width_px=640, image_height_px=480,
    )
    half = camera.tag_side_mm / 2
    object_points = np.array([
        [-half, half, 0], [half, half, 0],
        [half, -half, 0], [-half, -half, 0],
    ], dtype=np.float64)
    intrinsics = np.array([
        [camera.fx, 0, camera.cx], [0, camera.fy, camera.cy],
        [0, 0, 1],
    ], dtype=np.float64)
    # A real printed AprilTag faces the lens: its surface normal points
    # toward the camera, not away as in an inverted synthetic square.
    rotation = np.array([[math.pi - 0.08], [-0.04], [0.03]])
    translation = np.array([[14.0], [-8.0], [380.0]])
    corners, _ = cv2.projectPoints(
        object_points, rotation, translation, intrinsics,
        np.asarray(distortion, dtype=np.float64),
    )

    class SyntheticDetector:
        def __init__(self, dictionary):
            pass

        def detectMarkers(self, frame):
            return [corners.astype(np.float32).reshape(1, 4, 2)], np.array([[12]]), []

    monkeypatch.setattr(cv2.aruco, "ArucoDetector", SyntheticDetector)
    ok, jpeg = cv2.imencode(".jpg", np.zeros((480, 640), dtype=np.uint8))
    assert ok
    pose = detect_apriltag(jpeg.tobytes(), camera, captured_at=5.0)
    assert pose is not None
    assert abs(pose.x_mm - 14.0) < 0.1
    assert abs(pose.y_mm + 8.0) < 0.1
    assert abs(pose.z_mm - 380.0) < 0.5
    assert pose.reprojection_error_px < 0.1
    assessment = assess_dock(pose, now=5.1, target_distance_mm=120)
    assert assessment.phase == "approach"
    assert assessment.motor_authorized is False
    assert assessment.charging_authorized is False


def test_real_printed_apriltag_faces_camera_before_dock_approach():
    """Use real OpenCV tag generation/detection, not a mocked marker ID."""
    cv2 = pytest.importorskip("cv2", reason="dock vision tests require the optional vision extra")
    import numpy as np

    dictionary = cv2.aruco.getPredefinedDictionary(
        cv2.aruco.DICT_APRILTAG_36h11,
    )
    tag = cv2.aruco.generateImageMarker(dictionary, 12, 160)
    canvas = np.full((480, 640), 255, dtype=np.uint8)
    canvas[160:320, 240:400] = tag
    ok, jpeg = cv2.imencode(".jpg", canvas)
    assert ok
    cam = DockCameraCalibration(
        fx=410, fy=410, cx=320, cy=240, tag_side_mm=60,
        marker_id=12, image_width_px=640, image_height_px=480,
    )
    pose = detect_apriltag(jpeg.tobytes(), cam, captured_at=1.0)
    assert pose is not None
    assert abs(pose.x_mm) < 1
    assert abs(pose.y_mm) < 1
    assert 120 < pose.z_mm < 180
    assert pose.reprojection_error_px < 0.5
    decision = assess_dock(
        pose, now=1.05, target_distance_mm=120,
    )
    assert decision.phase == "approach"
    assert not decision.motor_authorized
    assert not decision.charging_authorized


def test_inverted_apriltag_plane_rejected_even_with_perfect_reprojection(monkeypatch):
    """A mirrored/back-facing tag cannot become a physical approach target."""
    cv2 = pytest.importorskip("cv2", reason="dock vision tests require the optional vision extra")
    import numpy as np

    half = 30.0
    square = np.array([
        [-half, half, 0], [half, half, 0],
        [half, -half, 0], [-half, -half, 0],
    ], dtype=np.float64)
    K = np.array([[410, 0, 320], [0, 410, 240], [0, 0, 1]], dtype=np.float64)
    # Exactly inverted face. IPPE recovers a legitimate low-error PnP
    # solution, but its normal points AWAY from the camera.
    image_points, _ = cv2.projectPoints(
        square, np.zeros((3, 1)), np.array([[0.], [0.], [380.]]),
        K, np.zeros(5),
    )

    class BackFacingDetector:
        def __init__(self, dictionary):
            pass

        def detectMarkers(self, frame):
            return [
                image_points.astype(np.float32).reshape(1, 4, 2),
            ], np.array([[12]], dtype=np.int32), []

    monkeypatch.setattr(cv2.aruco, "ArucoDetector", BackFacingDetector)
    ok, jpeg = cv2.imencode(".jpg", np.zeros((480, 640), dtype=np.uint8))
    assert ok
    assert detect_apriltag(
        jpeg.tobytes(), calibration(), captured_at=5.0,
    ) is None
    decision = assess_dock(None, now=5.1, target_distance_mm=120)
    assert decision.phase == "hold"
    assert not decision.motor_authorized
    assert not decision.charging_authorized



@pytest.mark.parametrize("field", [
    "fx", "fy", "cx", "cy", "tag_side_mm", "distortion_coeffs",
])
def test_unrepresentable_measured_camera_number_is_rejected(field):
    from dataclasses import replace
    huge = 10 ** 1000
    change = {field: (0.0, 0.0, huge, 0.0) if field == "distortion_coeffs" else huge}
    with pytest.raises(ValueError):
        replace(calibration(), **change)


@pytest.mark.parametrize("field", [
    "x_mm", "y_mm", "z_mm", "reprojection_error_px", "captured_at",
])
def test_unrepresentable_pose_number_is_rejected(field):
    from dataclasses import replace
    pose = DockPose(0, 0, 300, 0.5, 1)
    with pytest.raises(ValueError):
        replace(pose, **{field: 10 ** 1000})


@pytest.mark.parametrize("field", [
    "now", "target_distance_mm", "max_age_seconds", "lateral_tolerance_mm",
])
def test_unrepresentable_assessment_number_never_grants_motion(field):
    options = dict(now=1.1, target_distance_mm=120,
                   max_age_seconds=0.2, lateral_tolerance_mm=15)
    options[field] = 10 ** 1000
    with pytest.raises(ValueError):
        assess_dock(DockPose(0, 0, 300, 0.5, 1), **options)


@pytest.mark.parametrize("field", ["captured_at", "max_reprojection_error_px"])
def test_unrepresentable_detector_timing_rejected_before_cv2(field):
    options = dict(captured_at=1, max_reprojection_error_px=3)
    options[field] = 10 ** 1000
    with pytest.raises(ValueError):
        detect_apriltag(b"jpeg", calibration(), **options)


@pytest.mark.parametrize(("cx", "cy", "error"), [
    pytest.param(640, 240, "optical center", id="cx-outside-frame"),
    pytest.param(320, 480, "optical center", id="cy-outside-frame"),
    pytest.param(10 ** 1000, 240, "cx must be finite", id="cx-overflow"),
    pytest.param(320, 10 ** 1000, "cy must be finite", id="cy-overflow"),
])
def test_measured_dock_optical_center_must_be_inside_capture(cx, cy, error):
    """Invalid principal points cannot authorize contact approach."""
    from dataclasses import replace

    with pytest.raises(ValueError, match=error):
        replace(calibration(), image_width_px=640, image_height_px=480,
                cx=cx, cy=cy)
    assessment = assess_dock(None, now=1, target_distance_mm=120)
    assert assessment.phase == "hold"
    assert not assessment.motor_authorized and not assessment.charging_authorized


@pytest.mark.parametrize("bad_corner", [
    (float("nan"), 120.0), (float("inf"), 120.0),
    (-1.0, 120.0), (640.0, 120.0),
    (100.0, -1.0), (100.0, 480.0),
])
def test_corrupt_or_off_frame_tag_corners_cannot_reach_pnp(monkeypatch, bad_corner):
    """Reject a detector's invalid geometry before native pose estimation."""
    cv2 = pytest.importorskip("cv2", reason="dock vision tests require the optional vision extra")
    import numpy as np

    class BadDetector:
        def __init__(self, dictionary):
            pass

        def detectMarkers(self, frame):
            points = np.array([[
                [100.0, 100.0], [140.0, 100.0],
                [140.0, 140.0], [100.0, 140.0],
            ]], dtype=np.float64)
            points[0, 0] = bad_corner
            return [points], np.array([[12]]), []

    def forbidden_pnp(*args, **kwargs):
        pytest.fail("Invalid corners reached native solvePnP")

    monkeypatch.setattr(cv2.aruco, "ArucoDetector", BadDetector)
    monkeypatch.setattr(cv2, "solvePnP", forbidden_pnp)
    ok, jpeg = cv2.imencode(".jpg", np.zeros((480, 640), dtype=np.uint8))
    assert ok
    assert detect_apriltag(jpeg.tobytes(), calibration(), captured_at=5) is None
    decision = assess_dock(None, now=5.1, target_distance_mm=120)
    assert decision.phase == "hold"
    assert not decision.motor_authorized and not decision.charging_authorized


@pytest.mark.parametrize("bad_points", [
    [], [[1.0, 2.0]] * 3, [[1.0, 2.0]] * 5,
    [[1.0, 2.0, 3.0]] * 4,
    [[1.0, 2.0]] * 2 + [["not-a-number", 3.0]] + [[1.0, 2.0]],
    [[10 ** 1000, 2.0]] * 4,
])
def test_malformed_detector_corner_shape_never_reaches_pnp(monkeypatch, bad_points):
    """A damaged native detector result must not crash or authorize docking."""
    cv2 = pytest.importorskip("cv2", reason="dock vision tests require the optional vision extra")
    import numpy as np

    class MalformedDetector:
        def __init__(self, dictionary):
            pass

        def detectMarkers(self, frame):
            return [bad_points], np.array([[12]]), []

    def forbidden_pnp(*args, **kwargs):
        pytest.fail("Malformed detector corners reached solvePnP")

    monkeypatch.setattr(cv2.aruco, "ArucoDetector", MalformedDetector)
    monkeypatch.setattr(cv2, "solvePnP", forbidden_pnp)
    ok, jpeg = cv2.imencode(".jpg", np.zeros((480, 640), dtype=np.uint8))
    assert ok
    pose = detect_apriltag(jpeg.tobytes(), calibration(), captured_at=5)
    assert pose is None
    decision = assess_dock(pose, now=5.1, target_distance_mm=120)
    assert decision.phase == "hold"
    assert not decision.motor_authorized and not decision.charging_authorized


@pytest.mark.parametrize("bad_ids", [
    [[12.0]], [[True]], [[12, 12]], [[12], [12]],
    [[float("nan")]], [["12"]], [12], [],
])
def test_malformed_detector_ids_cannot_select_dock_pose(monkeypatch, bad_ids):
    """Corrupt native marker IDs must not reach pose estimation or authority."""
    cv2 = pytest.importorskip("cv2", reason="dock vision tests require the optional vision extra")
    import numpy as np

    class BadIdsDetector:
        def __init__(self, dictionary):
            pass

        def detectMarkers(self, frame):
            corners = [np.array([[
                [100.0, 100.0], [140.0, 100.0],
                [140.0, 140.0], [100.0, 140.0],
            ]], dtype=np.float32)]
            return corners, np.asarray(bad_ids), []

    def forbidden_pnp(*args, **kwargs):
        pytest.fail("Corrupt detector IDs reached solvePnP")

    monkeypatch.setattr(cv2.aruco, "ArucoDetector", BadIdsDetector)
    monkeypatch.setattr(cv2, "solvePnP", forbidden_pnp)
    ok, jpeg = cv2.imencode(".jpg", np.zeros((480, 640), dtype=np.uint8))
    assert ok
    pose = detect_apriltag(jpeg.tobytes(), calibration(), captured_at=5)
    assert pose is None
    decision = assess_dock(pose, now=5.1, target_distance_mm=120)
    assert decision.phase == "hold"
    assert not decision.motor_authorized and not decision.charging_authorized


@pytest.mark.parametrize("failure_stage", ["detect", "solve", "project"])
def test_native_opencv_failure_fails_closed_without_pose_authority(monkeypatch, failure_stage):
    """A native detector or PnP error cannot become an approach observation."""
    cv2 = pytest.importorskip("cv2", reason="dock vision tests require the optional vision extra")
    import numpy as np

    class Detector:
        def __init__(self, dictionary):
            pass

        def detectMarkers(self, frame):
            if failure_stage == "detect":
                raise cv2.error("simulated native detector failure")
            points = np.array([[[100., 100.], [140., 100.],
                                [140., 140.], [100., 140.]]], dtype=np.float32)
            return [points], np.array([[12]], dtype=np.int32), []

    def solve(*args, **kwargs):
        if failure_stage == "solve":
            raise cv2.error("simulated native solve failure")
        return True, np.zeros((3, 1)), np.array([[0.], [0.], [400.]])

    def project(*args, **kwargs):
        raise cv2.error("simulated native projection failure")

    monkeypatch.setattr(cv2.aruco, "ArucoDetector", Detector)
    monkeypatch.setattr(cv2, "solvePnP", solve)
    monkeypatch.setattr(cv2, "projectPoints", project)
    ok, jpeg = cv2.imencode(".jpg", np.zeros((480, 640), dtype=np.uint8))
    assert ok
    pose = detect_apriltag(jpeg.tobytes(), calibration(), captured_at=5)
    assert pose is None
    assessment = assess_dock(pose, now=5.1, target_distance_mm=120)
    assert assessment.phase == "hold"
    assert assessment.motor_authorized is False
    assert assessment.charging_authorized is False


@pytest.mark.parametrize("bad_corners", [
    None, 12, (1, 2, 3), {"marker": 12},
])
def test_corrupt_detector_corner_container_fails_closed(monkeypatch, bad_corners):
    """Native detector output cannot crash the observation safety boundary."""
    cv2 = pytest.importorskip("cv2", reason="dock vision tests require the optional vision extra")
    import numpy as np

    class CorruptDetector:
        def __init__(self, dictionary):
            pass

        def detectMarkers(self, frame):
            return bad_corners, np.array([[12]], dtype=np.int32), []

    def forbidden_pnp(*args, **kwargs):
        pytest.fail("Malformed corners reached native pose estimation")

    monkeypatch.setattr(cv2.aruco, "ArucoDetector", CorruptDetector)
    monkeypatch.setattr(cv2, "solvePnP", forbidden_pnp)
    ok, jpeg = cv2.imencode(".jpg", np.zeros((480, 640), dtype=np.uint8))
    assert ok
    pose = detect_apriltag(jpeg.tobytes(), calibration(), captured_at=5)
    assert pose is None
    decision = assess_dock(pose, now=5.1, target_distance_mm=120)
    assert decision.phase == "hold"
    assert not decision.motor_authorized
    assert not decision.charging_authorized


@pytest.mark.parametrize("decode_failure", ["native_error", "empty_frame"])
def test_dock_jpeg_decode_failure_cannot_authorize_motion(monkeypatch, decode_failure):
    """A failed native JPEG decode never reaches marker detection or motor authority."""
    cv2 = pytest.importorskip("cv2", reason="dock vision tests require the optional vision extra")

    def corrupt_decode(*args, **kwargs):
        if decode_failure == "native_error":
            raise cv2.error("simulated JPEG decoder failure")
        return None

    def forbidden_dictionary(*args, **kwargs):
        pytest.fail("Failed JPEG reached AprilTag detection")

    monkeypatch.setattr(cv2, "imdecode", corrupt_decode)
    monkeypatch.setattr(cv2.aruco, "getPredefinedDictionary", forbidden_dictionary)
    if decode_failure == "native_error":
        pose = detect_apriltag(b"corrupt JPEG", calibration(), captured_at=5)
        assert pose is None
    else:
        with pytest.raises(ValueError, match="Invalid JPEG frame"):
            detect_apriltag(b"corrupt JPEG", calibration(), captured_at=5)
        pose = None
    assessment = assess_dock(pose, now=5.1, target_distance_mm=120)
    assert assessment.phase == "hold"
    assert not assessment.motor_authorized
    assert not assessment.charging_authorized


@pytest.mark.parametrize("failure_stage", ["dictionary", "constructor"])
def test_native_apriltag_setup_failure_cannot_reach_pose_or_motion(monkeypatch, failure_stage):
    """A failed OpenCV detector initialization is not a trusted dock sighting."""
    cv2 = pytest.importorskip("cv2", reason="dock vision tests require the optional vision extra")
    import numpy as np

    def broken_dictionary(*args, **kwargs):
        raise cv2.error("injected dictionary failure")

    class BrokenDetector:
        def __init__(self, dictionary):
            raise cv2.error("injected detector construction failure")

    def forbidden_pnp(*args, **kwargs):
        pytest.fail("Detector setup failure reached pose estimation")

    if failure_stage == "dictionary":
        monkeypatch.setattr(cv2.aruco, "getPredefinedDictionary", broken_dictionary)
    else:
        monkeypatch.setattr(cv2.aruco, "ArucoDetector", BrokenDetector)
    monkeypatch.setattr(cv2, "solvePnP", forbidden_pnp)
    ok, jpeg = cv2.imencode(".jpg", np.zeros((480, 640), dtype=np.uint8))
    assert ok
    pose = detect_apriltag(jpeg.tobytes(), calibration(), captured_at=5)
    assert pose is None
    decision = assess_dock(pose, now=5.1, target_distance_mm=120)
    assert decision.phase == "hold"
    assert not decision.motor_authorized
    assert not decision.charging_authorized


@pytest.mark.parametrize("points", [
    [[100., 100.], [100., 100.], [140., 140.], [100., 140.]],
    [[100., 100.], [140., 140.], [140., 100.], [100., 140.]],
    [[100., 100.], [101., 100.], [101., 101.], [100., 101.]],
    # Both have nonzero polygon area and edges longer than two pixels.
    [[100., 100.], [160., 100.], [120., 120.], [100., 160.]],
    [[100., 100.], [160., 150.], [160., 100.], [100., 160.]],
])
def test_degenerate_dock_quad_rejected_before_native_pnp(monkeypatch, points):
    """Collapsed, crossed, concave and subpixel tags cannot provide a pose."""
    cv2 = pytest.importorskip("cv2", reason="dock vision tests require the optional vision extra")
    import numpy as np

    class Detector:
        def __init__(self, dictionary):
            pass

        def detectMarkers(self, frame):
            return [np.asarray(points, dtype=np.float32).reshape(1, 4, 2)], (
                np.array([[12]], dtype=np.int32)), []

    def forbidden_pnp(*args, **kwargs):
        pytest.fail("Degenerate AprilTag reached solvePnP")

    monkeypatch.setattr(cv2.aruco, "ArucoDetector", Detector)
    monkeypatch.setattr(cv2, "solvePnP", forbidden_pnp)
    ok, jpeg = cv2.imencode(".jpg", np.zeros((480, 640), dtype=np.uint8))
    assert ok
    pose = detect_apriltag(jpeg.tobytes(), calibration(), captured_at=5)
    assert pose is None
    decision = assess_dock(pose, now=5.1, target_distance_mm=120)
    assert decision.phase == "hold"
    assert not decision.motor_authorized
    assert not decision.charging_authorized


@pytest.mark.parametrize("bad_frame", [
    None, 1, [],
    pytest.param("one_dimensional", id="one-dimensional"),
    pytest.param("three_dimensional", id="three-dimensional"),
    pytest.param("empty_width", id="empty-width"),
])
def test_native_decoder_malformed_frame_shape_fails_closed(monkeypatch, bad_frame):
    """A decoder result without a 2D grayscale image cannot reach ArUco."""
    cv2 = pytest.importorskip("cv2", reason="dock vision tests require the optional vision extra")
    import numpy as np

    if bad_frame == "one_dimensional":
        bad_frame = np.zeros(8, dtype=np.uint8)
    elif bad_frame == "three_dimensional":
        bad_frame = np.zeros((8, 8, 3), dtype=np.uint8)
    elif bad_frame == "empty_width":
        bad_frame = np.zeros((8, 0), dtype=np.uint8)

    def forbidden_dictionary(*args, **kwargs):
        pytest.fail("Malformed JPEG frame reached marker detection")

    monkeypatch.setattr(cv2, "imdecode", lambda *args, **kwargs: bad_frame)
    monkeypatch.setattr(cv2.aruco, "getPredefinedDictionary", forbidden_dictionary)
    with pytest.raises(ValueError, match="Invalid JPEG frame"):
        detect_apriltag(b"malformed frame", calibration(), captured_at=5)
    decision = assess_dock(None, now=5.1, target_distance_mm=120)
    assert decision.phase == "hold"
    assert not decision.motor_authorized and not decision.charging_authorized


@pytest.mark.parametrize("bad_dtype", ["float32", "float64", "int16", "bool"])
def test_native_jpeg_decoder_non_uint8_frame_cannot_reach_detector(monkeypatch, bad_dtype):
    """A corrupt native decoder must not feed unexpected pixel types to ArUco."""
    cv2 = pytest.importorskip("cv2", reason="dock vision tests require the optional vision extra")
    import numpy as np

    def corrupt_decode(*args, **kwargs):
        return np.zeros((480, 640), dtype=bad_dtype)

    def forbidden_detector(*args, **kwargs):
        pytest.fail("Non uint8 decoded frame reached native AprilTag detector")

    monkeypatch.setattr(cv2, "imdecode", corrupt_decode)
    monkeypatch.setattr(cv2.aruco, "getPredefinedDictionary", forbidden_detector)
    with pytest.raises(ValueError, match="Invalid JPEG frame"):
        detect_apriltag(b"synthetic JPEG", calibration(), captured_at=5)
    decision = assess_dock(None, now=5.1, target_distance_mm=120)
    assert decision.phase == "hold"
    assert not decision.motor_authorized and not decision.charging_authorized


@pytest.mark.parametrize("malformed_result", [
    None,
    (),
    ([],),
    ([], None),
    ([], None, [], "unexpected fourth field"),
    42,
])
def test_malformed_native_detector_result_fails_closed(monkeypatch, malformed_result):
    """Unexpected native return arity must never reach PnP or docking authority."""
    cv2 = pytest.importorskip("cv2", reason="dock vision tests require the optional vision extra")
    import numpy as np

    class CorruptDetector:
        def __init__(self, dictionary):
            pass

        def detectMarkers(self, frame):
            return malformed_result

    def forbidden_pnp(*args, **kwargs):
        pytest.fail("Malformed native detector result reached solvePnP")

    monkeypatch.setattr(cv2.aruco, "ArucoDetector", CorruptDetector)
    monkeypatch.setattr(cv2, "solvePnP", forbidden_pnp)
    ok, jpeg = cv2.imencode(".jpg", np.zeros((480, 640), dtype=np.uint8))
    assert ok
    pose = detect_apriltag(jpeg.tobytes(), calibration(), captured_at=5)
    assert pose is None
    decision = assess_dock(pose, now=5.1, target_distance_mm=120)
    assert decision.phase == "hold"
    assert not decision.motor_authorized and not decision.charging_authorized


def test_dock_calibration_adds_identity_without_shifting_positional_mount():
    """New source labels must not reinterpret old positional mount geometry."""
    calibration = DockCameraCalibration(
        410, 410, 320, 240, 60, 1, None, 640, 480, "OV5640", 12.0, 2.0,
    )
    assert calibration.mount_lateral_offset_mm == 12.0
    assert calibration.mount_yaw_deg == 2.0
    assert calibration.robot_id is None
    assert calibration.head_device_id is None


@pytest.mark.parametrize("distance_mm", [80, 150, 400, 1000, 1900])
@pytest.mark.parametrize("yaw_deg", [0, 1, 10, 30, 44])
def test_front_facing_planar_pose_at_expected_distances(monkeypatch, distance_mm, yaw_deg):
    """Real OpenCV PnP on ideal projected corners, not a hardware trial."""
    cv2 = pytest.importorskip("cv2", reason="dock vision tests require the optional vision extra")
    import numpy as np

    camera = DockCameraCalibration(410, 410, 320, 240, 60, 12)
    square = np.array([[-30., 30., 0.], [30., 30., 0.],
                       [30., -30., 0.], [-30., -30., 0.]])
    intrinsics = np.array([[410., 0, 320], [0, 410., 240], [0, 0, 1]])
    yaw = math.radians(yaw_deg)
    rotation = np.array([[math.cos(yaw), 0, math.sin(yaw)], [0, 1, 0],
                         [-math.sin(yaw), 0, math.cos(yaw)]]) @ np.diag([1., -1., -1.])
    corners, _ = cv2.projectPoints(
        square, cv2.Rodrigues(rotation)[0], np.array([0., 0., float(distance_mm)]),
        intrinsics, np.zeros(5),
    )

    class Detector:
        def __init__(self, dictionary):
            pass

        def detectMarkers(self, frame):
            return [corners.astype(np.float32).reshape(1, 4, 2)], np.array([[12]]), []

    monkeypatch.setattr(cv2.aruco, "ArucoDetector", Detector)
    ok, jpeg = cv2.imencode(".jpg", np.zeros((480, 640), dtype=np.uint8))
    assert ok
    pose = detect_apriltag(jpeg.tobytes(), camera, captured_at=5)
    assert pose is not None
    assert abs(pose.x_mm) < 1.0
    assert abs(pose.y_mm) < 1.0
    assert abs(pose.z_mm - distance_mm) < 1.0
    assert pose.reprojection_error_px <= 3.0


@pytest.mark.parametrize("angle_deg", [0, 110])
def test_accurate_back_facing_or_overtilted_pose_does_not_retry(monkeypatch, angle_deg):
    """A valid fit outside the existing normal gate cannot be rescued."""
    cv2 = pytest.importorskip("cv2", reason="dock vision tests require the optional vision extra")
    import numpy as np

    camera = DockCameraCalibration(410, 410, 320, 240, 60, 12)
    square = np.array([[-30., 30., 0.], [30., 30., 0.],
                       [30., -30., 0.], [-30., -30., 0.]])
    intrinsics = np.array([[410., 0, 320], [0, 410., 240], [0, 0, 1]])
    rvec = np.array([[math.radians(angle_deg)], [0.], [0.]])
    tvec = np.array([[0.], [0.], [400.]])
    corners, _ = cv2.projectPoints(square, rvec, tvec, intrinsics, np.zeros(5))

    class Detector:
        def __init__(self, dictionary):
            pass

        def detectMarkers(self, frame):
            return [corners.astype(np.float32).reshape(1, 4, 2)], np.array([[12]]), []

    methods = []

    def solve(*args, flags):
        methods.append(flags)
        return True, rvec, tvec

    monkeypatch.setattr(cv2.aruco, "ArucoDetector", Detector)
    monkeypatch.setattr(cv2, "solvePnP", solve)
    ok, jpeg = cv2.imencode(".jpg", np.zeros((480, 640), dtype=np.uint8))
    assert ok
    assert detect_apriltag(jpeg.tobytes(), camera, captured_at=5) is None
    assert methods == [cv2.SOLVEPNP_IPPE_SQUARE]
