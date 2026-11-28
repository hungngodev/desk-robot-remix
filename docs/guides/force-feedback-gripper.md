# Gripper force feedback integration

The original Bluino gripper and SMARS forklift geometry remain unchanged. The first FSR402 belongs to belly squeeze and ADS1115 channel zero; the second belongs under the claw jaw and ADS1115 channel one.

The current Mac pickup implementation now closes the gripper in bounded small servo steps while reading verified ADS1115 electrical samples. It establishes an unloaded baseline, demands two consecutive contact detections, rechecks the local WROOM floor guard before each step, and refuses missing, stale or excessive feedback. The camera still verifies lift, hold and placement.

The existing measured camera calibration JSON supports these additional fields, initially unset:

    "grip_force_delta_raw": null,
    "grip_force_limit_raw": null,
    "grip_force_sign": 1,
    "grip_step_deg": 4

With no measured thresholds, real hardware pickup is intentionally blocked. Use the [jaw calibration helper](jaw-calibration-helper.md) to collect unloaded, representative contact and operator-approved upper-pressure samples. The Mac schema accepts contact deltas of 50 to 20000, ceilings of 100 to 30000 strictly above contact, polarity of +1 or -1, and steps of 1 to 4 degrees. These are validation bounds, not recommended physical thresholds. Separately qualify the mounted WROOM baseline, polarity, endpoints and exclusive closing ceiling; a Mac JSON candidate does not configure firmware. These are relative ADC values, not calibrated Newtons. No premature physical grasp success is claimed.


## Distinct ADC sample protection

Actual WROOM ADS1115 channel one conversions now carry a monotonic jaw_sample_seq counter into the read-only aux JSON field jaw_seq. Mac force guided grasp requires a new sequence number for the second unloaded baseline and for each post movement contact confirmation. Repeated HTTP polling of one sensor frame can no longer fabricate two physical contacts. Sensor driver and Mac validation reject stale, missing or malformed sequence numbers. The Mac waits 180 ms after a closing command, then polls for a distinct same-boot conversion within a 450 ms deadline (75 ms poll interval, at most six attempts). Nominal multiplexed acquisition can take about 336 ms; 180 ms alone does not authorize another pulse. Contact confirmation uses two distinct readings at the same commanded angle, with a 150 ms no-motion dwell and another health check. A sample aged 500 ms or more, including transport delay, is not fresh. At the calibrated ceiling or above, closure fails; contact is accepted only below that ceiling. This is still not a measured grip strength in Newtons.

## Hold evidence after contact

Hardware pickup refreshes the same robot and WROOM boot jaw sequence before lifting, after the lift, during raised-jaw visual verification, and before release. The first distinct fresh sample below the calibrated contact threshold invalidates the tactile grasp and fails the pickup job with `object_lost`; stale, contradictory or missing feedback instead leaves the hold unverified. No automatic regrasp or new motion is authorized. The read-only latest-pickup tool reports the loss as a historical job observation, not proof of a visible dropped object. This is checkpoint sampling, not continuous physical drop detection or qualified grip force.
