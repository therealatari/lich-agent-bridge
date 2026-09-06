from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lich_agent_bridge.action_approve_cli import main as approve_main
from lich_agent_bridge.action_cli import _proposal_payload, main as action_main, parser
from lich_agent_bridge.settings import Settings


class ActionCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.token = self.root / "token"
        self.token.write_text("d" * 64 + "\n", encoding="ascii")
        self.token.chmod(0o600)
        self.settings = Settings.load(
            self.root / "config.toml",
            environment={"HOME": str(self.home)},
            overrides={
                "server": {"port": 19123},
                "storage": {"action_token_file": str(self.token)},
            },
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_single_command_keeps_legacy_payload(self):
        args = parser().parse_args(["Testmage", "look", "--room", "4277"])

        self.assertEqual(
            _proposal_payload(args),
            {
                "character": "Testmage",
                "command": "look",
                "expected_room_id": "4277",
                "ttl_seconds": 45,
            },
        )

    def test_repeated_then_options_create_one_ordered_sequence(self):
        args = parser().parse_args(
            [
                "Testmage",
                "put my runestone in my robes",
                "--then",
                "get my smooth stone",
                "--then",
                "wave my stone at my scroll",
            ]
        )

        payload = _proposal_payload(args)
        self.assertNotIn("command", payload)
        self.assertEqual(
            payload["commands"],
            [
                "put my runestone in my robes",
                "get my smooth stone",
                "wave my stone at my scroll",
            ],
        )

    def test_action_main_uses_injected_resolved_settings(self) -> None:
        response = {
            "action_id": "action-1",
            "status": "confirmation_required",
        }
        with (
            mock.patch(
                "lich_agent_bridge.action_cli._post",
                return_value=response,
            ) as post,
            mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            action_main(
                ["Testmage", "look", "--no-wait"],
                settings=self.settings,
                environment={"LAB_PORT": "29999"},
            )

        post.assert_called_once_with(
            "http://127.0.0.1:19123",
            "d" * 64,
            "/v1/actions/propose",
            {"character": "Testmage", "command": "look", "ttl_seconds": 45},
        )
        self.assertEqual(json.loads(stdout.getvalue()), response)

    def test_action_main_loads_settings_once(self) -> None:
        with (
            mock.patch(
                "lich_agent_bridge.action_cli.Settings.load",
                return_value=self.settings,
            ) as load,
            mock.patch(
                "lich_agent_bridge.action_cli._post",
                return_value={"action_id": "action-1", "status": "completed"},
            ),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            action_main(
                ["--config", "/tmp/test.toml", "Testmage", "look", "--no-wait"],
                environment={"HOME": str(self.home)},
            )

        load.assert_called_once_with(
            path="/tmp/test.toml", environment={"HOME": str(self.home)}
        )

    def test_approve_main_uses_resolved_settings(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self) -> bytes:
                return b'{"status":"queued"}'

        requests = []

        def fake_urlopen(request, timeout):
            requests.append((request, timeout))
            return Response()

        with (
            mock.patch(
                "lich_agent_bridge.action_approve_cli.urlopen",
                side_effect=fake_urlopen,
            ),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            approve_main(
                ["action-1", "Testmage", "4277"],
                settings=self.settings,
                environment={"LAB_PORT": "29999"},
            )

        request, timeout = requests[0]
        self.assertEqual(
            request.full_url,
            "http://127.0.0.1:19123/v1/actions/approve",
        )
        self.assertEqual(request.get_header("Authorization"), f"Bearer {'d' * 64}")
        self.assertEqual(timeout, 3)

    def test_approve_main_loads_settings_once(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self) -> bytes:
                return b'{"status":"queued"}'

        with (
            mock.patch(
                "lich_agent_bridge.action_approve_cli.Settings.load",
                return_value=self.settings,
            ) as load,
            mock.patch(
                "lich_agent_bridge.action_approve_cli.urlopen",
                return_value=Response(),
            ),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            approve_main(
                ["--config", "/tmp/test.toml", "action-1", "Testmage", "4277"],
                environment={"HOME": str(self.home)},
            )

        load.assert_called_once_with(
            path="/tmp/test.toml", environment={"HOME": str(self.home)}
        )


if __name__ == "__main__":
    unittest.main()
