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
With a real JPEG, the endpoint returns the raw camera-relative tag pose.
When the actual lens-to-chassis lateral offset and yaw have been measured, its
qualitative alignment phase uses the corrected chassis-centerline lateral
coordinate and reports that coordinate separately; a centered lens alone need
not mean aligned tracks. Without mount measurements, the camera-only
observation remains provisional. No drive command, motor arm, or live charge
output is reachable from this observer. Mac image receipt time is not claimed to equal exposure time.

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


**Dock MJPEG freshness guard:** When the actual `HttpHead` supports
`snapshot_for_dock`, both guarded approach and the read-only observer
reuse the authenticated continuous MJPEG transport and require a frame
received by the Mac within the preceding **200 ms**. A disconnected
stream cannot silently fall back to a legacy `/api/camera.jpg` call,
including while the capture lock is pending. Ordinary conversational
snapshot semantics are unchanged. The stream transport returns the original JPEG and Mac receipt timestamp as one
atomic pair; both dock consumers feed that original timestamp to AprilTag
pose freshness assessment rather than resetting the clock after awaiting a
camera lock or native detector. Stale, malformed, future or nonfinite receipt
timestamps fail closed before motion planning. This still measures Mac
**receipt** age, not the original camera sensor exposure timestamp or
end-to-end latency.
No millimeter-scale docking movement or real charging is qualified until
camera exposure latency, physical marker placement, optical standoff,
local WROOM safety and stopped-distance trials are measured.
