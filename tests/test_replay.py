import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from lich_agent_bridge.replay import load_observations, main


class ReplayTests(unittest.TestCase):
    def test_sanitized_fixture_uses_production_parser(self):
        fixture = Path(__file__).parent / "fixtures" / "synthetic-hunt.jsonl"
        observations = load_observations(fixture)
        self.assertEqual(len(observations), 5)
        self.assertTrue(all(event.character == "Testwarrior" for event in observations))

    def test_main_uses_one_explicit_settings_file_for_model_and_knowledge(self):
        fixture = Path(__file__).parent / "fixtures" / "synthetic-hunt.jsonl"
        settings = Mock()
        model = Mock()
        knowledge = Mock()
        answer = Mock(text="Replay answer")

        with (
            patch("lich_agent_bridge.replay.Settings.load", return_value=settings) as load,
            patch(
                "lich_agent_bridge.replay.model_from_settings", return_value=model
            ) as build_model,
            patch(
                "lich_agent_bridge.replay.KnowledgeBase.from_settings",
                return_value=knowledge,
            ) as build_knowledge,
            patch(
                "lich_agent_bridge.replay.custom_instructions_from_settings",
                return_value="",
            ) as load_instructions,
            patch("lich_agent_bridge.replay.Copilot") as copilot_class,
            patch("builtins.print"),
        ):
            copilot_class.return_value.observe.return_value = 5
            copilot_class.return_value.ask.return_value = answer
            main(
                [
                    str(fixture),
                    "--character",
                    "Testwarrior",
                    "--question",
                    "What happened?",
                    "--config",
                    "/tmp/lab-config.toml",
                ]
            )

        load.assert_called_once_with(path="/tmp/lab-config.toml")
        build_model.assert_called_once_with(settings)
        build_knowledge.assert_called_once_with(settings)
        load_instructions.assert_called_once_with(settings)
        copilot_class.assert_called_once_with(
            model, knowledge=knowledge, custom_instructions=""
        )


if __name__ == "__main__":
    unittest.main()
