import unittest

from lich_agent_bridge.protocol import CharacterSnapshot
from lich_agent_bridge.watchers import (
    CharacterProfile,
    WatcherReducer,
)
from .synthetic_profiles import TEST_PROFILES, TESTMAGE_PROFILE, TESTSCOUT_PROFILE


def snapshot(character, sequence, *, generation="generation-1", **fields):
    return CharacterSnapshot.from_mapping(
        {
            "character": character,
            "generation": generation,
            "sequence": sequence,
            "observed_at": f"2026-08-31T12:00:{sequence:02d}Z",
            **fields,
        }
    )


def empty_hands():
    return {"right": None, "left": None}


class WatcherReducerTests(unittest.TestCase):
    def test_testscout_maul_missing_deduplicates_and_clears_when_present(self):
        reducer = WatcherReducer(TEST_PROFILES, corpse_persistence_snapshots=2)

        first = reducer.reduce(snapshot("Testscout", 1, hands=empty_hands()))
        repeated = reducer.reduce(snapshot("Testscout", 2, hands=empty_hands()))
        cleared = reducer.reduce(
            snapshot(
                "Testscout",
                3,
                hands={
                    "right": {
                        "id": "99",
                        "name": "a simple iron hammer",
                    },
                    "left": None,
                },
            )
        )

        self.assertEqual([alert.code for alert in first], ["expected_weapon_missing"])
        self.assertEqual(repeated, ())
        self.assertEqual(cleared[0].code, "expected_weapon_missing")
        self.assertEqual(cleared[0].status, "cleared")
        self.assertEqual(reducer.active("Testscout"), ())

    def test_testmage_staff_missing_and_configured_encumbrance_are_critical(self):
        reducer = WatcherReducer(TEST_PROFILES)
        baseline = snapshot(
            "Testmage",
            1,
            encumbrance=0,
            hands={
                "right": {"id": "77", "name": "a plain ash staff"},
                "left": None,
            },
        )
        self.assertEqual(reducer.reduce(baseline), ())

        alerts = reducer.reduce(
            snapshot("Testmage", 2, encumbrance=5, hands=empty_hands())
        )
        by_code = {alert.code: alert for alert in alerts}
        self.assertEqual(by_code["expected_weapon_missing"].severity, "critical")
        self.assertEqual(by_code["encumbrance"].severity, "critical")

    def test_generation_change_resets_alert_and_temporal_history(self):
        reducer = WatcherReducer(TEST_PROFILES)
        reducer.reduce(snapshot("Testscout", 1, hands=empty_hands()))
        self.assertTrue(reducer.active("Testscout"))
        self.assertTrue(reducer.history("Testscout"))

        emitted = reducer.reduce(
            snapshot(
                "Testscout",
                1,
                generation="generation-2",
                hands={
                    "right": {"id": "new-id", "name": "an iron hammer"},
                    "left": None,
                },
            )
        )
        self.assertEqual(emitted, ())
        self.assertEqual(reducer.active("Testscout"), ())
        self.assertEqual(reducer.history("Testscout"), ())

    def test_defensive_spell_alert_requires_known_presence_and_unknown_preserves(self):
        profile = CharacterProfile(
            character="Testmage",
            required_defensive_spell_ids=frozenset({"101"}),
        )
        reducer = WatcherReducer((profile,))

        self.assertEqual(
            reducer.reduce(snapshot("Testmage", 1, active_spells=[])), ()
        )
        self.assertEqual(
            reducer.reduce(
                snapshot("Testmage", 2, active_spells=[{"id": "101"}])
            ),
            (),
        )
        self.assertEqual(
            reducer.reduce(snapshot("Testmage", 3, active_spells=None)), ()
        )
        dropped = reducer.reduce(snapshot("Testmage", 4, active_spells=[]))
        self.assertEqual(dropped[0].code, "defensive_spell_dropped:101")
        self.assertEqual(dropped[0].evidence["spell_id"], "101")

        restored = reducer.reduce(
            snapshot("Testmage", 5, active_spells=[{"id": "101"}])
        )
        self.assertEqual(restored[0].status, "cleared")

    def test_owning_script_exit_alerts_only_while_lane_remains_active(self):
        reducer = WatcherReducer(TEST_PROFILES)
        reducer.reduce(
            snapshot(
                "Testscout",
                1,
                scripts=["bigshot"],
                owners={"combat": "bigshot"},
            )
        )
        exited = reducer.reduce(
            snapshot(
                "Testscout",
                2,
                scripts=[],
                owners={"combat": "bigshot"},
            )
        )
        self.assertEqual(exited[0].code, "owning_script_missing:combat:bigshot")
        self.assertEqual(exited[0].evidence["lane"], "combat")
        self.assertEqual(
            reducer.reduce(
                snapshot(
                    "Testscout",
                    3,
                    scripts=[],
                    owners={"combat": "bigshot"},
                )
            ),
            (),
        )
        cleared = reducer.reduce(
            snapshot("Testscout", 4, scripts=[], owners={"combat": None})
        )
        self.assertEqual(cleared[0].status, "cleared")

    def test_owning_script_exit_is_seen_when_producer_releases_lane(self):
        reducer = WatcherReducer(TEST_PROFILES)
        reducer.reduce(
            snapshot(
                "Testscout",
                1,
                scripts=["bigshot"],
                owners={"combat": "bigshot"},
            )
        )
        exited = reducer.reduce(
            snapshot(
                "Testscout",
                2,
                scripts=[],
                owners={"combat": None},
            )
        )
        self.assertEqual(exited[0].code, "owning_script_missing:combat:bigshot")
        self.assertEqual(exited[0].status, "active")
        cleared = reducer.reduce(
            snapshot("Testscout", 3, scripts=[], owners={"combat": None})
        )
        self.assertEqual(cleared[0].status, "cleared")

    def test_corpse_persistence_alerts_then_clears(self):
        reducer = WatcherReducer(TEST_PROFILES, corpse_persistence_snapshots=2)
        corpse = {"id": "500", "noun": "mastiff", "name": "a stone mastiff"}
        first = reducer.reduce(
            snapshot("Testmage", 1, nearby={"corpses": [corpse]})
        )
        second = reducer.reduce(
            snapshot("Testmage", 2, nearby={"corpses": [corpse]})
        )
        third = reducer.reduce(
            snapshot("Testmage", 3, nearby={"corpses": [corpse]})
        )
        cleared = reducer.reduce(
            snapshot("Testmage", 4, nearby={"corpses": []})
        )

        self.assertEqual(first, ())
        self.assertEqual(second[0].code, "unlooted_corpse:500")
        self.assertEqual(second[0].evidence["consecutive_snapshots"], 2)
        self.assertEqual(third, ())
        self.assertEqual(cleared[0].status, "cleared")

    def test_unknown_nearby_breaks_unconfirmed_consecutive_corpse_count(self):
        reducer = WatcherReducer(TEST_PROFILES, corpse_persistence_snapshots=2)
        corpse = {"id": "500", "noun": "mastiff"}
        reducer.reduce(snapshot("Testmage", 1, nearby={"corpses": [corpse]}))
        reducer.reduce(snapshot("Testmage", 2, nearby=None))
        after_unknown = reducer.reduce(
            snapshot("Testmage", 3, nearby={"corpses": [corpse]})
        )
        persisted = reducer.reduce(
            snapshot("Testmage", 4, nearby={"corpses": [corpse]})
        )
        self.assertEqual(after_unknown, ())
        self.assertEqual(persisted[0].code, "unlooted_corpse:500")

    def test_warning_and_emergency_encumbrance_thresholds_cross(self):
        profile = CharacterProfile(
            character="Threshold",
            encumbrance_warning=1,
            encumbrance_emergency=2,
        )
        reducer = WatcherReducer((profile,))
        self.assertEqual(
            reducer.reduce(snapshot("Threshold", 1, encumbrance=0)), ()
        )
        warning = reducer.reduce(snapshot("Threshold", 2, encumbrance=1))
        self.assertEqual(warning[0].severity, "warning")
        self.assertEqual(
            reducer.reduce(snapshot("Threshold", 3, encumbrance=1)), ()
        )
        emergency = reducer.reduce(snapshot("Threshold", 4, encumbrance=2))
        self.assertEqual(emergency[0].severity, "critical")
        cleared = reducer.reduce(snapshot("Threshold", 5, encumbrance=0))
        self.assertEqual(cleared[0].status, "cleared")

    def test_dead_stunned_and_severe_wounds_are_structured_and_clear(self):
        reducer = WatcherReducer(TEST_PROFILES)
        alerts = reducer.reduce(
            snapshot(
                "Testscout",
                1,
                dead=True,
                stunned=True,
                wounds={"rightArm": {"wound": 2, "scar": 0}},
            )
        )
        by_code = {alert.code: alert for alert in alerts}
        self.assertEqual(set(by_code), {"dead", "stunned", "severe_wounds"})
        self.assertEqual(by_code["dead"].severity, "critical")
        self.assertEqual(by_code["severe_wounds"].evidence["wounds"], {"rightArm": 2})
        for alert in alerts:
            self.assertEqual(alert.character, "Testscout")
            self.assertEqual(alert.generation, "generation-1")
            self.assertEqual(alert.snapshot_sequence, 1)

        cleared = reducer.reduce(
            snapshot("Testscout", 2, dead=False, stunned=False, wounds={})
        )
        self.assertEqual({alert.status for alert in cleared}, {"cleared"})

    def test_active_and_history_are_bounded(self):
        profile = CharacterProfile(character="Bounded")
        reducer = WatcherReducer((profile,), active_limit=2, history_limit=3)
        first = reducer.reduce(
            snapshot(
                "Bounded",
                1,
                dead=True,
                stunned=True,
                wounds={"head": {"wound": 3}},
            )
        )
        self.assertEqual(len(first), 2)
        self.assertEqual(len(reducer.active("Bounded")), 2)

        reducer.reduce(
            snapshot("Bounded", 2, dead=False, stunned=False, wounds={})
        )
        reducer.reduce(snapshot("Bounded", 3, dead=True, stunned=False, wounds={}))
        self.assertLessEqual(len(reducer.active("Bounded")), 2)
        self.assertLessEqual(len(reducer.history("Bounded")), 3)

    def test_synthetic_profiles_do_not_invent_required_spells(self):
        self.assertEqual(TESTSCOUT_PROFILE.required_defensive_spell_ids, frozenset())
        self.assertEqual(TESTMAGE_PROFILE.required_defensive_spell_ids, frozenset())

    def test_default_reducer_contains_no_character_profiles(self):
        reducer = WatcherReducer()
        self.assertFalse(reducer.supports("Testmage"))
        self.assertFalse(reducer.supports("SomeOtherPlayer"))


if __name__ == "__main__":
    unittest.main()
