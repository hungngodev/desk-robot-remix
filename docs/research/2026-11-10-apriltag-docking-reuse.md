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


## Live one-robot Mac integration

The authenticated GET /v1/robots/{robot_id}/dock/observe endpoint now uses
the existing head camera snapshot and OpenCV AprilTag detector, but only after
a per-robot dock_calibration JSON sets measured=true and real camera intrinsics,
AprilTag marker size/ID and target distance.

A missing or unmeasured file returns HOLD without even opening a camera frame.
With a real JPEG, the endpoint returns camera-relative tag pose and qualitative
alignment phase. No drive command, motor arm, or live charge output is reachable
from this observer. Mac image receipt time is not claimed to equal exposure time.

Physical final contact approach, charging power electronics and actual printed
mechanical fit remain explicitly unverified.


## Operator permitted guarded approach, not automatic charge

The Mac Coordinator now has a dock_approach job, exposed only through
operator-authorized POST /v1/robots/{robot_id}/dock/approach.
The robot config must explicitly set dock_motion_qualified true after real
swept-path and track calibration, include measured dock_turn_sign and
dock_forward_sign, and have a physically measured dock_calibration file.
The job consumes an ordinary operator permit and uses the existing WROOM
arm, cliff guard, stop, keepalive and watchdog authority. It takes at most
16 short 100ms movement pulses, reobserving the marker after each.
Turns require all three read-only lateral/rear ToF readings to be fresh and
far enough; unknown directions cannot trigger a blind turn.

The approach intentionally stops for front obstacles and never moves to
the last unqualified centimeters or turns on charging contacts.
Because head snapshots currently expose a receipt timestamp rather than a
calibrated exposure timestamp, any autonomous approach needs real motion
and image latency qualification before setting dock_motion_qualified true.
No automatic battery low docking is claimed.
