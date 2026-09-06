from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import URLError
from urllib.request import urlopen


class StageFiveRuntimeTest(unittest.TestCase):
    def test_setup_session_hub_and_doctor_share_one_temporary_config(self) -> None:
        project = Path(__file__).resolve().parents[1]
        session_port = self.available_port()
        mcp_port = self.available_port(excluding={session_port})

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            home.mkdir()
            config = root / "config.toml"
            environment = {
                **{
                    name: value
                    for name, value in os.environ.items()
                    if not name.startswith("LAB_")
                },
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_STATE_HOME": str(root / "state"),
                "LAB_CONFIG": str(config),
                "LAB_PORT": str(session_port),
                "LAB_MCP_PORT": str(mcp_port),
                "PYTHONPATH": self.pythonpath(project),
                "PYTHONDONTWRITEBYTECODE": "1",
            }

            setup = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "lich_agent_bridge.labctl",
                    "--config",
                    str(config),
                    "setup",
                ],
                cwd=project,
                env=environment,
                input="\n",
                text=True,
                capture_output=True,
                timeout=10,
                check=True,
            )
            self.assertTrue(config.is_file())
            self.assertIn(f"Wrote {config} atomically", setup.stdout)
            runtime_environment = {
                name: value
                for name, value in environment.items()
                if name not in {"LAB_PORT", "LAB_MCP_PORT"}
            }

            server = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "lich_agent_bridge",
                    "--config",
                    str(config),
                ],
                cwd=project,
                env=runtime_environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                health = self.wait_for_health(server, session_port)
                self.assertEqual(health["service"], "lich-agent-bridge")
                self.assertEqual(health["status"], "ok")

                doctor = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "lich_agent_bridge.labctl",
                        "--config",
                        str(config),
                        "doctor",
                    ],
                    cwd=project,
                    env=runtime_environment,
                    text=True,
                    capture_output=True,
                    timeout=10,
                    check=True,
                )
                report = json.loads(doctor.stdout)
                checks = {item["name"]: item for item in report["checks"]}
                self.assertEqual(report["config_path"], str(config))
                self.assertEqual(checks["configuration"]["status"], "ok")
                self.assertEqual(checks["session_hub"]["status"], "ok")
                self.assertEqual(
                    checks["session_hub"]["detail"],
                    f"ready at 127.0.0.1:{session_port}",
                )
            finally:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)
                if server.stdout is not None:
                    server.stdout.close()
                if server.stderr is not None:
                    server.stderr.close()

    @staticmethod
    def available_port(*, excluding: set[int] | None = None) -> int:
        excluded = excluding or set()
        while True:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", 0))
                port = int(probe.getsockname()[1])
            if port not in excluded:
                return port

    @staticmethod
    def pythonpath(project: Path) -> str:
        entries = [str(project / "src")]
        inherited = os.environ.get("PYTHONPATH")
        if inherited:
            entries.append(inherited)
        return os.pathsep.join(entries)

    @staticmethod
    def wait_for_health(
        server: subprocess.Popen[str], port: int
    ) -> dict[str, object]:
        deadline = time.monotonic() + 5
        url = f"http://127.0.0.1:{port}/health"
        while time.monotonic() < deadline:
            if server.poll() is not None:
                stdout, stderr = server.communicate()
                raise AssertionError(
                    "SessionHub exited before becoming ready:\n"
                    f"stdout: {stdout}\nstderr: {stderr}"
                )
            try:
                with urlopen(url, timeout=0.25) as response:
                    return json.loads(response.read())
            except (OSError, URLError, json.JSONDecodeError):
                time.sleep(0.05)
        raise AssertionError("SessionHub did not become ready within 5 seconds")


if __name__ == "__main__":
    unittest.main()
