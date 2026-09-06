"""Bounded per-character observation memory."""

from __future__ import annotations

from collections import defaultdict, deque
from threading import RLock

from .protocol import Observation


class ContextBuffer:
    """Retain recent observations without exposing storage details to callers."""

    def __init__(self, *, max_events: int = 200, max_characters: int = 16_000):
        if max_events < 1 or max_characters < 1:
            raise ValueError("context limits must be positive")
        self._max_events = max_events
        self._max_characters = max_characters
        self._events: dict[str, deque[Observation]] = defaultdict(
            lambda: deque(maxlen=self._max_events)
        )
        self._lock = RLock()

    def observe(self, observations: list[Observation]) -> int:
        with self._lock:
            for observation in observations:
                self._events[observation.character.casefold()].append(observation)
        return len(observations)

    def snapshot(self, character: str) -> tuple[Observation, ...]:
        with self._lock:
            available = tuple(self._events.get(character.casefold(), ()))

        selected: list[Observation] = []
        used = 0
        for observation in reversed(available):
            cost = len(observation.text) + len(observation.timestamp) + 32
            if selected and used + cost > self._max_characters:
                break
            selected.append(observation)
            used += cost
        selected.reverse()
        return tuple(selected)

    def clear(self, character: str) -> None:
        """Discard observations when the admitted Lich generation changes."""
        with self._lock:
            self._events.pop(character.casefold(), None)
