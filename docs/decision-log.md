# Project decision log

Updated 2026-11-06. This records durable project decisions and superseded choices,
not a transcript. Earlier items are reconstructed from saved project checkpoints
and user instructions; dates below identify records, not invented message times.
Canonical current requirements: [product-definition.md](product-definition.md).
Sources and reuse boundaries: [source-map.md](source-map.md).

| Record | Decision / reason / supersession |
| --- | --- |
| Historical initial robot brief | Camera, screen, speech and real small-object pickup; reuse existing open designs, with small CAD edits only. Original CoreS3 all-in-one estimate was replaced by budget modular components |
| Saved2026-10-28/30 work | Project folder and preserved upstream/CAD sources, assembly/trial records and dual-controller boundary established. Current work preserves those originals |
| Saved2026-11-03 inventory correction | No spare S3 N8R8 was actually owned. Later Sense purchase is the active camera/mic head; WROOM remains body. Feather/USB-C breakout/continuous servo are spares, not mandatory integration |
| Five-core requirement | All five are equally equipped functional robots with different names/cosmetics; initial one-moving-at-a-time tests stage the full group goal |
| Owned actuator revision |5steppers+5ULN boards and roughly10MG90S prompted stepper-SMARS plus lift/grip. Do not force those parts if compatibility would demand major redesign; report the concrete alternative tradeoff first |
| Manipulation | Actual flat keys and wrapped candy; two servos remain lift+closing grip. A Cozmo cube/fork or extra head tilt cannot silently replace this |
| Voice | Ordinary speech must interrupt ongoing robot TTS in build one. A button, special phrase or muted microphone fails. Source inspection/AEC flag is not acoustic qualification |
| Appearance | Rounder head, then Fetch retro-TV, then Cozmo/Vector cues. Compare actual Cozmars head packaging first; unprinted Sparky remains fallback. AI pictures are not fitted CAD |
| Local compute | Shared M1Max/64GB Mac supplies speech/vision/reasoning; no new Pi/Pico/Uno. Local-first remains active; Google optional cloud is not silently enabled |
| Initiative | Notice camera events and choose activities without a voice prompt. Face/sound reflexes, visual attention, activity memory and task execution need separate timing/ownership |
| Motion session | Enable until user pauses/stops; supersedes recurring120/300s renewal proposal. Short per-drive deadlines/watchdog and fault/disconnect/restart cancellation remain |
| Edge sensing | Compact candidate4VL6180X down+1L0X front+mux replaces old5L0X. Concealed boards/open optical windows; local measured stops and surface qualification required |
| Power/budget | Matched rechargeable1S kit replaces required consumer-bank direction. Exact cell/charge/protection/5V output remains unselected. $50delivered prototype cap includes money already spent; no updated complete quote |
|2026-11-04 source audit | Preserve full supplied-source mapping, not just six chosen repos. Concrete stronger candidates: Google robotics agent observation/event components, HF local voice/vision engine, Reachy activity arbitration, Stackchan-agent reaction controller. These are reviewed candidates, not integrated features |
|2026-11-04 interaction request | Add head touch and six-axis tilt/shake/handling awareness. TTP223+LSM6DS3TR-C is proposed new baseline; evaluate owned equivalents when simpler. RGB/bumper/Hall/light extras remain optional; no visible laser selected |
|2026-11-04 owned-photo revision |18photos group into ten module types; preserve minimumone per type, not18units. BerryIMU (likely older V1) supersedes new prototype IMU procurement pending identity/readout/fit. LSM6 becomes conditional fallback. MAX9814 is spare analog mic, not speaker output; separate interface-unknown camera stays spare. Reed module supports optional magnet-accessory game; do not force all spares onboard or replace qualified edge sensing with PIR/reflective IR. Four fleet IMU equivalents remain unconfirmed if only one is available. [Evidence](hardware/photo-inventory-2026-11-04.md) |
|2026-11-05 speaker amplifier clarification | User reports a separate HiLetgo board marked `pam 84`, likely PAM8403; exact model/count unverified. A PAM8403 can drive a speaker from analog input. Keep it as a reuse candidate if a suitable DAC is available; MAX98357A remains the one-board I2S baseline. The photographed MAX9814 is microphone input. [Parts](hardware/parts.md) |
| 2026-11-06 new electronics | Adafruit AT42QT1010 #1374 replaces the proposed TTP223 purchase for robot one, pending shell and bench checks. IMG_3902 identifies the earlier HiLetgo board as HW-104 PAM8403. One board is visible and the bag says five. Use a suitable DAC for analog reuse or choose the direct I²S path. DRV8833 and FIT0774 are optional. IMG_3905 matches the earlier reed module type and does not raise its stock count. [Photo follow-up](hardware/photo-inventory-2026-11-04.md#2026-11-06-follow-up) |
| 2026-11-06 project layout | Keep the living handbook in `docs/` and implementation in `code/`. Keep automated tests with the implementation and physical trial sheets and past reports in `docs/records/`. The two [entry points](../README.md) replace the earlier scattered top-level folders. |
| Evidence boundary | No complete robot assembled/flashed/physically accepted. Current runtime foundations compile historically; actual ToF I/O/calibration and many behaviors remain unfinished. New notes do not change those evidence states |

## Continuing recording rule

Record meaningful decisions, rationale, source/terms and superseded choices in
these canonical documents; update inventory only from actual reports. Store
small, self-contained durable project knowledge in Cognee dataset
`desk-robot-remix`, with links back here. Source code symbols belong in the code
graph and personal cross-project preferences belong in authenticated Mem0, not
in a copied chat transcript. Never store credentials/raw captures or every
one-off status update. Verify memory writes and retrieval before claiming saved.
