# FETCH: appearance and assembly reference

Reviewed 2026-11-03 at the user's request. Project: **FETCH**, by **SECTOR 07 /
Austin Dutenhoeffer**.

- [Creator's Arduino Project Hub build article](https://projecthub.arduino.cc/sector_07/build-fetch-an-open-source-ai-robot-powered-by-arduino-uno-q-8092d1)
- [Creator's video: I Built My Own AI Computer Vision Robot](https://www.youtube.com/watch?v=51q_WmbnJtQ)
- [Official project cover photograph](https://projects.arduinocontent.cc/cover-images/3f4d8e9e-ac9b-4cde-b5cd-e4613d0b5186.png)

The build article was read in the browser. Actual video frames were inspected at
0:12 (assembled character), 1:05, 2:30 (CAD), 4:30 (open electronics panels),
6:05, 8:35 (front arms), 9:20 (assembled side) and 15:45 (outdoor demonstration).
This is a review of sampled design/build/demo sections, not a claim to have
watched every second or verified its performance.

## Direction for our existing robot

These are proposed adaptations to our appearance brief, not new manufactured
parts or measured dimensions.

| Observed visual idea | How to use it in our remix |
| --- | --- |
| Substantial light bezel surrounding a dark inset face | Give the owned OLED a deliberate, neat surround within the rounded Sparky candidate. Keep the actual screen size; our white monochrome display cannot reproduce Fetch's blue color. |
| Soft corners, large face and contrasting side surfaces | Keep a rounded, friendly head with charcoal accents above the low tracked body. Confirm the bank and lift fit before fixing overall proportions. |
| Distinct side antenna/ear shapes | Optional lightweight, removable **static** decorations or costume attachment details. Do not add ear servos; the two allocated positional servos remain lift + grip. |
| Clearly readable expressions | Large simple eyes, blinks, gaze pauses and listening/speaking states on the existing SSD1306. Shape/timing can convey personality without copying Fetch's graphics. |
| Recognizable character across different views | Keep a consistent head/face across five cores; use hats, accents and costumes for individual identities. Leave camera, microphone, speaker, antenna and sensor views clear. |
| Electronics accessible during assembly | Check whether existing shell access plus a small removable retainer/plate can provide service access. Do not rebuild Sparky into Fetch's folding structure. |

Recommended combination: **rounded existing head + Fetch-inspired inset face and
contrasting panels + existing tracked rover + front lifting claw**, with optional
static ears. This does not replace the current shell candidate, mechanisms,
electronics or $50 prototype cap. Do not enlarge a decorative head without
checking mass, stability, gripper sweep and sensor occlusion.

## Why the complete Fetch shell is not selected

The creator's article specifies a 3.5-inch display, UNO Q, hinged electronics
panels, TT drive motors and several arm/ear servos. Its internal mounts and
mechanisms are different from our small OLED, Sense/WROOM and stepper/lift core.
Treating that enclosure as a drop-in would conceal substantial mechanical work.

The public project archive was inspected in memory by the source-review worker:
it contains assembly/BOM/schematic documents, application and print ZIPs; print
entries include front/back outer shells, ears, inner panels, arms and drive parts.
No STEP/native CAD or separate LICENSE/NOTICE entry was found in that listing.
No archive, CAD, face artwork, code or voice asset was copied into this project.

The Project Hub page metadata identifies **CC BY-NC 4.0 or later**, linking to
[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/). Preserve that
provenance if actual assets are reused; do not label them MIT. Public download
availability and the title's open-source wording are not a substitute for terms.

Reviewed archive: [Fetch Project ZIP](https://projects.arduinocontent.cc/02dff572-34ed-4309-9154-54d89146a56f.zip),
6,664,583 bytes, SHA256
`477e2a4651a61bcca0624b1df7c4c5e572c935c200dd41054b9bbad81e40f831`.
This is an audit record, not a saved or executed dependency.
