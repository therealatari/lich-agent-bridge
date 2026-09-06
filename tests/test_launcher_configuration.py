"""Launcher validation only: every case fails before any login can start."""

from pathlib import Path
import subprocess
import tempfile
import unittest


class LauncherConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = Path(__file__).resolve().parents[1]
        self.environment = {"HOME": str(self.root / "home"), "PATH": "/usr/bin:/bin"}

    def launch_validation(self, **configuration):
        # None of these fixtures contains lich.rbw or a frontend, so command
        # dispatch is impossible even if the host has a real Lich installation.
        return subprocess.run(
            ["bash", str(self.project / "scripts/play-gemstone.sh"), "Testmage"],
            env={**self.environment, **configuration}, text=True, capture_output=True,
            check=False, timeout=5,
        )

    def test_unconfigured_launcher_does_not_assume_a_personal_installation(self):
        result = self.launch_validation()
        self.assertEqual(result.returncode, 2)
        self.assertIn("Set LAB_LICH_DIR and LAB_FRONTEND_DIR", result.stderr)
        self.assertFalse((self.root / "home").exists())

    def test_explicit_paths_are_used_and_validated_before_login(self):
        lich = self.root / "chosen lich"
        frontend = self.root / "chosen frontend"
        result = self.launch_validation(LAB_LICH_DIR=str(lich), LAB_FRONTEND_DIR=str(frontend),
                                        LAB_RUBY_BIN="/bin/true", LAB_BUNDLE_BIN="/bin/true")
        self.assertEqual(result.returncode, 1)
        self.assertIn(str(lich / "lich.rbw"), result.stderr)
        self.assertFalse((self.root / "home").exists())

    def test_optional_common_game_directory_derives_only_configured_locations(self):
        game = self.root / "test game"
        result = self.launch_validation(LAB_GAME_DIR=str(game), LAB_RUBY_BIN="/bin/true", LAB_BUNDLE_BIN="/bin/true")
        self.assertEqual(result.returncode, 1)
        self.assertIn(str(game / "Lich5" / "lich.rbw"), result.stderr)

    def test_only_portable_service_templates_are_shipped(self):
        for name in ("lich-agent-bridge", "lich-agent-bridge-mcp"):
            units = self.project / "packaging" / "systemd"
            self.assertTrue((units / f"{name}.service.in").is_file())
            self.assertFalse((units / f"{name}.service").exists())


if __name__ == "__main__":
    unittest.main()
