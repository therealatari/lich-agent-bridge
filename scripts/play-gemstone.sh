#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

launch_detached() {
  local output_path="$1"
  shift

  if (( $# == 0 )); then
    printf 'launch_detached requires a command\n' >&2
    return 2
  fi

  /usr/bin/setsid --fork -- "$@" </dev/null >>"${output_path}" 2>&1
}

# Tests source this file to exercise the terminal-independent launch seam. A
# sourced launcher must never continue into the live login path.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  return 0
fi

usage() {
  printf 'Usage: %s CHARACTER [PORT] [TEMPLATE|gtk]\n' "$(basename -- "$0")" >&2
  printf 'Example: %s Mycharacter\n' "$(basename -- "$0")" >&2
  printf 'Native GTK desktop: %s Mycharacter 8000 gtk\n' "$(basename -- "$0")" >&2
  printf 'StormFront shell: %s Mycharacter 8000 stormfront.xml\n' "$(basename -- "$0")" >&2
  printf 'Set LAB_LICH_DIR and LAB_FRONTEND_DIR to your installations.\n' >&2
  printf 'Alternatively set LAB_GAME_DIR for a directory containing Lich5 and ProfanityFE.\n' >&2
  printf 'Ruby/Bundler use PATH; override with LAB_RUBY_BIN and LAB_BUNDLE_BIN.\n' >&2
}

if (( $# < 1 || $# > 3 )); then
  usage
  exit 2
fi

character="$1"
port="${2:-8000}"
template="${3:-}"
frontend='curses'

if [[ "${template}" == 'gtk' ]]; then
  frontend='gtk'
  template=''
fi

if [[ ! "${character}" =~ ^[[:alpha:]]+$ ]]; then
  printf 'Character names may contain letters only: %s\n' "${character}" >&2
  exit 2
fi

if [[ ! "${port}" =~ ^[0-9]+$ ]] || (( port < 1024 || port > 65535 )); then
  printf 'PORT must be a number from 1024 through 65535: %s\n' "${port}" >&2
  exit 2
fi

base_dir="${LAB_GAME_DIR:-}"
lich_dir="${LAB_LICH_DIR:-${base_dir:+${base_dir}/Lich5}}"
profanity_dir="${LAB_FRONTEND_DIR:-${base_dir:+${base_dir}/ProfanityFE}}"
despana_dir="${LAB_FRONTEND_DIR:-${LAB_DESPANA_DIR:-}}"
ruby_bin="${LAB_RUBY_BIN:-$(command -v ruby || true)}"
bundle_bin="${LAB_BUNDLE_BIN:-$(command -v bundle || true)}"
ruby_dir="${ruby_bin%/*}"
log_dir="${XDG_STATE_HOME:-${HOME}/.local/state}/lich-agent-bridge/launcher"
lich_log="${log_dir}/lich-${character,,}.log"
session_log="${log_dir}/despana-${character,,}.log"
profanity_home="${HOME}/.profanity"
profanity_config="${profanity_home}/${character,,}.xml"
lich_pid=''

if [[ "${frontend}" == 'gtk' ]]; then
  frontend_dir="${despana_dir}"
  frontend_script='despana.rb'
  frontend_name='Despana'
else
  frontend_dir="${profanity_dir}"
  frontend_script='profanity.rb'
  frontend_name='ProfanityFE'
fi

if [[ -z "${lich_dir}" || -z "${frontend_dir}" ]]; then
  printf 'Set LAB_LICH_DIR and LAB_FRONTEND_DIR before launching. No installation is assumed.\n' >&2
  exit 2
fi

if [[ -z "${ruby_bin}" || -z "${bundle_bin}" ]]; then
  printf 'Ruby and Bundler must be available on PATH or configured with LAB_RUBY_BIN and LAB_BUNDLE_BIN.\n' >&2
  exit 2
fi

for required_file in "${ruby_bin}" "${bundle_bin}" "${lich_dir}/lich.rbw" "${frontend_dir}/${frontend_script}" "${frontend_dir}/Gemfile"; do
  if [[ ! -e "${required_file}" ]]; then
    printf 'Required file is missing: %s\n' "${required_file}" >&2
    exit 1
  fi
done

if [[ -n "${template}" ]]; then
  if [[ ! "${template}" =~ ^[[:alnum:]_.-]+\.xml$ ]]; then
    printf 'Template must be a simple XML filename: %s\n' "${template}" >&2
    exit 2
  fi
  if [[ ! -f "${frontend_dir}/templates/${template}" ]]; then
    printf 'Frontend template is missing: %s\n' "${frontend_dir}/templates/${template}" >&2
    exit 1
  fi
fi

if [[ -n "$(/usr/bin/ss -H -ltn "sport = :${port}")" ]]; then
  printf 'Local port %s is already in use. Try another, for example:\n' "${port}" >&2
  printf '  %q %q 8001\n' "$0" "${character}" >&2
  exit 1
fi

mkdir -p -- "${log_dir}" "${profanity_home}"
if [[ ! -e "${profanity_config}" ]]; then
  cp -- "${frontend_dir}/templates/original.xml" "${profanity_config}"
  printf 'Created GemStone frontend config: %s\n' "${profanity_config}"
fi

if [[ "${frontend}" == 'gtk' && "${DESPANA_SESSION_DETACHED:-0}" != '1' ]]; then
  printf 'Starting detached Despana session for %s; log: %s\n' "${character}" "${session_log}"
  launch_detached \
    "${session_log}" \
    /usr/bin/env DESPANA_SESSION_DETACHED=1 "$0" "${character}" "${port}" gtk
  printf 'Despana is independent of this terminal; it is safe to close the terminal window.\n'
  exit 0
fi

cleanup() {
  if [[ -n "${lich_pid}" ]] && kill -0 "${lich_pid}" 2>/dev/null; then
    kill "${lich_pid}" 2>/dev/null || true
    wait "${lich_pid}" 2>/dev/null || true
  fi
}
trap cleanup EXIT HUP INT TERM

printf 'Starting Lich for %s on local port %s...\n' "${character}" "${port}"
(
  cd -- "${lich_dir}"
  export PATH="${ruby_dir}:${PATH}"
  exec "${ruby_bin}" lich.rbw --login "${character}" --headless "${port}"
) >"${lich_log}" 2>&1 &
lich_pid=$!

ready=false
for (( attempt = 0; attempt < 225; attempt++ )); do
  if ! kill -0 "${lich_pid}" 2>/dev/null; then
    wait "${lich_pid}" || lich_status=$?
    printf 'Lich exited before opening its frontend port (status %s).\n' "${lich_status:-0}" >&2
    printf 'Last lines from %s:\n' "${lich_log}" >&2
    tail -n 40 -- "${lich_log}" >&2
    exit 1
  fi

  if [[ -n "$(/usr/bin/ss -H -ltn "sport = :${port}")" ]]; then
    ready=true
    break
  fi
  sleep 0.2
done

if [[ "${ready}" != true ]]; then
  printf 'Lich did not open port %s within 45 seconds. See %s\n' "${port}" "${lich_log}" >&2
  exit 1
fi

printf 'Connecting %s (%s)...\n' "${frontend_name}" "${frontend}"
cd -- "${frontend_dir}"
export PATH="${ruby_dir}:${PATH}"
export BUNDLE_GEMFILE="${frontend_dir}/Gemfile"
export BUNDLE_WITHOUT=test
if [[ "${frontend}" == 'gtk' ]]; then
  frontend_args=(despana.rb --port="${port}" --char="${character}")
else
  frontend_args=(profanity.rb --port="${port}" --char="${character}")
  if [[ -n "${template}" ]]; then
    frontend_args+=(--template="${template}")
  fi
fi
"${bundle_bin}" exec "${ruby_bin}" "${frontend_args[@]}"
