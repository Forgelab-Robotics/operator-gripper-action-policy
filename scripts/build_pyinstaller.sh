#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUILD_ENV="${ROOT}/.venv-build"
WORK_DIR="${ROOT}/build/pyinstaller"
DIST_DIR="${ROOT}/dist"
SPEC_FILE="${SCRIPT_DIR}/gripper_action_policy.spec"
BINARY="${DIST_DIR}/gripper_action_policy"

cleanup() {
  rm -rf "${BUILD_ENV}"
}
trap cleanup EXIT

cd "${ROOT}"
rm -rf "${BUILD_ENV}" "${WORK_DIR}"
rm -f "${BINARY}"
mkdir -p "${DIST_DIR}" "${WORK_DIR}"

uv venv --python 3.12 --clear "${BUILD_ENV}"
UV_PROJECT_ENVIRONMENT="${BUILD_ENV}" uv sync \
  --no-dev \
  --group build

PYINSTALLER_CONFIG_DIR="${WORK_DIR}/config" \
  "${BUILD_ENV}/bin/pyinstaller" \
  --noconfirm \
  --clean \
  --distpath "${DIST_DIR}" \
  --workpath "${WORK_DIR}" \
  "${SPEC_FILE}"

if [[ ! -x "${BINARY}" ]]; then
  echo "ERROR: 未生成可执行文件：${BINARY}" >&2
  exit 1
fi

timeout 30 "${BINARY}" --help >/dev/null
printf '%s\n' "${BINARY}"
