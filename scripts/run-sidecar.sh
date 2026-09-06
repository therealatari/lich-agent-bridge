#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="${project_dir}/src${PYTHONPATH:+:${PYTHONPATH}}"

cd -- "${project_dir}"
exec python3 -m lich_agent_bridge "$@"
