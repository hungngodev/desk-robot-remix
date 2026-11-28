#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
board=cores3
private=false
passthrough=()
while (($#)); do
  case "$1" in
    --board)
      if (($# < 2)); then echo "--board needs cores3, modular, sense or waveshare" >&2; exit 2; fi
      board="$2"; shift 2 ;;
    --private) private=true; shift ;;
    *) passthrough+=("$1"); shift ;;
  esac
done
case "$board" in
  cores3) variant=desk-robot-core-s3; build_copy=xiaozhi ;;
  modular) variant=desk-robot-modular-s3; build_copy=xiaozhi-modular ;;
  sense) variant=desk-robot-sense-s3; build_copy=xiaozhi-sense ;;
  waveshare) variant=desk-robot-waveshare-s3-cam; build_copy=xiaozhi-waveshare ;;
  *) echo "Unknown board: $board (choose cores3, modular, sense or waveshare)" >&2; exit 2 ;;
esac
build_root="firmware/head/build/$build_copy"
if [[ ! -f "$build_root/scripts/build.py" ]]; then
  echo "Missing $board build copy; run firmware/head/install_overlay.py --board $board first." >&2
  exit 1
fi
# Resolve the same component versions as the verified project-local lock.
if [[ ! -f "$build_root/dependencies.lock" ]]; then
  cp firmware/head/dependencies.lock "$build_root/dependencies.lock"
fi
if ! cmp -s firmware/head/dependencies.lock "$build_root/dependencies.lock"; then
  echo "Build dependency lock differs from firmware/head/dependencies.lock; preserve it and prepare a fresh pinned build copy." >&2
  exit 1
fi
tools_root="$project_root/../.tools"
if [[ ! -f "$tools_root/esp-idf/export.sh" ]]; then
  tools_root="$project_root/.tools"
fi
if [[ ! -x "$tools_root/sdk-bootstrap/bin/python" || ! -f "$tools_root/esp-idf/export.sh" ]]; then
  echo "Project-local ESP-IDF/Python environment missing; see docs/guides/build.md." >&2
  exit 1
fi
# Check the SDK before its export script or build can run.
if ! expected_idf="$("$tools_root/sdk-bootstrap/bin/python" -c 'import json; print(json.load(open("toolchain-lock.json"))["esp_idf"]["commit"])')" ||
   ! actual_idf="$(git -C "$tools_root/esp-idf" rev-parse HEAD)" ||
   [[ "$actual_idf" != "$expected_idf" ]]; then
  echo "ESP-IDF revision differs from toolchain-lock.json or cannot be verified; inspect the existing SDK checkout." >&2
  exit 1
fi
export IDF_TOOLS_PATH="$tools_root/idf-tools"
export PATH="$tools_root/sdk-bootstrap/bin:$PATH"
source "$tools_root/esp-idf/export.sh"
build_args=("desk-robot/$variant" --name "$variant" --language en-US)
if $private; then
  build_args+=(--config config.private.json --wake-word hiesp)
else
  if [[ "$board" == waveshare ]]; then
    build_args+=(--wake-word hiesp)
  else
    build_args+=(--wake-word disabled)
  fi
fi
python "$build_root/scripts/build.py" "${build_args[@]}" ${passthrough[@]+"${passthrough[@]}"}
