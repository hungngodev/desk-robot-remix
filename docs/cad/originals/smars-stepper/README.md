# Original SMARS stepper remix

Source: [SMARS - 28BYJ-48 #2778904](https://www.thingiverse.com/thing:2778904/files), **unclejeff**, published 2018-02-01. Checked 2026-11-03. The live source labels this **Work in Progress** and displays [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

Saved unmodified downloads:

- [SMARS_2BJY8-Chassis.stl](SMARS_2BJY8-Chassis.stl), source update 2018-02-04.
- [SMARS_28BYJ-48-RearWheel.stl](SMARS_28BYJ-48-RearWheel.stl), source update 2018-02-02.

[source.json](source.json) records bytes, SHA256 hashes, binary triangle counts and coordinate bounds. The configured browser downloaded both after plain HTTP retrieval returned403. Filenames retain the source spelling, including `2BJY8`.

The creator describes a slow 28BYJ drivetrain, original SMARS tracks, M4 motor mounts and M3 slave-wheel mounts. Screw lengths and complete print quantities are not specified. The source reports fixing shaft-hole/non-manifold errors; our checks establish binary structure only.

The [wtlx code reference](https://github.com/wtlx/smars-28byj-48/tree/caa117f86bd6048e42b9b5085cbb7c58184e9df2) links this exact design but contains only two Arduino sketches and a README, **no CAD or LICENSE**. It is an educational reference, not licensed code copied into our firmware.

## Assembly qualification still required

These files establish an existing stepper chassis/wheel option without designing a new drivetrain. They do **not** establish that the saved Bluino lift, gripper, EVA head, power bank and four corner sensors fit together. Compare actual mounting interfaces and track clearance before printing the full assembly. The older N20 screwless chassis is a separate variant: do not mix its wheel/shaft assumptions with this stepper chassis. Inspect the original track and slave-wheel choices against this source and use only matching parts.

STL stores no unit metadata. The chassis spans roughly 58.0 × 86.2 × 41.6 source units; the wheel spans21.0 × 32.5 × 32.5. Large coordinate offsets and wheel orientation remain unchanged. Confirm units/orientation from component dimensions and original assembly. No topology repair, slicing, physical fit, loaded turning, lift clearance or anti-fall qualification has occurred. No live Fusion/Blender scene was touched.

## Preserve the source chain

The remix page identifies [original SMARS #2662828](https://www.thingiverse.com/thing:2662828), **tristomietitoredeituit**, as its ancestor. Our previously collected original source records CC BY-NC-SA4.0. Preserve both attributions and the recorded ancestor restrictions; the displayed CC BY remix label does not by itself resolve that difference. Keep this personal prototype source collection separate from any future redistribution until the source-chain terms are checked. No commercial permission is claimed.
