"""Read-only access to durable LAB Inventory knowledge.

Lich remains authoritative for current hands and locations.  This adapter reads
only learned dossier facts and explicitly timestamped last observations from
the account SQLite ledger.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .errors import ValidationError

if TYPE_CHECKING:
    from .settings import Settings


MAX_QUERY_LENGTH = 200
MAX_RESULTS = 100


@dataclass(frozen=True, slots=True)
class InventoryItem:
    dossier_id: str
    fingerprint: str
    item_type: str
    noun: str
    name: str
    full_name: str
    last_game_id: str | None
    last_seen_at: str | None
    last_location: dict[str, Any] | None
    facts: tuple[dict[str, Any], ...]

    def to_mapping(self) -> dict[str, Any]:
        return {
            "dossier_id": self.dossier_id,
            "fingerprint": self.fingerprint,
            "identity": {
                "type": self.item_type,
                "noun": self.noun,
                "name": self.name,
                "full_name": self.full_name,
            },
            "last_game_id": self.last_game_id,
            "last_seen_at": self.last_seen_at,
            "last_location": self.last_location,
            "facts": list(self.facts),
        }


class InventoryKnowledge:
    """Query durable inventory facts without pretending they are live state."""

    def __init__(self, database: Path | None):
        self.database = Path(database) if database is not None else None

    @classmethod
    def from_environment(cls) -> "InventoryKnowledge":
        """Compatibility wrapper around the central settings module."""

        from .settings import Settings

        return cls.from_settings(Settings.load())

    @classmethod
    def from_settings(cls, settings: "Settings") -> "InventoryKnowledge":
        """Build from the already-resolved application configuration."""

        return cls(settings.storage.resolved_inventory_database)

    @property
    def configured(self) -> bool:
        return self.database is not None and self.database.is_file()

    def find(
        self, *, character: str, query: str, limit: int = 20
    ) -> tuple[InventoryItem, ...]:
        character = character.strip()
        query = query.strip()
        if not character:
            raise ValidationError("character must not be blank")
        if not query:
            raise ValidationError("inventory query must not be blank")
        if len(query) > MAX_QUERY_LENGTH:
            raise ValidationError(
                f"inventory query exceeds {MAX_QUERY_LENGTH} characters"
            )
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_RESULTS:
            raise ValidationError(f"limit must be between 1 and {MAX_RESULTS}")
        if not self.configured:
            return ()

        assert self.database is not None
        connection = sqlite3.connect(f"file:{self.database}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            pattern = f"%{query.casefold()}%"
            rows = connection.execute(
                """
                SELECT d.*, c.name AS character_name
                  FROM dossiers AS d
                  JOIN characters AS c ON c.id = d.character_id
                 WHERE c.name = ? COLLATE NOCASE
                   AND (
                       lower(d.id) LIKE ? OR lower(coalesce(d.item_type, '')) LIKE ? OR
                       lower(coalesce(d.noun, '')) LIKE ? OR lower(coalesce(d.name, '')) LIKE ? OR
                       lower(coalesce(d.full_name, '')) LIKE ? OR lower(coalesce(d.last_game_id, '')) = ?
                   )
                 ORDER BY coalesce(d.last_seen_at, d.updated_at) DESC, d.id
                 LIMIT ?
                """,
                (character, pattern, pattern, pattern, pattern, pattern, query.removeprefix("#"), limit),
            ).fetchall()
            return tuple(self._materialize(connection, row) for row in rows)
        except sqlite3.Error:
            return ()
        finally:
            connection.close()

    def _materialize(
        self, connection: sqlite3.Connection, row: sqlite3.Row
    ) -> InventoryItem:
        facts = connection.execute(
            """
            SELECT field, value_json, source, confidence, observed_at, evidence
              FROM facts
             WHERE dossier_id = ? AND active = 1
             ORDER BY ordinal, id
            """,
            (row["id"],),
        ).fetchall()
        location = connection.execute(
            """
            SELECT session_id, kind, container_game_id, hand, game_id, observed_at
              FROM session_locations
             WHERE dossier_id = ?
             ORDER BY observed_at DESC
             LIMIT 1
            """,
            (row["id"],),
        ).fetchone()
        return InventoryItem(
            dossier_id=str(row["id"]),
            fingerprint=str(row["fingerprint"]),
            item_type=str(row["item_type"] or ""),
            noun=str(row["noun"] or ""),
            name=str(row["name"] or ""),
            full_name=str(row["full_name"] or ""),
            last_game_id=None if row["last_game_id"] is None else str(row["last_game_id"]),
            last_seen_at=None if row["last_seen_at"] is None else str(row["last_seen_at"]),
            last_location=(
                None
                if location is None
                else {
                    "session_id": location["session_id"],
                    "kind": location["kind"],
                    "container_game_id": location["container_game_id"],
                    "hand": location["hand"],
                    "game_id": location["game_id"],
                    "observed_at": location["observed_at"],
                    "authority": "last_observation_only",
                }
            ),
            facts=tuple(
                {
                    "field": fact["field"],
                    "value": _json_value(fact["value_json"]),
                    "source": fact["source"],
                    "confidence": fact["confidence"],
                    "observed_at": fact["observed_at"],
                    "evidence": fact["evidence"],
                }
                for fact in facts
            ),
        )


def _json_value(value: str) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value
