"""Approve one room-bound action queued by the local Lich bridge."""

from __future__ import annotations

import argparse
import json
import os
import sys
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
    result.add_argument("action_id")
    result.add_argument("character")
    result.add_argument("room_id")
    return result


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

    payload = {
        "action_id": args.action_id,
        "character": args.character,
        "room_id": args.room_id,
        "approval_mode": "manual",
    }
    request = Request(
        f"{connection.base_url}/v1/actions/approve",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {connection.token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=3) as response:
            result = json.loads(response.read())
    except HTTPError as error:
        try:
            detail = json.loads(error.read()).get("detail", error.reason)
        except (json.JSONDecodeError, UnicodeError):
            detail = error.reason
        raise SystemExit(f"approval rejected: {detail}") from error
    except URLError as error:
        raise SystemExit(f"sidecar unavailable: {error.reason}") from error

    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
