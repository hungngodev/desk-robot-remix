import sys
from dataclasses import replace

import numpy as np
import pytest
from desk_robot.dock_vision import DockCameraCalibration
from desk_robot.spatial_projection import FloorProjectionCalibration, ProjectionError


def calibration(distortion=(0.1, -0.03, 0., 0., 0.)):
    lens = DockCameraCalibration(
        400, 400, 320, 240, 50, 4, distortion, 640, 480, 'OV5640', 0, 0,
    )
    return FloorProjectionCalibration(
        lens, 'sample-cal-1', 100, 0, 30, (0, 0, 640, 480),
        (-1000, 1000), (-1000, 1000), 10, measured=True,
    )


def project(cal, u=600, v=400, **overrides):
    args = dict(image_width=640, image_height=480, camera_sensor_pid='OV5640')
    return cal.project(u, v, **(args | overrides))


def test_nonconvergent_real_opencv_inverse_is_rejected():
    pytest.importorskip('cv2')
    with pytest.raises(ProjectionError, match='round trip'):
        project(calibration((-0.6, 0., 0., 0., 0.)))


@pytest.mark.parametrize('bad', [None, [], np.zeros((2, 1, 2)), np.array([[[np.nan, 0.]]])])
def test_malformed_native_undistortion_rejected(monkeypatch, bad):
    cv2 = pytest.importorskip('cv2')
    monkeypatch.setattr(cv2, 'undistortPoints', lambda *args: bad)
    with pytest.raises(ProjectionError, match='undistortion'):
        project(calibration())


def test_native_undistortion_exception_rejected(monkeypatch):
    cv2 = pytest.importorskip('cv2')

    def fail(*args):
        raise cv2.error('injected native failure')

    monkeypatch.setattr(cv2, 'undistortPoints', fail)
    with pytest.raises(ProjectionError, match='undistortion'):
        project(calibration())


def test_missing_cv2_only_blocks_nonzero_distortion(monkeypatch):
    monkeypatch.setitem(sys.modules, 'cv2', None)
    with pytest.raises(ProjectionError, match='vision extra'):
        project(calibration())
    assert project(calibration((0.,)*5), 320, 240).x_mm == pytest.approx(173.20508)


def test_huge_numbers_and_pid_type_rejected():
    cal = calibration()
    with pytest.raises(ProjectionError):
        project(cal, 10**1000, 240)
    with pytest.raises(ProjectionError):
        replace(cal, camera_height_mm=10**1000)
    with pytest.raises(ProjectionError):
        replace(cal, valid_forward_mm=(0, 10**1000))
    with pytest.raises(ProjectionError):
        project(cal, camera_sensor_pid=np.array(['OV5640']))


def test_valid_off_center_distortion_still_projects():
    pytest.importorskip('cv2')
    point = project(calibration())
    assert point.x_mm > 0
    assert point.y_mm < 0


@pytest.mark.parametrize('pid', [np.array(['OV5640']), np.str_('OV5640')])
def test_nested_lens_pid_must_be_plain_string(pid):
    cal = calibration((0.,) * 5)
    lens = replace(cal.lens, camera_sensor_pid=pid)
    with pytest.raises(ProjectionError, match='Lens and measured mount geometry'):
        replace(cal, lens=lens)


def test_nested_distortion_must_be_plain_immutable_tuple():
    class MutableCoefficients(tuple):
        pass

    cal = calibration()
    lens = replace(cal.lens, distortion_coeffs=MutableCoefficients(cal.lens.distortion_coeffs))
    with pytest.raises(ProjectionError, match='Lens and measured mount geometry'):
        replace(cal, lens=lens)
