# Rounded head cases — source/fit audit

User chose a rounder existing head instead of the boxy EVA case on2026-11-03.
Retain tracked locomotion/front lift-claw and identical cores; change only the
head source plus small integration parts. Source claims below are not fit proof.

| Candidate | Download/license evidence | Decision |
| --- | --- | --- |
| [Sparky by Siddhartha Lahiri](https://github.com/slahiri/sparky/releases/tag/v0.1.0) | Actual STL ZIP, individual STLs and source. Explicit hardware CC BY-SA 4 in [LICENSE.md](https://github.com/slahiri/sparky/blob/91e3784be60b76d30942f2a487752389c7b05872/LICENSE.md). Saved unchanged with hashes. | Leading fit-check candidate. Original v0.1.0 shell approximately56×52×54mm, rounded8mm corners. Author explicitly says not test-printed/estimated;0.96 OLED insert, Sense mount/camera/mic/speaker/retention checks remain. |
| [Tiny Engineer by Krzysztof Jamroz](https://github.com/jamro/tiny-engineer/tree/aefc852a894174604a1e350bf9bc04c04f28ec80/3d_models) | Actual Head/Hat STL and native Fusion source. [Hardware scope](https://github.com/jamro/tiny-engineer/blob/aefc852a894174604a1e350bf9bc04c04f28ec80/LICENSING.md) explicitly CERN-OHL-S2; software MIT does not cover CAD. Saved Head/Hat/license/notice unchanged. | Alternative only. Intended0.91-inch Waveshare/servo housing; no camera or Sense/audio fit proven. |
| [TN24 creator article](https://www.hackster.io/tech_nickk/tn-24-v2-0-cute-desktop-companion-robot-44a472) | Article describes Sense/0.96 OLED and printed enclosure. Linked[tech-nickk/TN24](https://github.com/tech-nickk/TN24) contained README/sketch/expressions, no CAD or license file in checked tree. | A photographed shell is insufficient: no usable print download established. |
| [Compagnon309](https://makerworld.com/en/models/2109424-compagnon-309-build-your-expressive-robot) | Primary page inaccessible. Secondary catalog says PRIVATE-USE; source remix permission/dimensions not verified. | Do not select from third-party pictures/labels alone. |
| [Mochi housing](https://makerworld.com/en/models/1844353-the-mochi-housing-and-inner-frame-dasai-mochi) | Primary page inaccessible; secondary catalog leaves modification/license unstated. | No verified downloadable licensed source for this remix yet. |

For Sparky do **not** use current-main/v0.2 dimensions with v0.1 STL. The current
main config is64.4 × 56.6 mm and shell top76mm; the downloaded v0.1 has different
geometry. The v0.1 export places each part on its own print plane. Saved source
commit is`91e3784be60b76d30942f2a487752389c7b05872`; source config explicitly usesmm.

The downloaded archive contains shell, collar, rack, battery base and lid. Our
preview uses only the unmodified shell and does not adopt a LiPo battery circuit
or silently require all 12 magnet pairs. Any exact retainer must be added to the
priced BOM. No new hardware purchase, CAD deformation, slicing or fit test occurred.
