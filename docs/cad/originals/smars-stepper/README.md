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

## Independent license cross-check (2026-11-13)

The original SMARS model is listed with **different terms across public distribution pages**: the [Thingiverse #2662828 source record](https://www.thingiverse.com/thing:2662828) is catalogued here as CC BY-NC-SA 4.0; a [Pinshape SMARS listing](https://pinshape.com/items/40386-smars-modular-robot) displays CC BY-ND; and a [Printables mirror](https://3dfinder.io/model/printables/1041789-smars-modular-robot) reports CC BY-NC-SA. These are not interchangeable grants, and a mirror or remix's CC BY label cannot establish permission to modify or commercially distribute the ancestor geometry. The Pinshape page was directly readable, but Thingiverse blocked a fresh independent fetch (HTTP 403), so the recorded original license remains subject to creator confirmation. **Do not incorporate modified SMARS-derived meshes into a commercial five-robot product or distribute the remixed CAD until the specific file provenance and authorized grant are confirmed.** Preserve the saved unmodified source files and hashes. The independently written mount adapters can be designed from measured component interfaces without copying restricted geometry; they still need physical fit and strength testing. No legal clearance, commercial license or assembly readiness is claimed.

## Independently licensed chassis fallback research (2026-11-13)

If creator permission for the SMARS ancestor cannot be established, do **not** assume the existing stepper meshes can be relicensed by changing the attribution file. An alternative with a directly visible permissive license is [UKMARS ukmarsbot](https://github.com/ukmars/ukmarsbot), whose repository displays MIT and provides mechanical CAD, motor mounts, electronic CAD and assembly references. Its [mechanical directory](https://github.com/ukmars/ukmarsbot/tree/master/mechanical) and [LICENSE](https://github.com/ukmars/ukmarsbot/blob/master/LICENSE) are the primary review points. The published robot uses **N20 geared DC motors and wheels**, not the owned 28BYJ-48 steppers, ULN2003 boards or SMARS tracks. Thus it is an independently licensed **design reference**, not a drop-in replacement, and converting it would require measured new motor, wheel, cliff-sensor, lift and dock interfaces. Its documented regulated/protected battery guidance is not an approved charging circuit for this robot.

Two tempting alternatives are explicitly rejected for the current product: [Bot-Chassis](https://github.com/bjepson/Bot-Chassis) publishes editable OpenSCAD but no visible license grant in the repository listing, and uses servos plus a caster; [Open Decabot](https://github.com/triwaca/openDecabot) is reported as CC BY-NC, with differing README terms, so it does not resolve commercial redistribution. These sources are **not** imported, copied or substituted for the existing drivetrain. The next mechanical integration experiment is to record actual motor shaft, mount, track, lift and dock envelope dimensions and compare a fully licensed candidate's native CAD before making any adapter. No geometry was changed or physically checked in this research pass.
