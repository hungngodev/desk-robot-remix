# Reused OpenCV AprilTag observation for a future real dock

**Not a working automatic charging dock and never an alternative movement authority.**

The repo already has an optional `vision` dependency with OpenCV. New
`code/laptop/src/desk_robot/dock_vision.py` reuses OpenCV's existing
`aruco.ArucoDetector` with `DICT_APRILTAG_36h11` and its
`solvePnP(..., SOLVEPNP_IPPE_SQUARE)` rather than implementing a new marker
detector. It accepts a camera calibration from the real XIAO Sense and a
measured printed marker side length. It rejects missing, duplicated, stale,
implausible or high reprojection error poses.

`assess_dock` produces only `hold`, `align`, or `approach` **diagnostic
phases**. It never returns a drive command, grants a permit, charges a battery
or bypasses the WROOM's four downward sensors. This is intentional. The physical
dock needs measured camera intrinsics, marker mounting, final face/contact
detection, anti-short charging circuit and a verified current-rated power path,
none of which the repository currently has.

Reuse source:
https://docs.opencv.org/4.x/d5/dae/tutorial_aruco_detection.html

OpenCV library license: Apache 2.0. Code here is a small integration adapter,
not copied OpenCV code. The existing `vision` optional install supplies cv2.

Run pure unit tests with `pytest tests/test_dock_vision.py`. Detecting real
tags requires the optional OpenCV dependency and a real calibrated JPEG.
