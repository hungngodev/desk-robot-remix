#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
if [[ ! -x .tools/sdk-bootstrap/bin/python || ! -f .tools/esp-idf/export.sh ]]; then
  echo "Project-local ESP-IDF/Python environment missing; see docs/build.md." >&2
  exit 1
fi
export IDF_TOOLS_PATH="$project_root/.tools/idf-tools"
export PATH="$project_root/.tools/sdk-bootstrap/bin:$PATH"
source .tools/esp-idf/export.sh
build_args=(desk-robot/desk-robot-core-s3 --name desk-robot-core-s3 --language en-US)
if [[ "${1:-}" == "--private" ]]; then
  shift
  build_args+=(--config config.private.json --wake-word hiesp)
else
  build_args+=(--wake-word disabled)
fi
python firmware/head/build/xiaozhi/scripts/build.py "${build_args[@]}" "$@"
