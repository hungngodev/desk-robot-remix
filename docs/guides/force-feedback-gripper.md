# Gripper force feedback integration

The original Bluino gripper and SMARS forklift geometry remain unchanged. The first FSR402 belongs to belly squeeze and ADS1115 channel zero; the second belongs under the claw jaw and ADS1115 channel one.

The current Mac pickup implementation now closes the gripper in bounded small servo steps while reading verified ADS1115 electrical samples. It establishes an unloaded baseline, demands two consecutive contact detections, rechecks the local WROOM floor guard before each step, and refuses missing, stale or excessive feedback. The camera still verifies lift, hold and placement.

The existing measured camera calibration JSON supports these additional fields, initially unset:

    "grip_force_delta_raw": null,
    "grip_force_limit_raw": null,
    "grip_force_sign": 1,
    "grip_step_deg": 4

With no measured thresholds, real hardware pickup is intentionally blocked. The user only needs to read the raw ADS1115 channel 1 values at open jaw and with a representative object, then record first contact threshold, ceiling and polarity. These are relative ADC values, not calibrated Newtons. No premature physical grasp success is claimed.
