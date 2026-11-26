# Third-party notices

The [root MIT license](LICENSE) covers original integration code only.
The authoritative source and reuse inventory is [docs/ATTRIBUTION.md](docs/ATTRIBUTION.md).
Do not apply the root MIT grant to upstream software, model weights, CAD,
fonts, or other assets.

- [Pinned upstream revisions](code/upstream-lock.json).
- [VerdureBuddyRover MIT](docs/licenses/VerdureBuddyRover-MIT.txt).
- [Xiaozhi device MIT](docs/licenses/xiaozhi-esp32-MIT.txt).
- [Xiaozhi server MIT](docs/licenses/xiaozhi-esp32-server-MIT.txt).
- Stackchan-agent: [MIT license](docs/licenses/Stackchan-agent-MIT.txt),
  [pinned upstream Behavior.hpp](https://github.com/botamochi6277/stackchan-agent/blob/bfb98fb8bdb4f8ecc4b7c1c4f9bc90ee5227e613/include/Behavior.hpp)
  and [adapted HSM with retained notice](code/firmware/head/overlay/stackchan_behavior.hpp).
- [Body firmware notices](code/firmware/body/THIRD_PARTY_NOTICES.md), including
  [Seeed PN532 BSD-3-Clause](docs/licenses/Seeed-PN532-BSD-3-Clause.txt).
- [Original CAD source records](docs/cad/originals/) and
  [mechanical remixes](docs/cad/remixes/README.md).

## Revision-specific distribution boundaries

- ESP-SR: the pinned Xiaozhi device manifest selects
  `espressif/esp-sr ==2.4.7`. The [version-specific ESPRESSIF MIT license](https://components.espressif.com/components/espressif/esp-sr/versions/2.4.7/license)
  restricts use to Espressif products; it is not unrestricted MIT.
  Retain the actual component notice with firmware distributions. Review the
  packaged models and [wake-word trademark restrictions](https://components.espressif.com/components/espressif/esp-sr/versions/2.4.7/readme)
  separately. The resolved component archive and model inventory have not
  been independently audited here; do not infer clearance for non-Espressif
  targets or commercial use of third-party wake words.
- Pololu VL53L0X: release `1.3.1` resolved to
  `9f3773cb48d4e4e844d689cfc529a06f96d1d264` at the November 25 audit.
  Its [exact upstream notice](https://github.com/pololu/vl53l0x-arduino/blob/9f3773cb48d4e4e844d689cfc529a06f96d1d264/LICENSE.txt)
  contains both Pololu MIT and STMicroelectronics BSD-3-Clause terms.
  The complete text is retained in the body firmware notices above.
- SMARS: [original chassis](docs/cad/originals/smars/source.json),
  [stepper remix](docs/cad/originals/smars-stepper/source.json) and
  [forklift](docs/cad/originals/forklift/source.json) retain recorded
  CC BY-NC-SA 4.0 terms or ancestry. These are separate mechanical assets,
  not MIT firmware; the repository as a whole is **not NC-free**.
  Commercial release remains on hold until rights are resolved or
  independently licensed replacement geometry is qualified.

Keep dependency and model notices from the exact distributed revisions.
Research references are not automatically incorporated dependencies.
Generated concept layouts retain upstream mesh provenance and are not
commercial manufacturing approval. The recorded SMARS noncommercial
share-alike ancestor terms and separate head-shell terms require review
before redistribution or commercial use, including mixed adaptations.

This index is not a complete release bill of materials or a substitute
for the actual license texts and component-specific attribution.
