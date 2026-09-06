"""Load sanitized JSONL observations through the production protocol parser."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .engine import Copilot
from .knowledge import KnowledgeBase
from .protocol import AskRequest, Observation
from .server import custom_instructions_from_settings, model_from_settings
from .settings import Settings


def load_observations(path: Path) -> list[Observation]:
    observations: list[Observation] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                observations.append(Observation.from_mapping(value))
            except Exception as error:
                raise ValueError(f"{path}:{line_number}: {error}") from error
    return observations


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, help="sanitized observation JSONL")
    parser.add_argument("--character", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument(
        "--config",
        help="settings file (default: LAB_CONFIG or the XDG configuration path)",
    )
    args = parser.parse_args(argv)

    settings = Settings.load(path=args.config)
    observations = load_observations(args.fixture)
    knowledge = KnowledgeBase.from_settings(settings)
    copilot = Copilot(
        model_from_settings(settings),
        knowledge=knowledge,
        custom_instructions=custom_instructions_from_settings(settings),
    )
    accepted = copilot.observe(observations)
    print(f"Loaded {accepted} sanitized observation(s).")
    answer = copilot.ask(AskRequest(character=args.character, question=args.question))
    print(answer.text)
