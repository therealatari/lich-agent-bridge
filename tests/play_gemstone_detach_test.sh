#!/usr/bin/env bash
set -Eeuo pipefail

test_dir="$(mktemp -d)"
probe_pid=''

cleanup() {
  if [[ -n "${probe_pid}" ]] && kill -0 "${probe_pid}" 2>/dev/null; then
    kill "${probe_pid}" 2>/dev/null || true
  fi
  rm -rf -- "${test_dir}"
}
trap cleanup EXIT

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "${project_dir}/scripts/play-gemstone.sh"

pid_file="${test_dir}/probe.pid"
log_file="${test_dir}/probe.log"

launch_detached \
  "${log_file}" \
  /bin/sh -c 'printf "%s\n" "$$" > "$1"; exec sleep 5' sh "${pid_file}"

for (( attempt = 0; attempt < 100; attempt++ )); do
  [[ -s "${pid_file}" ]] && break
  sleep 0.02
done

[[ -s "${pid_file}" ]] || {
  printf 'detached probe did not start; log follows:\n' >&2
  sed -n '1,80p' "${log_file}" >&2
  exit 1
}

probe_pid="$(<"${pid_file}")"
kill -0 "${probe_pid}"

probe_tty="$(ps -o tty= -p "${probe_pid}")"
[[ "${probe_tty//[[:space:]]/}" == '?' ]] || {
  printf 'detached probe retained a controlling TTY: %s\n' "${probe_tty}" >&2
  exit 1
}

printf 'play-gemstone detached-launch regression test passed\n'
