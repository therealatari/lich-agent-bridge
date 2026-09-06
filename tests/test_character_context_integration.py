"""Real admission, persistence and prompt integration; no live game transport."""
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from lich_agent_bridge.character_knowledge import CharacterKnowledge
from lich_agent_bridge.protocol import AskRequest, CharacterSnapshot
from lich_agent_bridge.server import ServerConfig, build_server
from lich_agent_bridge.world_state import StateConflict
from .fakes import RecordingModel
from .test_character_knowledge import character_snapshot
from .test_server import StaticInventory, StaticKnowledge


class CharacterContextIntegrationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / 'inventory.sqlite3'
        sqlite3.connect(self.database).close()
        self.adapter = CharacterKnowledge(self.database)
        self.model = RecordingModel('A grounded response.')
        self.server = build_server(
            ServerConfig(port=0), model=self.model,
            inventory=StaticInventory(), knowledge=StaticKnowledge(),
            character_knowledge=self.adapter, action_token='a' * 64,
            timing=lambda _sample: None,
        )
        self.addCleanup(self.server.server_close)

    def snapshot(self, **changes):
        data = character_snapshot().to_mapping()
        stamp = datetime.now(timezone.utc).isoformat()
        data['observed_at'] = stamp
        for category in data['character_data'].values():
            category['observed_at'] = stamp
        data.update(changes)
        return CharacterSnapshot.from_mapping(data)

    def test_accepted_live_data_updates_database_and_actual_model_prompt(self):
        self.server.publish_snapshot(self.snapshot())
        self.assertEqual(self.server.character_database_status, 'saved')
        stored = self.adapter.find(character='Testmage', generation='generation-1')
        self.assertEqual(stored['info']['values']['level'], 20)
        self.server.copilot.ask(AskRequest('Testmage', 'How long does it last with my skills?'))
        prompt = self.model.calls[-1]['input_text']
        self.assertIn('CHARACTER BUILD', prompt)
        self.assertIn('sorcerer', prompt)
        self.assertIn('30', prompt)
        self.assertIn('current_character_observation', prompt)

    def test_unobserved_cache_is_available_but_not_persisted_as_current(self):
        data = self.snapshot().to_mapping()
        for category in data['character_data'].values():
            category.update(source='infomon_cache', observed_at=None, complete=False)
        self.server.publish_snapshot(CharacterSnapshot.from_mapping(data))
        self.assertEqual(self.adapter.find(character='Testmage'), {})
        self.server.copilot.ask(AskRequest('Testmage', 'What are my skills?'))
        prompt = self.model.calls[-1]['input_text']
        self.assertIn('last_observation_only', prompt)
        self.assertIn('30', prompt)

    def test_rejected_old_sequence_cannot_update_character_database(self):
        self.server.publish_snapshot(self.snapshot(sequence=2))
        with patch.object(self.adapter, 'record', wraps=self.adapter.record) as record:
            with self.assertRaises(StateConflict):
                self.server.publish_snapshot(self.snapshot(sequence=1))
            record.assert_not_called()

    def test_database_failure_does_not_reject_live_state(self):
        with patch('lich_agent_bridge.character_knowledge.sqlite3.connect',
                   side_effect=sqlite3.OperationalError('private diagnostic')):
            self.server.publish_snapshot(self.snapshot())
        self.assertEqual(self.server.character_database_status, 'unavailable')
        current = self.server.world_state.snapshot('Testmage')['snapshot']
        self.assertEqual(current['character_data']['info']['values']['level'], 20)
        self.assertEqual(self.adapter.record(self.snapshot())['status'], 'saved')

    def test_other_character_never_receives_the_live_build(self):
        self.server.publish_snapshot(self.snapshot())
        self.server.copilot.ask(AskRequest('Testscout', 'What are my skills?'))
        self.assertNotIn('sorcerer', self.model.calls[-1]['input_text'])
