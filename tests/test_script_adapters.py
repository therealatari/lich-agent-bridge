import unittest

from lich_agent_bridge.errors import ValidationError
from lich_agent_bridge.script_adapters import (
    BIGSHOT_ADAPTER,
    ELOOT_ADAPTER,
    GO2_ADAPTER,
    script_adapter,
)


class ScriptAdapterTests(unittest.TestCase):
    def test_registry_exposes_only_exact_registered_scripts_and_lanes(self):
        self.assertIs(script_adapter("go2"), GO2_ADAPTER)
        self.assertIs(script_adapter("Bigshot"), BIGSHOT_ADAPTER)
        self.assertIs(script_adapter("eloot"), ELOOT_ADAPTER)
        self.assertEqual(GO2_ADAPTER.ownership_lanes, frozenset({"movement"}))
        self.assertEqual(
            BIGSHOT_ADAPTER.ownership_lanes,
            frozenset({"movement", "combat"}),
        )
        self.assertEqual(ELOOT_ADAPTER.ownership_lanes, frozenset({"inventory"}))
        with self.assertRaisesRegex(ValidationError, "unregistered"):
            script_adapter("arbitrary-script")

    def test_exact_entrypoints_build_only_allowed_commands(self):
        self.assertEqual(GO2_ADAPTER.command("travel", destination=123), "go2 123")
        self.assertEqual(BIGSHOT_ADAPTER.command("start"), "bigshot start")
        self.assertEqual(BIGSHOT_ADAPTER.command("stop"), "bigshot stop")
        self.assertEqual(
            ELOOT_ADAPTER.command("loot_current_room"), "eloot loot"
        )
        self.assertEqual(ELOOT_ADAPTER.command("stop"), "eloot stop")
        with self.assertRaises(ValidationError):
            GO2_ADAPTER.command("travel", destination="123;kill all")
        with self.assertRaises(ValidationError):
            BIGSHOT_ADAPTER.command("restart")
        with self.assertRaises(ValidationError):
            ELOOT_ADAPTER.command("sell")


if __name__ == "__main__":
    unittest.main()
