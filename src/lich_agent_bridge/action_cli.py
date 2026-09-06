"""Queue one tightly scoped local action or explicit utility sequence."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .errors import ConfigurationError
from .local_connection import LocalConnection
from .settings import Settings


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "--config",
        help="settings file (default: LAB_CONFIG or the XDG configuration path)",
    )
    result.add_argument("character")
    result.add_argument("command")
    result.add_argument(
        "--then",
        dest="following_commands",
        action="append",
        default=[],
        metavar="COMMAND",
        help=(
            "append an ordered inventory/crafting step; repeat to send one "
            "locally executed, confirmation-gated sequence"
        ),
    )
    result.add_argument("--room", dest="expected_room_id")
    result.add_argument("--ttl", dest="ttl_seconds", type=int, default=45)
    result.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="seconds to wait for bridge completion (default: 30)",
    )
    result.add_argument(
        "--no-wait",
        action="store_true",
        help="return after proposal instead of waiting for bridge completion",
    )
    return result


def _post(
    base_url: str,
    token: str,
    path: str,
    payload: dict[str, object],
) -> dict:
    request = Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urlopen(request, timeout=3) as response:
        return json.loads(response.read())


def _proposal_payload(args: argparse.Namespace) -> dict[str, object]:
    payload: dict[str, object] = {
        "character": args.character,
        "ttl_seconds": args.ttl_seconds,
    }
    if args.following_commands:
        payload["commands"] = [args.command, *args.following_commands]
    else:
        payload["command"] = args.command
    if args.expected_room_id is not None:
        payload["expected_room_id"] = args.expected_room_id
    return payload


def main(
    argv: list[str] | None = None,
    *,
    settings: Settings | None = None,
    environment: Mapping[str, str] | None = None,
) -> None:
    args = parser().parse_args(argv)
    env = dict(os.environ if environment is None else environment)
    try:
        resolved = settings or Settings.load(path=args.config, environment=env)
        connection = LocalConnection.from_settings(resolved)
    except ConfigurationError as error:
        raise SystemExit(f"invalid local configuration: {error}") from error
    payload = _proposal_payload(args)
    try:
        result = _post(
            connection.base_url,
            connection.token,
            "/v1/actions/propose",
            payload,
        )
        if not args.no_wait:
            deadline = time.monotonic() + args.timeout
            terminal = {"completed", "failed", "cancelled", "expired", "denied_stale_room"}
            while result.get("status") not in terminal:
                if time.monotonic() >= deadline:
                    raise SystemExit(
                        f"action {result['action_id']} did not complete within {args.timeout:g}s"
                    )
                time.sleep(0.1)
                result = _post(
                    connection.base_url,
                    connection.token,
                    "/v1/actions/status",
                    {"action_id": result["action_id"]},
                )
    except HTTPError as error:
        try:
            detail = json.loads(error.read()).get("detail", error.reason)
        except (json.JSONDecodeError, UnicodeError):
            detail = error.reason
        raise SystemExit(f"action rejected: {detail}") from error
    except URLError as error:
        raise SystemExit(f"sidecar unavailable: {error.reason}") from error
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    if result.get("status") in {"failed", "cancelled", "expired", "denied_stale_room"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
