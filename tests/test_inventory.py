import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from lich_agent_bridge.errors import ValidationError
from lich_agent_bridge.inventory import InventoryKnowledge


class InventoryKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "inventory.sqlite3"
        connection = sqlite3.connect(self.database)
        connection.executescript(
            """
            CREATE TABLE characters (id INTEGER PRIMARY KEY, game TEXT, name TEXT);
            CREATE TABLE dossiers (
                id TEXT PRIMARY KEY, character_id INTEGER, fingerprint TEXT,
                item_type TEXT, noun TEXT, name TEXT, full_name TEXT,
                last_game_id TEXT, created_at TEXT, updated_at TEXT, last_seen_at TEXT
            );
            CREATE TABLE facts (
                id INTEGER PRIMARY KEY, dossier_id TEXT, occurrence_key TEXT,
                ordinal INTEGER, field TEXT, value_json TEXT, source TEXT,
                confidence TEXT, observed_at TEXT, evidence TEXT, active INTEGER
            );
            CREATE TABLE session_locations (
                dossier_id TEXT, session_id TEXT, kind TEXT,
                container_game_id TEXT, hand TEXT, game_id TEXT, observed_at TEXT
            );
            """
        )
        connection.execute(
            "INSERT INTO characters(id, game, name) VALUES(1, 'GSIV', 'Testmage')"
        )
        connection.execute(
            """
            INSERT INTO dossiers VALUES(
                'item-staff', 1, 'runestaff|ash staff|ash staff',
                'weapon', 'runestaff', 'ash staff', 'an ash staff',
                '123', '2026-08-30', '2026-08-31', '2026-08-31T03:00:00Z'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO facts VALUES(
                1, 'item-staff', 'enchant', 0, 'enchant_bonus', ?, '405',
                'observed', '2026-08-31T03:00:00Z', 'strong glow', 1
            )
            """,
            (json.dumps(15),),
        )
        connection.execute(
            """
            INSERT INTO session_locations VALUES(
                'item-staff', 'old-lich-session', 'hand', NULL, 'right', '123',
                '2026-08-31T03:00:01Z'
            )
            """
        )
        connection.commit()
        connection.close()

    def tearDown(self):
        self.temporary.cleanup()

    def test_find_returns_durable_facts_and_labels_location_as_historical(self):
        items = InventoryKnowledge(self.database).find(
            character="testmage", query="staff"
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].dossier_id, "item-staff")
        self.assertEqual(items[0].facts[0]["value"], 15)
        self.assertEqual(
            items[0].last_location["authority"], "last_observation_only"
        )
        self.assertEqual(items[0].last_location["observed_at"], "2026-08-31T03:00:01Z")

    def test_character_scope_is_case_insensitive_and_isolated(self):
        self.assertEqual(
            InventoryKnowledge(self.database).find(
                character="Testscout", query="staff"
            ),
            (),
        )

    def test_missing_database_degrades_to_empty(self):
        self.assertEqual(
            InventoryKnowledge(Path(self.temporary.name) / "missing.sqlite3").find(
                character="Testmage", query="staff"
            ),
            (),
        )

    def test_query_and_limit_are_bounded(self):
        reader = InventoryKnowledge(self.database)
        with self.assertRaises(ValidationError):
            reader.find(character="Testmage", query="")
        with self.assertRaises(ValidationError):
            reader.find(character="Testmage", query="staff", limit=0)


if __name__ == "__main__":
    unittest.main()
