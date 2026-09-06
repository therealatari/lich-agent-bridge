from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from lich_agent_bridge.errors import ConfigurationError
from lich_agent_bridge.local_connection import LocalConnection, read_action_token
from lich_agent_bridge.settings import Settings


class LocalConnectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.token = self.root / "action-token"
        self.token.write_text("a" * 64 + "\n", encoding="ascii")
        self.token.chmod(0o600)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def settings(self, host: str = "127.0.0.1") -> Settings:
        return Settings.load(
            self.root / "config.toml",
            environment={"HOME": str(self.home)},
            overrides={
                "server": {"host": host, "port": 19000},
                "storage": {"action_token_file": str(self.token)},
            },
        )

    def test_connection_uses_resolved_loopback_endpoint_and_token(self) -> None:
        connection = LocalConnection.from_settings(self.settings())

        self.assertEqual(connection.base_url, "http://127.0.0.1:19000")
        self.assertEqual(connection.token, "a" * 64)

    def test_ipv6_loopback_is_bracketed(self) -> None:
        connection = LocalConnection.from_settings(self.settings("::1"))

        self.assertEqual(connection.base_url, "http://[::1]:19000")

    def test_token_must_be_private_regular_owned_and_hex(self) -> None:
        self.token.chmod(0o644)
        with self.assertRaisesRegex(ConfigurationError, "group/world"):
            read_action_token(self.token)

        self.token.chmod(0o600)
        self.token.write_text("not-a-token\n", encoding="ascii")
        with self.assertRaisesRegex(ConfigurationError, "invalid"):
            read_action_token(self.token)

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "requires O_NOFOLLOW")
    def test_token_symbolic_link_is_rejected(self) -> None:
        target = self.root / "target-token"
        target.write_text("b" * 64 + "\n", encoding="ascii")
        target.chmod(0o600)
        self.token.unlink()
        self.token.symlink_to(target)

        with self.assertRaisesRegex(ConfigurationError, "cannot read"):
            read_action_token(self.token)


if __name__ == "__main__":
    unittest.main()
