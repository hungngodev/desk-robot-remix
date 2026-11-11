# Gripper force feedback integration

The original Bluino gripper and SMARS forklift geometry remain unchanged. The first FSR402 belongs to belly squeeze and ADS1115 channel zero; the second belongs under the claw jaw and ADS1115 channel one.

The current Mac pickup implementation now closes the gripper in bounded small servo steps while reading verified ADS1115 electrical samples. It establishes an unloaded baseline, demands two consecutive contact detections, rechecks the local WROOM floor guard before each step, and refuses missing, stale or excessive feedback. The camera still verifies lift, hold and placement.

The existing measured camera calibration JSON supports these additional fields, initially unset:

    "grip_force_delta_raw": null,
    "grip_force_limit_raw": null,
    "grip_force_sign": 1,
    "grip_step_deg": 4

With no measured thresholds, real hardware pickup is intentionally blocked. The user only needs to read the raw ADS1115 channel 1 values at open jaw and with a representative object, then record first contact threshold, ceiling and polarity. These are relative ADC values, not calibrated Newtons. No premature physical grasp success is claimed.


## Distinct ADC sample protection

Actual WROOM ADS1115 channel one conversions now carry a monotonic jaw_sample_seq counter into the read-only aux JSON field jaw_seq. Mac force guided grasp requires a new sequence number for the second unloaded baseline and for each post movement contact confirmation. Repeated HTTP polling of one sensor frame can no longer fabricate two physical contacts. Sensor driver and Mac validation reject stale, missing or malformed sequence numbers. The jaw closes more slowly at approximately 180ms between commands so the multiplexed ADS1115 has time to produce a new conversion. This is still not a measured grip strength in Newtons.
