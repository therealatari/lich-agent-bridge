"""Launch the Node MCP adapter from the resolved LAB settings."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Callable, Mapping, NoReturn, Sequence

from .errors import ConfigurationError
from .local_connection import LocalConnection
from .settings import Settings


ExecProcess = Callable[[str, Sequence[str], Mapping[str, str]], NoReturn]


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "--config",
        help="settings file (default: LAB_CONFIG or the XDG configuration path)",
    )
    return result


def launch_environment(
    settings: Settings,
    *,
    environment: Mapping[str, str],
) -> dict[str, str]:
    """Return the direct MCP adapter environment for validated settings."""

    connection = LocalConnection.from_settings(settings)
    result = dict(environment)
    result.update(
        {
            "LAB_SESSION_HUB_URL": connection.base_url,
            "LAB_SESSION_HUB_TOKEN": connection.token,
            "LAB_MCP_PORT": str(settings.server.mcp_port),
        }
    )
    return result


def main(
    argv: list[str] | None = None,
    *,
    settings: Settings | None = None,
    environment: Mapping[str, str] | None = None,
    exec_process: ExecProcess = os.execvpe,
    project_root: Path | None = None,
) -> None:
    """Load settings once and replace this process with the Node adapter."""

    args = parser().parse_args(argv)
    env = dict(os.environ if environment is None else environment)
    try:
        resolved = settings or Settings.load(path=args.config, environment=env)
        adapter_environment = launch_environment(resolved, environment=env)
        root = project_root or Path(__file__).resolve().parents[2]
        entrypoint = root / "mcp" / "dist" / "index.js"
        if not entrypoint.is_file():
            raise SystemExit(
                f"MCP adapter is not built: {entrypoint}; run npm run build in mcp/"
            )
        exec_process("node", ("node", str(entrypoint)), adapter_environment)
    except ConfigurationError as error:
        raise SystemExit(f"invalid MCP launcher configuration: {error}") from error
    except OSError as error:
        raise SystemExit(f"cannot launch MCP adapter: {error}") from error


if __name__ == "__main__":
    main()
