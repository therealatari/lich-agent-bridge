import sqlite3
import tempfile
import unittest
from pathlib import Path

from lich_agent_bridge.character_baseline import load_audit, persist


class CharacterBaselineTest(unittest.TestCase):
    def test_historical_sol_markers_remain_importable(self):
        text = """\
2025-01-01 14:11:02 +00: [sol]>info
2025-01-01 14:11:02 +00: Name: Testchar Race: Human  Profession: Warrior (not shown)
2025-01-01 14:11:02 +00: Gender: Male    Age: 1    Expr: 10    Level:  0
2025-01-01 14:11:02 +00: --- Sol: executed [def456]: info
2025-01-01 14:11:03 +00: [sol]>skills
2025-01-01 14:11:03 +00: Training Points: 1 Phy 2 Mnt
2025-01-01 14:11:03 +00: --- Sol: executed [abc123]: skills
"""
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "historical-sol.log"
            log.write_text(text)
            audit = load_audit("Testchar", log)

        self.assertEqual(audit.snapshot["identity"]["profession"], "Warrior")

    def test_interleaved_output_is_parsed_from_complete_log(self):
        text = """\
2025-01-01 14:10:58 +00: [lab]>skills
2025-01-01 14:10:59 +00:   Armor Use..........................|      15       3
2025-01-01 14:10:59 +00: [lab]>exp
2025-01-01 14:10:59 +00: Training Points: 4 Phy 7 Mnt
2025-01-01 14:10:59 +00: --- LAB: executed [abc123]: exp
2025-01-01 14:11:02 +00: [lab]>info
2025-01-01 14:11:02 +00: --- LAB: executed [def456]: info
2025-01-01 14:11:02 +00: Name: Testnovice Race: Human  Profession: Warrior (not shown)
2025-01-01 14:11:02 +00: Gender: Female    Age: 21    Expr: 15    Level:  0
2025-01-01 14:11:02 +00:     Strength (STR):    70 (15)    ...   70 (15)
2025-01-01 14:11:02 +00: Health: 25/25     Mana: 2/2     Stamina: 30/30     Spirit: 7/7
2025-01-01 14:11:02 +00: You have no guild affiliation.
2025-01-01 14:11:02 +00:    You are not a member of any society at this time.
2025-01-01 14:15:39 +00: In the canvas bag you see a brass ring and a glass vial.
"""
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "audit.log"
            log.write_text(text)
            audit = load_audit("Testnovice", log)
            snapshot = audit.snapshot
            self.assertEqual(snapshot["identity"]["profession"], "Warrior")
            self.assertEqual(snapshot["level"], 0)
            self.assertEqual(snapshot["training_points"]["physical"], 4)
            self.assertEqual(snapshot["skills"]["Armor Use"]["ranks"], 3)
            self.assertEqual(snapshot["resources"]["max_stamina"], 30)
            self.assertEqual(snapshot["guild"], "No Guild affiliation")
            self.assertEqual(snapshot["container_observations"][0]["status"], "protected_pending_item_audit")

    def test_persistence_uses_shared_character_tables(self):
        text = """\
2025-01-01 14:11:02 +00: [lab]>info
2025-01-01 14:11:02 +00: Name: Testchar Race: Human  Profession: Warrior (not shown)
2025-01-01 14:11:02 +00: Gender: Male    Age: 1    Expr: 10    Level:  0
2025-01-01 14:11:02 +00: --- LAB: executed [def456]: info
2025-01-01 14:10:58 +00: [lab]>skills
2025-01-01 14:10:59 +00: Training Points: 1 Phy 2 Mnt
2025-01-01 14:10:59 +00: --- LAB: executed [abc123]: skills
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "audit.log"
            database = root / "inventory.sqlite3"
            log.write_text(text)
            baseline_id = persist(database, load_audit("Testchar", log))
            connection = sqlite3.connect(database)
            try:
                self.assertGreater(baseline_id, 0)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM character_baselines").fetchone()[0], 1)
                self.assertEqual(
                    connection.execute("SELECT value_json FROM character_facts WHERE field='identity.profession'").fetchone()[0],
                    '"Warrior"',
                )
                self.assertGreater(
                    connection.execute("SELECT COUNT(*) FROM character_observations WHERE command='raw-log'").fetchone()[0],
                    0,
                )
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
