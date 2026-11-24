# Sustained boost input qualification, November 12, 2026

## Source level decision

The one cell power preflight already computes a conservative continuous battery input requirement, but previously accepted a candidate from peak boost input, continuous 5 V output, and protected cell ratings alone. A peak switch current rating is not a continuous input thermal rating. This run adds an independent optional `boost_continuous_input_a` and requires it before a candidate can be marked sufficient on paper. Missing data yields null, inadequate sustained input rating yields false, and no result grants physical qualification.

## Upstream references and reuse boundary

Texas Instruments TPS61088: https://www.ti.com/product/TPS61088 . The advertised 10 A is switch current capability, not an independently qualified continuous battery input rating for the assembled board. Pololu S13V30F5 documentation: https://www.pololu.com/product/4082 . Continuous achievable current depends on input voltage, thermal conditions and load; its published 5 V output graphs are not automatically equivalent to a 3 V cell input current rating. Use manufacturer board thermal curves or bench measurements at worst case cell voltage. Neither vendor's PCB or firmware has been copied; the integration uses the existing original arithmetic only, so no new third party source license is introduced.

## Test boundary and next actions

Source commits 072b005 and ba4cc16b add the gate and deterministic missing, insufficient, boundary and invalid input regressions in the existing test file. These tests were committed but NOT executed in this run. Run `python -m pytest code/tests/test_power_preflight.py -q` against current branch and record exact blob identities and exit code. Do not treat these calculations as measured motor/servo current, boost thermal acceptance, protected cell discharge safety or a verified docking charger. Before selecting a board, qualify actual continuous and transient loads, brownout, regulator thermal behavior, cell protection, contact isolation and charge power path independently.

## EXP-063: independent inductor saturation and thermal qualification (November 24)

**HOLD: not measured, no converter approved.** The existing `size_5v_supply` in
`code/scripts/power_preflight.py` computes load-equivalent average input
current with reserve. Its `boost_max_input_a` comparison does not evaluate
cycle-by-cycle switch or inductor peak current. Keep that sizing result
separate from magnetics qualification; do not enter a switch-current-limit
marketing number as an assembled board input rating.

For a conventional continuous-conduction boost stage, TI TPS61088 Rev D,
section 8.2.2.5, equations 8–10
(https://www.ti.com/lit/ds/symlink/tps61088.pdf) gives the following screen:

```
I_dc = Vout * Iout / (Vin * eta)
I_ripple_pp = Vin * (Vout - Vin) / (Vout * L_min * f_sw_min)
I_peak = I_dc + I_ripple_pp / 2
required_Isat = 1.30 * I_peak_upper_bound
```

Use the maximum required simultaneous output load and output voltage, lower
efficiency bound, lowest effective inductance including tolerance, bias and
temperature, and minimum switching frequency at each operating point.
For the fixed 5 V ideal boost ripple equation, ripple decreases from 3.0 V
through 4.2 V; do not assume this proves the worst actual operating point
when efficiency, frequency, control mode or effective inductance changes.
For a buck-boost module use its own controller equations and measured
waveforms, including mode transitions; the Pololu S13V30F5 is a buck-boost,
not the TPS61088 reference circuit. The 30% reserve is a project requirement,
not a claimed TI or Pololu specification.

Acceptance requires the exact fitted inductor's documented minimum
saturation current at worst operating temperature to be at least 1.30
times the upper-bound instantaneous peak current across the entire 3.0–4.2 V
battery range. Include instrument uncertainty, start-up, load steps and
current-limit behavior. Also check that the minimum controller current limit
supports normal operation and the inductor saturation rating exceeds the
maximum possible protection current including tolerances and overshoot.
Check inductor RMS/temperature-rise rating, DCR loss, switch and PCB thermal
limits independently. A room-temperature output-current graph, protection
shutdown or average INA226 reading cannot establish any of these.

Evidence to collect in the existing charging-design and verification ledger:
exact regulator PCB revision and controller, fitted inductor part number and
manufacturer datasheet revision (including definition of saturation and
temperature derating), current-limit setting and tolerances, measured
inductance/frequency and efficiency bounds, calibrated current waveform and
peak uncertainty, ambient and stabilized enclosure/inductor/controller
temperatures, 5 V ripple/droop and sustained load duration. Use a protected,
current-limited isolated bench setup; no energized dock or free-moving robot.
Sweep actual converter input over 3.0–4.2 V under sustained and transient
representative loads, including at least 3.0, 3.3, 3.6, 3.9 and 4.2 V and
any observed intermediate maxima/control-mode transitions. Record raw scope
traces and component/board identity; endpoints alone are insufficient.
Qualify the separate docked SYS range independently if the final architecture
uses it. No unsafe fault injection on an unqualified lithium pack.

### Checkpoint

At reviewed source revision `32b6c957ba5b74f7becf35aff694e949efd05d6e`,
`docs/hardware/full-feature-plan.json` lists `boost_5v_candidate` as unresolved
and `physical_trial_count=0`. The associated
`docs/hardware/charging-design-and-validation.md` and
`docs/records/verification.md` do not supply a fitted inductor identity,
temperature-derated saturation rating, or actual switching-current/thermal
trace. The margin is therefore UNKNOWN, not a measured failure or pass.
No source behavior, purchase authorization or physical receipt is changed by
this research-note update. Full Python/firmware verification is not executed
by this review; check exact commit CI independently. Next action: obtain
the exact candidate board schematic/BOM and inductor curves, then evaluate
the full voltage/load/temperature envelope and attach real scope and thermal
records before closing the physical gate.
