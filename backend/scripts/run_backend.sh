#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

export PYTHONPATH="${REPO_ROOT}"
export MARACUYA_HEF="${MARACUYA_HEF:-/hailo/maracuya_yolo.hef}"

cd "${REPO_ROOT}"
exec python -m backend.main
