from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lich_agent_bridge.mcp_launcher import launch_environment, main
from lich_agent_bridge.settings import Settings


class McpLauncherTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.token = self.root / "action-token"
        self.token.write_text("c" * 64 + "\n", encoding="ascii")
        self.token.chmod(0o600)
        self.settings = Settings.load(
            self.root / "config.toml",
            environment={"HOME": str(self.home)},
            overrides={
                "server": {"port": 19000, "mcp_port": 19001},
                "storage": {"action_token_file": str(self.token)},
            },
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_launch_environment_preserves_direct_adapter_contract(self) -> None:
        environment = launch_environment(
            self.settings,
            environment={"PATH": "/test/bin", "UNCHANGED": "yes"},
        )

        self.assertEqual(environment["LAB_SESSION_HUB_URL"], "http://127.0.0.1:19000")
        self.assertEqual(environment["LAB_SESSION_HUB_TOKEN"], "c" * 64)
        self.assertEqual(environment["LAB_MCP_PORT"], "19001")
        self.assertEqual(environment["UNCHANGED"], "yes")

    def test_main_loads_once_and_execs_node_with_resolved_environment(self) -> None:
        project = self.root / "project"
        entrypoint = project / "mcp" / "dist" / "index.js"
        entrypoint.parent.mkdir(parents=True)
        entrypoint.write_text("", encoding="utf-8")
        calls: list[tuple[str, tuple[str, ...], dict[str, str]]] = []

        def fake_exec(command: str, argv, environment) -> None:
            calls.append((command, tuple(argv), dict(environment)))

        with mock.patch(
            "lich_agent_bridge.mcp_launcher.Settings.load",
            return_value=self.settings,
        ) as load:
            main(
                ["--config", str(self.root / "explicit.toml")],
                environment={"HOME": str(self.home)},
                exec_process=fake_exec,
                project_root=project,
            )

        load.assert_called_once_with(
            path=str(self.root / "explicit.toml"),
            environment={"HOME": str(self.home)},
        )
        self.assertEqual(calls[0][0], "node")
        self.assertEqual(calls[0][1], ("node", str(entrypoint)))
        self.assertEqual(calls[0][2]["LAB_MCP_PORT"], "19001")

    def test_missing_build_exits_before_exec(self) -> None:
        with self.assertRaisesRegex(SystemExit, "MCP adapter is not built"):
            main(
                [],
                settings=self.settings,
                environment={},
                exec_process=lambda *_: self.fail("must not exec"),
                project_root=self.root / "missing",
            )


if __name__ == "__main__":
    unittest.main()
