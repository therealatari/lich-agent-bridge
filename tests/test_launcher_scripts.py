from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class LauncherScriptsTest(unittest.TestCase):
    def test_sidecar_launcher_does_not_interpret_backend_or_credentials(self) -> None:
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            python = fake_bin / "python3"
            python.write_text(
                "#!/usr/bin/env bash\n"
                "printf 'argv:'\n"
                "printf ' <%s>' \"$@\"\n"
                "printf '\\nbackend=%s\\n' \"${LAB_BACKEND:-}\"\n",
                encoding="utf-8",
            )
            python.chmod(0o755)
            environment = {
                **os.environ,
                "HOME": temporary,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "LAB_BACKEND": "openai",
            }

            result = subprocess.run(
                [
                    str(project / "scripts" / "run-sidecar.sh"),
                    "--config",
                    str(root / "settings.toml"),
                ],
                cwd=project,
                env=environment,
                input="",
                text=True,
                capture_output=True,
                timeout=2,
                check=True,
            )

        self.assertIn("argv: <-m> <lich_agent_bridge>", result.stdout)
        self.assertIn(f" <--config> <{root / 'settings.toml'}>", result.stdout)
        self.assertIn("backend=openai", result.stdout)
        self.assertNotIn("API key", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
