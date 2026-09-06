import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

from lich_agent_bridge.codex_model import CodexExecModel, _run_controlled
from lich_agent_bridge.errors import ConfigurationError, ModelError, QuestionInvalidated
from lich_agent_bridge.question import QuestionControl


class RecordingRunner:
    def __init__(self, *, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr
        self.command = None
        self.options = None

    def __call__(self, command, **options):
        self.command = command
        self.options = options
        if self.returncode == 0:
            output = Path(command[command.index("--output-last-message") + 1])
            output.write_text("Subscription-backed answer.\n", encoding="utf-8")
        return subprocess.CompletedProcess(
            command, self.returncode, stdout="", stderr=self.stderr
        )


class CodexExecModelTests(unittest.TestCase):
    def test_runs_ephemeral_read_only_tool_disabled_turn(self):
        runner = RecordingRunner()
        model = CodexExecModel(binary="/test/codex", runner=runner)

        answer = model.respond(instructions="Stay read-only.", input_text="Hello")

        self.assertEqual(answer, "Subscription-backed answer.")
        self.assertIn("--ephemeral", runner.command)
        self.assertIn("--ignore-user-config", runner.command)
        self.assertEqual(
            runner.command[runner.command.index("--sandbox") + 1], "read-only"
        )
        disabled = [
            runner.command[index + 1]
            for index, value in enumerate(runner.command)
            if value == "--disable"
        ]
        self.assertIn("shell_tool", disabled)
        self.assertIn("apps", disabled)
        self.assertIn("web_search", disabled)
        self.assertIn("Stay read-only.", runner.options["input"])
        self.assertIn("Hello", runner.options["input"])
        self.assertNotIn("OPENAI_API_KEY", runner.options["env"])

    def test_missing_cli_is_not_configured(self):
        model = CodexExecModel(binary="")
        self.assertFalse(model.configured)
        with self.assertRaises(ConfigurationError):
            model.respond(instructions="x", input_text="y")

    def test_cli_failure_is_a_model_error(self):
        runner = RecordingRunner(returncode=1, stderr="first\nauth failed\n")
        model = CodexExecModel(binary="/test/codex", runner=runner)
        with self.assertRaisesRegex(ModelError, "auth failed"):
            model.respond(instructions="x", input_text="y")

    def test_reasoning_effort_uses_the_installed_cli_configuration_key(self):
        runner = RecordingRunner()
        model = CodexExecModel(
            binary="/test/codex", reasoning_effort="high", runner=runner
        )

        model.respond(instructions="x", input_text="y")

        configuration = [
            runner.command[index + 1]
            for index, value in enumerate(runner.command)
            if value == "--config"
        ]
        self.assertIn('model_reasoning_effort="high"', configuration)

    def test_controlled_runner_cancels_and_reaps_a_real_local_process(self):
        control = QuestionControl(10)
        errors = []
        def run():
            try:
                _run_controlled(
                    [sys.executable, "-c", "import time; time.sleep(30)"],
                    input="prompt", timeout=10, control=control,
                    capture_output=True, check=False, text=True,
                )
            except Exception as error:
                errors.append(error)
        worker = threading.Thread(target=run)
        worker.start()
        control.cancel("invalidated")
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertIsInstance(errors[0], QuestionInvalidated)

    def test_controlled_adapter_uses_remaining_deadline_and_truthful_metadata(self):
        runner = RecordingRunner()
        model = CodexExecModel(binary="/test/codex", model="chosen", reasoning_effort="high",
                               timeout=180, runner=runner)
        model.respond_controlled(instructions="x", input_text="y", control=QuestionControl(2))
        self.assertLessEqual(runner.options["timeout"], 2)
        self.assertEqual(model.timeout_seconds, 180)
        self.assertEqual(model.timing_metadata, {"model": "chosen", "effort": "high"})


if __name__ == "__main__":
    unittest.main()
