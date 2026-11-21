# Fast physical force pad calibration after assembly

The Mac's `guarded_grasp()` logic already uses the real jaw ADS1115 FSR (channel 1), 4 degree stepped closure, a fresh conversion sequence after each step and a separate WROOM local guard. The final two jaw thresholds and sign must be measured on the robot; a raw ADC value cannot reveal mechanical force in newtons.

The WROOM now caps jaw movement to four commanded degrees for each distinct, fresh ADS1115 channel 1 conversion and cancels a pending target on sensor replay. The Mac calibration and guarded grasp enforce `grip_step_deg` at **1 through 4 degrees**, not the older 10-degree ceiling, so commanded increments cannot outrun firmware permission. The Mac waits 180 ms for the next ADC before another step. These are source limits, not measured servo position or jaw force.

The new `code/scripts/calibrate_jaw_fsr.py` is an **interactive operator-only no-motion tool**. It polls the existing authenticated Mac `/v1/robots/robot-01/aux` endpoint for three sets of *eight different hardware conversion IDs*: (1) unloaded, (2) gentle contact on the representative object, (3) stronger but non-damaging hand pressure. It rejects high noise, duplicate readings, weak contact or narrow threshold margins. It proposes `grip_force_delta_raw`, `grip_force_limit_raw`, `grip_force_sign` and `grip_step_deg`.

Example after setting the actual private operator token in your shell:

    cd code
    uv run python scripts/calibrate_jaw_fsr.py --calibration config/calibration.example.json --robot robot-01

It creates a **new** `.jaw_candidate.json` file, never overwrites the original, and always leaves `measured=false`. Review results and complete camera homography, actual horn travel and lifting tests before changing that flag. No code can prove safe squeezing of candy, keys or fingers without the physical jaw and force response.

The tool **does not move the servo**, open the charger or grant motor permissions. The operator keeps the mechanism stationary while sampling the pressure pad. Source is original code reusing the repo's existing force ADC validator; no extra third-party driver is added.
