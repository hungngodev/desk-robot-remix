# November 13: dock camera distortion and AprilTag reuse boundary

Owner: Robot Open Source Research. Starting canonical PR #17 head `85e0f5eb612b6a6c2a66a6b7a2bd771cabca5541`; 51 issue comments and 51 combined timeline entries, no submitted reviews or review threads. Research and source consistency only, no executed tests or physical camera measurements.

## Current implementation and unresolved geometric assumption

`code/laptop/src/desk_robot/dock_vision.py` already uses OpenCV `cv2.aruco.DICT_APRILTAG_36h11` and `SOLVEPNP_IPPE_SQUARE` to produce a read-only pose. `dock_runtime.py` requires a declared measured calibration, bounds JPEGs, serializes native detector calls and never authorizes motor or charger power. Preserve those owners. The decoder and pose code are not a reason to install a second AprilTag service.

**Specific gap to qualify:** `DockCameraCalibration` records only fx/fy/cx/cy, tag side and ID. `detect_apriltag` hardcodes `distortion = np.zeros((5, 1))` and uses raw JPEG corner pixels. A measured focal length and center do not establish zero lens distortion. On the actual XIAO S3 Sense camera, off-axis tag corners could produce biased x/z pose even when reprojection error against the *incorrect* zero-distortion model is small. This is a geometric qualification concern, not a demonstrated physical defect. The current code never authorizes movement, so preserve its fail-closed authority boundary.

## Reuse comparison and licenses

* [OpenCV ArUco detection and pose guide](https://docs.opencv.org/4.x/d5/dae/tutorial_aruco_detection.html): already selected; provides the existing dictionary and IPPE square PnP. Prefer using the existing OpenCV distortion coefficients and camera calibration workflow, not another detector.
* [AprilRobotics AprilTag 3](https://github.com/AprilRobotics/apriltag): BSD 2-Clause C implementation, actively maintained upstream, recommends tagStandard41h12 for many new uses; changing family now would invalidate the existing 36h11 marker ID, print and calibration contract. Do not silently switch.
* [Pupil Labs AprilTag bindings](https://github.com/pupil-labs/apriltags): MIT Python wrapper around AprilTag 3, prebuilt wheels, but would introduce a second native detector and dependency for no proven advantage. No source copied.

## Smallest proposed implementation and verification

Keep OpenCV and the existing dock pose owner. First capture a real XIAO camera checkerboard calibration at the actual JPEG resolution, measure distortion coefficients and verify reprojection error across center and edges. Then extend the existing calibration schema to include finite, bounded measured coefficients and pass them to `cv2.solvePnP` and `cv2.projectPoints`, or explicitly require a verified rectified image pipeline. Do not silently default missing coefficients to zero for a new physical qualification. Preserve compatibility only for read-only diagnostics until the real measured calibration is installed.

Add deterministic `code/tests/test_dock_vision.py` cases using synthetic distorted projected tag corners: verify nonzero coefficients recover expected pose, missing/unqualified distortion fails closed for any future approach permit, wrong tag ID and duplicate IDs hold, and no observation grants motor/charging authority. Then run the exact current checkout tests and an actual camera geometry trial. This research is not approval of docking or charging. Existing WROOM local cliff, terminal IR, bumper and dock contact fences remain mandatory.

Next owner: dock vision implementation and independent QA. Do not duplicate the November 13 Nav2 staged recovery comparison; the new issue is camera optical geometry and calibration provenance.
