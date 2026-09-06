from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class ServiceInstallerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.config_home = self.root / "config home"
        self.settings = self.root / "settings with spaces.toml"
        self.source_project = Path(__file__).resolve().parents[1]
        self.project = self.root / "project with spaces"
        (self.project / "scripts").mkdir(parents=True)
        (self.project / "packaging" / "systemd").mkdir(parents=True)
        shutil.copy2(
            self.source_project / "scripts" / "install-user-services.sh",
            self.project / "scripts" / "install-user-services.sh",
        )
        for name in (
            "lich-agent-bridge.service.in",
            "lich-agent-bridge-mcp.service.in",
        ):
            shutil.copy2(
                self.source_project / "packaging" / "systemd" / name,
                self.project / "packaging" / "systemd" / name,
            )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_render_only_installs_portable_units_without_systemctl(self) -> None:
        environment = {
            **os.environ,
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.config_home),
            "PATH": os.environ["PATH"],
        }
        subprocess.run(
            [
                str(self.project / "scripts" / "install-user-services.sh"),
                "--config",
                str(self.settings),
                "--render-only",
            ],
            cwd=self.project,
            env=environment,
            text=True,
            capture_output=True,
            check=True,
        )

        unit_root = self.config_home / "systemd" / "user"
        sidecar = (unit_root / "lich-agent-bridge.service").read_text(
            encoding="utf-8"
        )
        mcp = (unit_root / "lich-agent-bridge-mcp.service").read_text(
            encoding="utf-8"
        )
        escaped_project = str(self.project).replace(" ", r"\x20")
        self.assertIn(f"WorkingDirectory={escaped_project}", sidecar)
        self.assertIn(f'Environment="LAB_CONFIG={self.settings}"', sidecar)
        self.assertIn(f'ExecStart="{self.project}/scripts/run-sidecar.sh"', sidecar)
        self.assertIn(f'ExecStart="{self.project}/scripts/run-mcp.sh"', mcp)
        self.assertNotIn(str(self.source_project), "\n".join((sidecar, mcp)))
        self.assertNotIn("@PROJECT_DIR@", sidecar)
        self.assertEqual((unit_root.stat().st_mode & 0o777), 0o700)

    def test_relative_xdg_config_home_is_rejected(self) -> None:
        result = subprocess.run(
            [
                str(self.project / "scripts" / "install-user-services.sh"),
                "--render-only",
            ],
            cwd=self.project,
            env={
                **os.environ,
                "HOME": str(self.home),
                "XDG_CONFIG_HOME": "relative",
            },
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("must be an absolute path", result.stderr)


if __name__ == "__main__":
    unittest.main()
