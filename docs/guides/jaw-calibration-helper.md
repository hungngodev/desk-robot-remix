# Fast physical force pad calibration after assembly

The Mac's `guarded_grasp()` logic already uses the real jaw ADS1115 FSR (channel 1), 4 degree stepped closure, a fresh conversion sequence after each step and a separate WROOM local guard. The final two jaw thresholds and sign must be measured on the robot; a raw ADC value cannot reveal mechanical force in newtons.

The WROOM now caps jaw movement to four commanded degrees for each distinct, fresh ADS1115 channel 1 conversion and cancels a pending target on sensor replay. The Mac calibration and guarded grasp enforce `grip_step_deg` at **1 through 4 degrees**, not the older 10-degree ceiling, so commanded increments cannot outrun firmware permission. The Mac waits 180 ms for the next ADC before another step. These are source limits, not measured servo position or jaw force.

The new `code/scripts/calibrate_jaw_fsr.py` is an **interactive operator-only no-motion tool**. It polls the existing authenticated Mac `/v1/robots/robot-01/aux` endpoint for three sets of *eight different hardware conversion IDs*: (1) unloaded, (2) gentle contact on the representative object, (3) stronger but non-damaging hand pressure. It rejects high noise, duplicate readings, weak contact or narrow threshold margins. It proposes `grip_force_delta_raw`, `grip_force_limit_raw`, `grip_force_sign` and `grip_step_deg`.

After [Local AI setup](local-ai.md), start the Mac coordinator and confirm the configured robot ID. Its default API port is 8765, not the helper's historical 8008 default. Use the generated private `config/local.env` and coordinator operator token (`DESK_ROBOT_API_TOKEN` by default, not the model tool token). Keep the wheels and servos physically unpowered during hand-applied force sampling; logic and ADC power must remain stable.

From the repository root, enter `code/`. Use your existing private per-unit calibration JSON. If starting with the unmeasured example, copy it to `config/local.calibration.json` without overwriting any prior measurements:

```bash
cd code
cp -n config/calibration.example.json config/local.calibration.json
uv run --no-sync --env-file config/local.env python scripts/calibrate_jaw_fsr.py \
  --url http://127.0.0.1:8765 --token-env DESK_ROBOT_API_TOKEN \
  --calibration config/local.calibration.json --robot robot-01
```

If you changed the coordinator port or its token environment name, use those actual values. The token file must be private; do not put token values in commands or commit them. The script requires a single nonzero WROOM boot identity across all three phases, fresh valid jaw samples and distinct forward conversion sequences; a reboot or clipped ADC requires a new trial.

It creates a **new** `config/local.calibration.jaw_candidate.json` file (ignored by Git), never overwrites the original or an earlier candidate, and always leaves `measured=false`. Review results and complete camera homography, actual horn travel and lifting tests before changing that flag. No code can prove safe squeezing of candy, keys or fingers without the physical jaw and force response.

The tool **does not move the servo**, open the charger or grant motor permissions. The operator keeps the mechanism stationary while sampling the pressure pad. Source is original code reusing the repo's existing force ADC validator; no extra third-party driver is added.
