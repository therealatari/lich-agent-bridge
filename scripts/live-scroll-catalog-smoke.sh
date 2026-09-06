#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 4 ]]; then
  echo "usage: $0 CHARACTER ROOM_ID OBJECT_ID INVENTORY_JSON" >&2
  exit 2
fi

character=$1
room_id=$2
object_id=${3#\#}
inventory_json=$4

PYTHONPATH=src python3 -m lich_agent_bridge.action_cli \
  "$character" "read #$object_id" --room "$room_id" --ttl 30 >/dev/null

for _attempt in 1 2 3 4 5 6; do
  sleep 1
  fact_count=$(jq --arg object_id "$object_id" '
    [
      .dossiers[]
      | select(.last_game_id == $object_id)
      | .facts[]?
      | select(.field | startswith("scroll.spell."))
    ]
    | length
  ' "$inventory_json")
  if (( fact_count > 0 )); then
    echo "PASS: object #$object_id has $fact_count cataloged spell fact(s)"
    exit 0
  fi
done

echo "FAIL: READ succeeded but object #$object_id has no cataloged spell facts" >&2
exit 1
