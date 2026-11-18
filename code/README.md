# Implementation

- `firmware/` contains the robot’s head and body software.
- `laptop/` contains the Mac coordinator and speech-server integration.
- `config/` and `scripts/` contain settings and build or validation tools.
- `tests/` contains automated checks for the Mac software, simulator and
  budget and trial tools. Firmware-specific checks live with the firmware.
- `upstream/` holds local copies of the pinned source projects.

Run development commands from this folder. From the repository root, use
`cd code`. Run the main test suite with `uv run --extra dev pytest -q`.
See the [firmware build guide](../docs/guides/build.md) for board-specific steps.

Read the [handbook](../docs/README.md) for the build order, parts and
[physical trial records](../docs/records/verification.md).
