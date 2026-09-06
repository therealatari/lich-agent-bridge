"""Fictional profiles for isolated tests; never loaded as application defaults."""

from lich_agent_bridge.watchers import CharacterProfile


TESTMAGE_PROFILE = CharacterProfile(
    character="Testmage",
    expected_hand_item_names=frozenset({"plain ash staff", "ash staff"}),
    expected_hand_item_label="plain ash staff",
    encumbrance_warning=3,
    encumbrance_emergency=5,
)
TESTSCOUT_PROFILE = CharacterProfile(
    character="Testscout",
    expected_hand_item_names=frozenset({"iron hammer", "simple iron hammer"}),
    expected_hand_item_label="iron hammer",
)
TEST_PROFILES = (TESTMAGE_PROFILE, TESTSCOUT_PROFILE)
