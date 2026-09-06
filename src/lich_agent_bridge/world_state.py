"""Thread-safe current state and bounded meaningful events per character."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
import time
from typing import Any, Callable

from .errors import ValidationError
from .protocol import CharacterSnapshot, MeaningfulEvent

DEFAULT_EVENT_CAPACITY = 128
DEFAULT_FRESHNESS_SECONDS = 30.0
MAX_WATCH_TIMEOUT_SECONDS = 30.0


class StateConflict(ValidationError):
    """A valid state message conflicts with the admitted session timeline."""


@dataclass(frozen=True, slots=True)
class _StoredEvent:
    cursor: int
    event: MeaningfulEvent

    def to_mapping(self) -> dict[str, Any]:
        return {"cursor": self.cursor, **self.event.to_mapping()}


@dataclass(slots=True)
class _CharacterState:
    display_name: str
    generation: str | None = None
    sequence: int | None = None
    snapshot: CharacterSnapshot | None = None
    retired_generations: set[str] = field(default_factory=set)
    cursor: int = 0
    events: deque[_StoredEvent] = field(default_factory=deque)


class WorldState:
    """Admit session state and expose immediate snapshots/blocking watches.

    Route contract implemented by :mod:`lich_agent_bridge.server`:

    - ``POST /v1/state`` publishes a :class:`CharacterSnapshot`.
    - ``POST /v1/event`` publishes a :class:`MeaningfulEvent`.
    - ``GET /v1/state/{character}`` reads current state without a game command.
    - ``GET /v1/watch/{character}`` reads after a cursor and blocks boundedly.

    Character lookup is case-insensitive. Generations are opaque and
    case-sensitive. Once replaced, a generation cannot become active again in
    this process; sequence numbers must strictly increase in the active one.
    """

    def __init__(
        self,
        *,
        event_capacity: int = DEFAULT_EVENT_CAPACITY,
        freshness_seconds: float = DEFAULT_FRESHNESS_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] | None = None,
    ):
        if isinstance(event_capacity, bool) or not isinstance(event_capacity, int):
            raise ValueError("event_capacity must be an integer")
        if event_capacity < 1:
            raise ValueError("event_capacity must be positive")
        if freshness_seconds <= 0:
            raise ValueError("freshness_seconds must be positive")
        self._event_capacity = event_capacity
        self._freshness_seconds = float(freshness_seconds)
        self._monotonic = monotonic
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._condition = threading.Condition()
        self._characters: dict[str, _CharacterState] = {}

    def publish_snapshot(self, snapshot: CharacterSnapshot) -> dict[str, Any]:
        key = snapshot.character.casefold()
        with self._condition:
            state = self._characters.get(key)
            if state is None:
                state = _CharacterState(
                    display_name=snapshot.character,
                    events=deque(maxlen=self._event_capacity),
                )
                self._characters[key] = state

            replaced: str | None = None
            if state.generation is None:
                state.generation = snapshot.generation
            elif snapshot.generation != state.generation:
                if snapshot.generation in state.retired_generations:
                    raise StateConflict(
                        "snapshot generation is stale for this character"
                    )
                replaced = state.generation
                state.retired_generations.add(replaced)
                state.generation = snapshot.generation
                state.sequence = None
                state.snapshot = None

            if state.sequence is not None and snapshot.sequence <= state.sequence:
                raise StateConflict(
                    "snapshot sequence must strictly increase within its generation"
                )

            previous = state.snapshot
            changed = previous is None or self._semantic_snapshot(
                previous
            ) != self._semantic_snapshot(snapshot)
            state.display_name = snapshot.character
            state.sequence = snapshot.sequence
            state.snapshot = snapshot
            if changed:
                changed_fields = self._changed_fields(previous, snapshot)
                self._append_event_locked(
                    state,
                    MeaningfulEvent(
                        character=snapshot.character,
                        generation=snapshot.generation,
                        observed_at=snapshot.observed_at,
                        kind="snapshot",
                        summary=(
                            "session snapshot admitted"
                            if previous is None
                            else "session snapshot changed"
                        ),
                        data={
                            "changed_fields": changed_fields,
                            **(
                                {"replaced_generation": replaced}
                                if replaced is not None
                                else {}
                            ),
                        },
                    ),
                )

            return {
                "accepted": True,
                "character": snapshot.character,
                "generation": snapshot.generation,
                "sequence": snapshot.sequence,
                "cursor": state.cursor,
                "replaced_generation": replaced,
            }

    def publish_event(self, event: MeaningfulEvent) -> dict[str, Any]:
        key = event.character.casefold()
        with self._condition:
            state = self._characters.get(key)
            if state is None or state.generation is None:
                raise StateConflict("event has no active snapshot generation")
            if event.generation != state.generation:
                raise StateConflict("event generation is stale for this character")
            stored = self._append_event_locked(state, event)
            return {
                "accepted": True,
                "character": state.display_name,
                "generation": state.generation,
                "cursor": stored.cursor,
            }

    def snapshot(self, character: str) -> dict[str, Any] | None:
        key = self._character_key(character)
        with self._condition:
            state = self._characters.get(key)
            if state is None or state.snapshot is None:
                return None
            snapshot = state.snapshot
            observed = self._parse_timestamp(snapshot.observed_at)
            now = self._now()
            if now.tzinfo is None or now.utcoffset() is None:
                now = now.replace(tzinfo=timezone.utc)
            age = max(0.0, (now - observed).total_seconds())
            return {
                "snapshot": snapshot.to_mapping(),
                "cursor": state.cursor,
                "freshness": {
                    "observed_at": snapshot.observed_at,
                    "age_seconds": round(age, 3),
                    "stale": age > self._freshness_seconds,
                },
            }

    def watch(
        self,
        character: str,
        *,
        cursor: int = 0,
        timeout: float = MAX_WATCH_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        key = self._character_key(character)
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
            raise ValidationError("cursor must be a nonnegative integer")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ValidationError("timeout must be a number")
        timeout = float(timeout)
        if not 0 <= timeout <= MAX_WATCH_TIMEOUT_SECONDS:
            raise ValidationError(
                f"timeout must be between 0 and {MAX_WATCH_TIMEOUT_SECONDS:g} seconds"
            )

        deadline = self._monotonic() + timeout
        with self._condition:
            while True:
                state = self._characters.get(key)
                available = [] if state is None else [
                    item for item in state.events if item.cursor > cursor
                ]
                if available:
                    oldest_cursor = state.events[0].cursor
                    return {
                        "character": state.display_name,
                        "cursor": available[-1].cursor,
                        "events": [item.to_mapping() for item in available],
                        "timed_out": False,
                        "truncated": cursor < oldest_cursor - 1,
                    }
                remaining = deadline - self._monotonic()
                if remaining <= 0:
                    current_cursor = 0 if state is None else state.cursor
                    display_name = character if state is None else state.display_name
                    return {
                        "character": display_name,
                        "cursor": current_cursor,
                        "events": [],
                        "timed_out": True,
                        "truncated": False,
                    }
                self._condition.wait(remaining)

    def _append_event_locked(
        self, state: _CharacterState, event: MeaningfulEvent
    ) -> _StoredEvent:
        state.cursor += 1
        stored = _StoredEvent(cursor=state.cursor, event=event)
        state.events.append(stored)
        self._condition.notify_all()
        return stored

    @staticmethod
    def _semantic_snapshot(snapshot: CharacterSnapshot) -> dict[str, Any]:
        result = snapshot.to_mapping()
        result.pop("observed_at", None)
        result.pop("sequence", None)
        return result

    @staticmethod
    def _changed_fields(
        previous: CharacterSnapshot | None, current: CharacterSnapshot
    ) -> list[str]:
        current_mapping = WorldState._semantic_snapshot(current)
        if previous is None:
            return sorted(current_mapping)
        previous_mapping = WorldState._semantic_snapshot(previous)
        return sorted(
            key
            for key in current_mapping.keys() | previous_mapping.keys()
            if current_mapping.get(key) != previous_mapping.get(key)
        )

    @staticmethod
    def _character_key(character: str) -> str:
        if not isinstance(character, str):
            raise ValidationError("character must be a string")
        normalized = character.replace("\x00", "").strip()
        if not normalized:
            raise ValidationError("character must not be blank")
        if len(normalized) > 40:
            raise ValidationError("character exceeds 40 characters")
        return normalized.casefold()

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
