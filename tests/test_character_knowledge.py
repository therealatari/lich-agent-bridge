import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from lich_agent_bridge.character_baseline import ensure_schema
from lich_agent_bridge.character_knowledge import CharacterKnowledge, category_freshness
from lich_agent_bridge.protocol import CharacterSnapshot


NOW = datetime(2026, 8, 31, 12, 0, 10, tzinfo=timezone.utc)


def character_snapshot(**changes):
    payload = {
        "character": "Testmage", "game": "GSIV", "generation": "generation-1",
        "sequence": 1, "observed_at": "2026-08-31T12:00:00Z",
        "character_data": {
            "info": {"source": "info", "observed_at": "2026-08-31T12:00:00Z",
                     "complete": True, "observed_level": 20,
                     "values": {"level": 20, "profession": "Sorcerer",
                                "stats": {"STR": {"value": 80, "bonus": 15, "enhanced_value": 85, "enhanced_bonus": 17}}}},
            "skills": {"source": "skills", "observed_at": "2026-08-31T12:00:00Z",
                       "complete": True, "observed_level": 20,
                       "values": {"skills": {"armoruse": {"ranks": 0, "bonus": 0}},
                                  "spell_circles": {"sorcerer": 30},
                                  "training_points": {"physical": 10, "mental": 20}}},
        },
    }
    payload.update(changes)
    return CharacterSnapshot.from_mapping(payload)


class CharacterKnowledgeTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = Path(self.temporary.name) / "inventory.sqlite3"
        connection = sqlite3.connect(self.database)
        ensure_schema(connection)
        connection.execute("INSERT INTO characters VALUES (1, 'GSIV', 'Testmage')")
        connection.execute("INSERT INTO character_facts VALUES (1, 'level', '19', 'historical audit', 'observed', '2026-08-01T00:00:00Z', NULL)")
        connection.commit()
        connection.close()
        self.adapter = CharacterKnowledge(self.database, now=lambda: NOW)

    def test_observed_categories_saved_without_rewriting_historical_audit(self):
        result = self.adapter.record(character_snapshot())
        self.assertEqual(result, {"status": "saved", "categories": ["info", "skills"]})
        found = self.adapter.find(character="TESTMAGE", game="GSIV", generation="generation-1")
        self.assertEqual(found["info"]["values"]["level"], 20)
        self.assertEqual(found["skills"]["values"]["skills"]["armoruse"]["ranks"], 0)
        self.assertTrue(found["skills"]["freshness"]["current"])
        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(connection.execute("SELECT value_json FROM character_facts WHERE field='level'").fetchone()[0], "19")
        finally:
            connection.close()

    def test_game_character_and_generation_are_not_confused(self):
        self.adapter.record(character_snapshot())
        self.assertEqual(self.adapter.find(character="Testscout", generation="generation-1"), {})
        self.assertEqual(self.adapter.find(character="Testmage", game="GST", generation="generation-1"), {})
        old = self.adapter.find(character="Testmage", generation="generation-2")
        self.assertFalse(old["info"]["freshness"]["current"])
        self.assertFalse(old["info"]["freshness"]["same_generation"])

    def test_stale_cached_or_future_values_are_never_saved_as_fresh(self):
        for kind in ("cached", "stale", "future", "incomplete"):
            data = character_snapshot().to_mapping()
            data["character_data"].pop("skills")
            category = data["character_data"]["info"]
            if kind == "cached":
                category.update(source="infomon_cache", observed_at=None, complete=False)
            elif kind == "stale":
                category["observed_at"] = "2026-08-31T11:00:00Z"
            elif kind == "future":
                category["observed_at"] = "2026-08-31T12:00:20Z"
            else:
                category["complete"] = False
            with self.subTest(kind=kind):
                self.assertEqual(self.adapter.record(CharacterSnapshot.from_mapping(data))["status"], "unchanged")
                self.assertEqual(self.adapter.find(character="Testmage"), {})

    def test_level_change_invalidates_preceding_skill_observation(self):
        data = character_snapshot().to_mapping()
        data["character_data"]["skills"]["observed_level"] = 19
        result = self.adapter.record(CharacterSnapshot.from_mapping(data))
        self.assertEqual(result["categories"], ["info"])
        self.assertNotIn("skills", self.adapter.find(character="Testmage"))

    def test_duplicate_admitted_snapshot_does_not_open_database_again(self):
        snapshot = character_snapshot()
        self.adapter.record(snapshot)
        with patch("lich_agent_bridge.character_knowledge.sqlite3.connect", side_effect=AssertionError("duplicate database work")):
            self.assertEqual(self.adapter.record(snapshot)["status"], "unchanged")

    def test_failure_remains_retryable_and_does_not_rollback_live_snapshot(self):
        with patch("lich_agent_bridge.character_knowledge.sqlite3.connect", side_effect=sqlite3.OperationalError("private-path-must-not-leak")):
            result = self.adapter.record(character_snapshot())
        self.assertEqual(result, {"status": "unavailable", "categories": []})
        self.assertEqual(self.adapter.record(character_snapshot())["status"], "saved")

    def test_category_save_failure_rolls_back_both_categories_and_retries(self):
        self.adapter.record(character_snapshot())
        connection = sqlite3.connect(self.database)
        connection.execute("""CREATE TRIGGER fail_skills BEFORE INSERT ON character_current_context
                            WHEN NEW.category = 'skills' BEGIN SELECT RAISE(ABORT, 'isolated failure'); END""")
        connection.commit()
        payload = character_snapshot().to_mapping()
        payload["observed_at"] = "2026-08-31T12:00:05Z"
        for category in payload["character_data"].values():
            category.update(observed_at=payload["observed_at"], observed_level=21)
        payload["character_data"]["info"]["values"]["level"] = 21
        updated = CharacterSnapshot.from_mapping(payload)
        try:
            self.assertEqual(self.adapter.record(updated)["status"], "unavailable")
            self.assertEqual(self.adapter.find(character="Testmage")["info"]["values"]["level"], 20)
            connection.execute("DROP TRIGGER fail_skills")
            connection.commit()
            self.assertEqual(self.adapter.record(updated)["status"], "saved")
            self.assertEqual(self.adapter.find(character="Testmage")["info"]["values"]["level"], 21)
        finally:
            connection.close()

    def test_older_observation_does_not_replace_newer_character_values(self):
        self.adapter.record(character_snapshot())
        payload = character_snapshot().to_mapping()
        payload["character_data"].pop("skills")
        payload["character_data"]["info"].update(observed_at="2026-08-31T11:59:59Z", observed_level=19)
        payload["character_data"]["info"]["values"]["level"] = 19
        self.assertEqual(self.adapter.record(CharacterSnapshot.from_mapping(payload))["status"], "unchanged")
        self.assertEqual(self.adapter.find(character="Testmage")["info"]["values"]["level"], 20)

    def test_missing_database_does_not_create_a_new_unconfigured_store(self):
        missing = Path(self.temporary.name) / "missing.sqlite3"
        adapter = CharacterKnowledge(missing)
        self.assertEqual(adapter.record(character_snapshot())["status"], "unconfigured")
        self.assertFalse(missing.exists())
        self.assertEqual(adapter.find(character="Testmage"), {})

    def test_current_observation_becomes_historical_without_changing_values(self):
        self.adapter.record(character_snapshot())
        later = CharacterKnowledge(self.database, now=lambda: NOW + timedelta(minutes=3))
        record = later.find(character="Testmage", generation="generation-1")["skills"]
        self.assertFalse(record["freshness"]["current"])
        self.assertEqual(record["freshness"]["authority"], "last_observation_only")
        self.assertEqual(record["values"]["skills"]["armoruse"]["ranks"], 0)

    def test_cached_record_age_is_unknown_not_zero(self):
        record = {"source": "infomon_cache", "observed_at": None, "complete": False, "generation": "generation-1"}
        freshness = category_freshness(record, generation="generation-1", now=NOW)
        self.assertIsNone(freshness["age_seconds"])
        self.assertFalse(freshness["current"])

    def test_malformed_durable_generation_does_not_escape_as_non_json_context(self):
        self.adapter.record(character_snapshot())
        connection = sqlite3.connect(self.database)
        try:
            connection.execute("UPDATE character_current_context SET generation = ?", (sqlite3.Binary(b'broken-generation'),))
            connection.commit()
        finally:
            connection.close()
        self.assertEqual(self.adapter.find(character="Testmage", generation="generation-1"), {})

    def test_unreadable_database_path_does_not_reject_admitted_live_state(self):
        with patch.object(Path, "is_file", side_effect=PermissionError("private path")):
            self.assertEqual(self.adapter.record(character_snapshot()), {"status": "unavailable", "categories": []})
            self.assertEqual(self.adapter.find(character="Testmage"), {})


if __name__ == "__main__":
    unittest.main()
