# Rounded head candidate — Sparky v0.1.0

Author: **Sparky by Siddhartha Lahiri**. [Original release](https://github.com/slahiri/sparky/releases/tag/v0.1.0),
tag commit`91e3784be60b76d30942f2a487752389c7b05872`.
Hardware/CAD:[CC BY-SA 4.0](LICENSE.md). Preserve attribution, source link and
share-alike terms on derived files. Firmware is separately MIT; none is copied.

The unmodified release ZIP and its five ASCII STLs are saved here. [source.json](source.json)
records original URLs, bytes, triangles, bounds and SHA256 hashes. The saved
`config.scad` specifies millimeters. These bounds are the **older v0.1.0 files**,
not main/v0.2's64.4×56.6×76mm configuration.

| Original file | Size, approximately mm |
| --- | --- |
| `sparky_shell.stl` | 55.97×51.97×53.98 |
| `sparky_collar.stl` | 56×52×6 |
| `sparky_rack.stl` | 47.2×43.2×53 |
| `sparky_base.stl` | 56×52×12 |
| `sparky_lid.stl` | 51.4×47.4×4 |

The author explicitly calls this release **not test-printed; component sizes are
estimates**. It is a licensed downloadable candidate, not a proven fit. Only the
shell is used in our [layout study](../../concepts/2026-11-03-rounded/README.md).
All five parts have separate print-coordinate origins; they are not automatically
registered as one assembled body.

For our use: measure an insert for the owned 0.96-inch OLED in the source 1.3-inch
window; Sense/camera/audio mount and clearance; microphone path; camera aperture
and angle; small rover mount and retention. The front LED hole is not a verified
camera mount. Keep the original main shell shape; no whole-case scaling. The
source's battery base and raw-LiPo circuit are **not** our power-bank architecture,
and its full magnet set is not automatically in our BOM. A small retaining mount
must be designed and priced before the print manifest is final.

No geometry repaired, modified, sliced or physically verified. Read the
[product definition](../../../product-definition.md) before printing.
