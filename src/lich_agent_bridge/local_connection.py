"""Validated credentials and endpoint for the local SessionHub."""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigurationError
from .settings import Settings


_TOKEN_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_MAX_TOKEN_BYTES = 256


@dataclass(frozen=True, slots=True)
class LocalConnection:
    """One authenticated, loopback-only SessionHub connection."""

    base_url: str
    token: str

    @classmethod
    def from_settings(cls, settings: Settings) -> "LocalConnection":
        """Resolve an endpoint and securely read its configured bearer token."""

        host = settings.server.host
        url_host = f"[{host}]" if ":" in host else host
        return cls(
            base_url=f"http://{url_host}:{settings.server.port}",
            token=read_action_token(settings.storage.action_token_file),
        )


def read_action_token(path: Path) -> str:
    """Read a private regular token file without following symbolic links."""

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ConfigurationError(f"cannot read action token file: {path}") from error

    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ConfigurationError("action token file must be a regular file")
        if metadata.st_uid != os.getuid():
            raise ConfigurationError("action token file must be owned by the current user")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise ConfigurationError(
                "action token file must not be group/world accessible"
            )
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            payload = stream.read(_MAX_TOKEN_BYTES + 1)
    finally:
        os.close(descriptor)

    if len(payload) > _MAX_TOKEN_BYTES:
        raise ConfigurationError("action token file is invalid")
    try:
        token = payload.decode("ascii").strip()
    except UnicodeDecodeError as error:
        raise ConfigurationError("action token file is invalid") from error
    if not _TOKEN_PATTERN.fullmatch(token):
        raise ConfigurationError("action token file is invalid")
    return token
