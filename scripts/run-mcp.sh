#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

cd -- "${project_dir}/mcp"
if [[ ! -f dist/index.js ]] || find src -type f -newer dist/index.js -print -quit | grep -q .; then
  npm run build
fi

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="${project_dir}/src${PYTHONPATH:+:${PYTHONPATH}}"
cd -- "${project_dir}"
exec python3 -m lich_agent_bridge.mcp_launcher "$@"
