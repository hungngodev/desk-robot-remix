# Sustained boost input qualification, November 12, 2026

## Source level decision

The one cell power preflight already computes a conservative continuous battery input requirement, but previously accepted a candidate from peak boost input, continuous 5 V output, and protected cell ratings alone. A peak switch current rating is not a continuous input thermal rating. This run adds an independent optional `boost_continuous_input_a` and requires it before a candidate can be marked sufficient on paper. Missing data yields null, inadequate sustained input rating yields false, and no result grants physical qualification.

## Upstream references and reuse boundary

Texas Instruments TPS61088: https://www.ti.com/product/TPS61088 . The advertised 10 A is switch current capability, not an independently qualified continuous battery input rating for the assembled board. Pololu S13V30F5 documentation: https://www.pololu.com/product/4082 . Continuous achievable current depends on input voltage, thermal conditions and load; its published 5 V output graphs are not automatically equivalent to a 3 V cell input current rating. Use manufacturer board thermal curves or bench measurements at worst case cell voltage. Neither vendor's PCB or firmware has been copied; the integration uses the existing original arithmetic only, so no new third party source license is introduced.

## Test boundary and next actions

Source commits 072b005 and ba4cc16b add the gate and deterministic missing, insufficient, boundary and invalid input regressions in the existing test file. These tests were committed but NOT executed in this run. Run `python -m pytest code/tests/test_power_preflight.py -q` against current branch and record exact blob identities and exit code. Do not treat these calculations as measured motor/servo current, boost thermal acceptance, protected cell discharge safety or a verified docking charger. Before selecting a board, qualify actual continuous and transient loads, brownout, regulator thermal behavior, cell protection, contact isolation and charge power path independently.
