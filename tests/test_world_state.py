import threading
import unittest

from lich_agent_bridge.protocol import CharacterSnapshot, MeaningfulEvent
from lich_agent_bridge.world_state import StateConflict, WorldState


def snapshot(
    character="Testscout", generation="generation-1", sequence=1, *, room_id="100"
):
    return CharacterSnapshot.from_mapping(
        {
            "character": character,
            "generation": generation,
            "sequence": sequence,
            "observed_at": "2026-08-31T12:00:00Z",
            "room": {"id": room_id, "title": "Test Room"},
        }
    )


def event(character="Testscout", generation="generation-1", *, kind="threat"):
    return MeaningfulEvent.from_mapping(
        {
            "character": character,
            "generation": generation,
            "observed_at": "2026-08-31T12:00:01Z",
            "kind": kind,
            "summary": "A threat arrived.",
            "data": {"object_id": "123"},
        }
    )


class WorldStateTests(unittest.TestCase):
    def test_new_generation_replaces_active_and_old_generation_stays_stale(self):
        state = WorldState()
        state.publish_snapshot(snapshot())
        replaced = state.publish_snapshot(
            snapshot(generation="generation-2", sequence=1, room_id="200")
        )
        self.assertEqual(replaced["replaced_generation"], "generation-1")
        self.assertEqual(
            state.snapshot("testscout")["snapshot"]["generation"], "generation-2"
        )
        with self.assertRaisesRegex(StateConflict, "stale"):
            state.publish_snapshot(snapshot(generation="generation-1", sequence=2))

    def test_sequence_must_strictly_increase(self):
        state = WorldState()
        state.publish_snapshot(snapshot(sequence=2))
        with self.assertRaisesRegex(StateConflict, "strictly increase"):
            state.publish_snapshot(snapshot(sequence=2, room_id="101"))
        with self.assertRaisesRegex(StateConflict, "strictly increase"):
            state.publish_snapshot(snapshot(sequence=1, room_id="102"))

    def test_character_state_and_cursors_are_isolated(self):
        state = WorldState()
        state.publish_snapshot(snapshot(character="Testscout"))
        state.publish_snapshot(snapshot(character="Testmage", room_id="900"))
        state.publish_event(event(character="Testscout"))

        testscout = state.watch("TESTSCOUT", cursor=0, timeout=0)
        testmage = state.watch("testmage", cursor=0, timeout=0)
        self.assertEqual([item["character"] for item in testscout["events"]], ["Testscout", "Testscout"])
        self.assertEqual([item["character"] for item in testmage["events"]], ["Testmage"])
        self.assertEqual(state.snapshot("Testmage")["snapshot"]["room"]["id"], "900")

    def test_event_buffer_is_bounded_and_reports_truncated_cursor(self):
        state = WorldState(event_capacity=3)
        state.publish_snapshot(snapshot())
        for index in range(5):
            state.publish_event(event(kind=f"event-{index}"))
        page = state.watch("Testscout", cursor=0, timeout=0)
        self.assertEqual(len(page["events"]), 3)
        self.assertEqual([item["cursor"] for item in page["events"]], [4, 5, 6])
        self.assertTrue(page["truncated"])

    def test_watch_wakes_when_event_is_published(self):
        state = WorldState()
        first = state.publish_snapshot(snapshot())
        entered = threading.Event()
        result = {}

        def watch():
            entered.set()
            result.update(
                state.watch("Testscout", cursor=first["cursor"], timeout=1)
            )

        thread = threading.Thread(target=watch)
        thread.start()
        self.assertTrue(entered.wait(timeout=1))
        published = state.publish_event(event())
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.assertFalse(result["timed_out"])
        self.assertEqual(result["cursor"], published["cursor"])
        self.assertEqual(result["events"][0]["kind"], "threat")

    def test_watch_timeout_is_bounded_and_immediate_at_zero(self):
        state = WorldState()
        page = state.watch("Testscout", cursor=0, timeout=0)
        self.assertTrue(page["timed_out"])
        self.assertEqual(page["events"], [])

    def test_heartbeat_refreshes_snapshot_without_event_noise(self):
        state = WorldState()
        first = state.publish_snapshot(snapshot(sequence=1))
        heartbeat = CharacterSnapshot.from_mapping(
            {
                **snapshot(sequence=2).to_mapping(),
                "observed_at": "2026-08-31T12:00:10Z",
            }
        )
        second = state.publish_snapshot(heartbeat)
        self.assertEqual(second["cursor"], first["cursor"])
        self.assertTrue(
            state.watch("Testscout", cursor=first["cursor"], timeout=0)["timed_out"]
        )


if __name__ == "__main__":
    unittest.main()
