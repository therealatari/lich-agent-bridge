"""Timestamped INFO/SKILLS observations in the existing account inventory DB.

The historical character audit tables are deliberately untouched. SessionHub
must admit the snapshot generation before calling record; model answers never
enter this adapter.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from threading import Lock
from typing import Any, Callable, Mapping

from .protocol import MAX_GENERATION_LENGTH, CharacterSnapshot, _character_data
from .errors import ValidationError


CHARACTER_DATA_MAX_AGE_SECONDS = 120


def category_freshness(
    record: Mapping[str, Any], *, generation: str | None,
    level: int | None = None, now: datetime | None = None,
) -> dict[str, Any]:
    """Known zero values remain data; missing timestamps remain unknown age."""
    now = now or datetime.now(timezone.utc)
    observed = record.get("observed_at")
    age = None if observed is None else (now - datetime.fromisoformat(observed.replace("Z", "+00:00"))).total_seconds()
    same_session = generation is not None and record.get("generation") == generation
    same_level = level is None or record.get("observed_level") == level
    current = bool(
        record.get("complete") and record.get("source") in {"info", "skills"}
        and same_session and same_level and age is not None
        and 0 <= age <= CHARACTER_DATA_MAX_AGE_SECONDS
    )
    return {
        "current": current, "age_seconds": None if age is None else round(age, 3),
        "same_generation": same_session, "same_level": same_level,
        "authority": "current_character_observation" if current else "last_observation_only",
    }


class CharacterKnowledge:
    def __init__(self, database: Path | None, *, now: Callable[[], datetime] | None = None):
        self.database = Path(database) if database is not None else None
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._lock = Lock()
        self._saved: dict[tuple[str, str, str], tuple[str, str]] = {}

    @property
    def configured(self) -> bool:
        return self.database is not None and self.database.is_file()

    def record(self, snapshot: CharacterSnapshot) -> dict[str, Any]:
        """Persist only fresh completed observations, never uncertain cache data."""
        try:
            if not self.configured:
                return {"status": "unconfigured", "categories": []}
        except OSError:
            return {"status": "unavailable", "categories": []}
        data = snapshot.character_data or {}
        level = data.get("info", {}).get("values", {}).get("level")
        now = self._now()
        candidates = {}
        for category, value in data.items():
            record = {**value, "generation": snapshot.generation}
            if category_freshness(record, generation=snapshot.generation, level=level, now=now)["current"]:
                # A category cannot have been observed after its enclosing sample.
                if datetime.fromisoformat(value["observed_at"].replace("Z", "+00:00")) <= datetime.fromisoformat(snapshot.observed_at.replace("Z", "+00:00")):
                    candidates[category] = record
        with self._lock:
            pending = {
                category: record for category, record in candidates.items()
                if self._saved.get((snapshot.game, snapshot.character.casefold(), category))
                != (snapshot.generation, record["observed_at"])
            }
            if not pending:
                return {"status": "unchanged", "categories": []}
            assert self.database is not None
            try:
                connection = sqlite3.connect(self.database.resolve().as_uri() + "?mode=rw", uri=True, timeout=0.25)
                try:
                    written = []
                    with connection:
                        connection.execute("""
                            CREATE TABLE IF NOT EXISTS character_current_context (
                                game TEXT NOT NULL, character TEXT NOT NULL COLLATE NOCASE,
                                category TEXT NOT NULL, generation TEXT NOT NULL,
                                observed_at TEXT NOT NULL, payload_json TEXT NOT NULL,
                                PRIMARY KEY (game, character, category)
                            )
                        """)
                        for category, record in pending.items():
                            stamp = datetime.fromisoformat(record["observed_at"].replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
                            cursor = connection.execute("""
                                INSERT INTO character_current_context VALUES (?, ?, ?, ?, ?, ?)
                                ON CONFLICT (game, character, category) DO UPDATE SET
                                  generation=excluded.generation, observed_at=excluded.observed_at,
                                  payload_json=excluded.payload_json
                                WHERE excluded.observed_at > character_current_context.observed_at
                                  OR (excluded.observed_at = character_current_context.observed_at
                                      AND excluded.generation != character_current_context.generation)
                            """, (snapshot.game, snapshot.character, category, snapshot.generation,
                                  stamp, json.dumps(record, sort_keys=True, separators=(",", ":"))))
                            if cursor.rowcount:
                                written.append(category)
                    for category, record in pending.items():
                        self._saved[(snapshot.game, snapshot.character.casefold(), category)] = (snapshot.generation, record["observed_at"])
                    return {"status": "saved" if written else "unchanged", "categories": written}
                finally:
                    connection.close()
            except (sqlite3.Error, OSError):
                return {"status": "unavailable", "categories": []}

    def find(
        self, *, character: str, game: str = "GSIV", generation: str | None = None,
    ) -> dict[str, Mapping[str, Any]]:
        try:
            if not self.configured:
                return {}
            assert self.database is not None
            connection = sqlite3.connect(self.database.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.25)
            try:
                rows = connection.execute("""
                    SELECT category, generation, payload_json FROM character_current_context
                    WHERE game = ? AND character = ? COLLATE NOCASE
                """, (game, character)).fetchall()
                records = {}
                for category, recorded_generation, serialized in rows:
                    if (not isinstance(recorded_generation, str)
                            or not recorded_generation.strip()
                            or len(recorded_generation) > MAX_GENERATION_LENGTH):
                        continue
                    raw = json.loads(serialized)
                    payload = {key: raw[key] for key in ("source", "observed_at", "complete", "observed_level", "values") if key in raw}
                    validated = _character_data({category: payload})
                    record = {**validated[category], "generation": recorded_generation,
                              "character": character, "game": game, "category": category}
                    record["freshness"] = category_freshness(record, generation=generation, now=self._now())
                    records[category] = record
                return records
            finally:
                connection.close()
        except (sqlite3.Error, OSError, ValidationError, ValueError, KeyError, TypeError):
            return {}
