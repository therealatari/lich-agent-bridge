"""Registered character recon exercised through a real, isolated ActionBroker."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
import unittest
import threading
import time
from unittest.mock import Mock

from lich_agent_bridge.actions import ActionApproval, ActionBroker, ActionContext, ActionControl, ActionProposal, ActionResult
from lich_agent_bridge.errors import ValidationError
from lich_agent_bridge.operations import CapabilityRunner
from lich_agent_bridge.session_hub import SessionHub, WorldStateOperationAdapter

from .test_operations import FakeClock, FakeEvidence, FakeState


class ReconState(FakeState):
    def __init__(self):
        super().__init__()
        self.fresh = True
        self.sequence = 1
        self.character_data = {}

    def snapshot(self, character):
        return replace(super().snapshot(character), character_data=deepcopy(self.character_data))


class CharacterReconOperationTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.state = ReconState()
        self.broker = ActionBroker(clock=self.clock)
        self.broker.admit_generation("Testmage", "generation-1")
        self.broker.control(ActionControl("Testmage", True))
        self.proposals = []
        self.commands = []
        self.capture = True
        self.after = None
        self.outcome = "completed"
        self.runner = CapabilityRunner(
            actions=self.broker, state=self.state, evidence=FakeEvidence(),
            clock=self.clock, sleeper=self.clock.sleep, step_hook=self.drive,
        )

    def record(self, category, *, level=20, stamp=None):
        value = {
            "source": category, "complete": True,
            "observed_at": datetime.fromtimestamp(self.clock() if stamp is None else stamp, UTC).isoformat(),
            "values": ({"level": level, "stats": {"STR": {"value": 100, "bonus": 25}}}
                       if category == "info" else {"skills": {"arcane_symbols": {"ranks": 21, "bonus": 191}}, "spell_circles": {"sorcerer": 30}}),
        }
        if category == "skills":
            value["observed_level"] = level
        return value

    def drive(self, broker, proposal, snapshot):
        self.proposals.append(proposal)
        commands = proposal.get("commands") or [proposal["command"]]
        self.commands.extend(commands)
        context = ActionContext(snapshot.character, snapshot.room_id, snapshot.generation)
        action = broker.poll(context)
        if action["status"] == "confirmation_required":
            broker.approve(ActionApproval(action["action_id"], snapshot.character, snapshot.room_id,
                                          approval_mode="manual", generation=snapshot.generation))
            action = broker.poll(context)
        self.clock.sleep(0.001)
        if self.capture:
            self.state.sequence += 1
            for category in commands:
                self.state.character_data[category] = self.record(category)
        broker.record_result(ActionResult(action["action_id"], snapshot.character, self.outcome,
                                         "sent by fake bridge", generation=snapshot.generation))
        if self.after:
            self.after()

    def perform(self, args=None, timeout=2):
        return self.runner.perform("Testmage", "character.recon", args, timeout_seconds=timeout)

    def test_default_recon_is_one_approved_sequence_and_requires_new_records(self):
        operation = self.perform()
        self.assertEqual(operation.status, "succeeded", operation.explanation)
        self.assertEqual(self.commands, ["info", "skills"])
        self.assertEqual(len(self.proposals), 1)
        self.assertEqual([item.method for item in operation.evidence], ["character.info", "character.skills"])
        self.assertEqual(len({item.action_id for item in operation.evidence}), 1)
        for item in operation.evidence:
            self.assertEqual(item.facts["source"], item.facts["category"])
            self.assertTrue(item.facts["complete"])
        mapped = SessionHub._operation_mapping(operation)
        self.assertEqual(mapped["end_state"]["character_data"]["info"]["values"]["level"], 20)

    def test_single_info_uses_scalar_and_tolerates_old_skills_level(self):
        self.state.character_data["skills"] = self.record("skills", level=19, stamp=999)
        operation = self.perform({"categories": ["info"]})
        self.assertEqual(operation.status, "succeeded", operation.explanation)
        self.assertEqual(self.commands, ["info"])
        self.assertEqual(self.proposals[0]["command"], "info")

    def test_reverse_requested_categories_still_observe_info_before_skills(self):
        operation = self.perform({"categories": ["skills", "info"]})
        self.assertEqual(operation.status, "succeeded", operation.explanation)
        self.assertEqual(self.commands, ["info", "skills"])

    def test_single_skills_matches_known_level(self):
        self.state.character_data["info"] = self.record("info", stamp=999)
        operation = self.perform({"categories": ["skills"]})
        self.assertEqual(operation.status, "succeeded", operation.explanation)
        self.assertEqual(self.commands, ["skills"])

    def test_sent_without_records_times_out(self):
        self.capture = False
        operation = self.perform()
        self.assertEqual(operation.status, "timed_out", operation.explanation)
        self.assertFalse(operation.evidence)

    def test_waits_for_post_command_snapshot_before_reporting_success(self):
        self.capture = False
        def publish_after_sleep(seconds):
            self.clock.sleep(seconds)
            if self.clock() >= 1000.02:
                self.state.sequence = 2
                self.state.character_data = {name: self.record(name) for name in ("info", "skills")}
        self.runner._sleeper = publish_after_sleep
        operation = self.perform()
        self.assertEqual(operation.status, "succeeded", operation.explanation)
        self.assertGreaterEqual(operation.ended_at, 1000.02)

    def test_session_adapter_copies_typed_character_records(self):
        records = {"info": self.record("info"), "skills": self.record("skills")}
        world = Mock()
        world.snapshot.return_value = {
            "freshness": {"stale": False},
            "snapshot": {"character": "Testmage", "generation": "generation-1", "sequence": 2,
                         "room": {"id": "1234"}, "character_data": records},
        }
        state = WorldStateOperationAdapter(world, Mock()).snapshot("Testmage")
        self.assertEqual(state.character_data, records)
        records["info"]["values"]["level"] = 21
        self.assertEqual(state.character_data["info"]["values"]["level"], 20)

    def test_cached_or_incomplete_capture_never_proves_completion(self):
        for change in ({"source": "infomon_cache"}, {"complete": False}, {"observed_at": None}, {"values": {}}):
            with self.subTest(change=change):
                self.after = lambda change=change: self.state.character_data["skills"].update(change)
                operation = self.perform()
                self.assertEqual(operation.status, "timed_out", operation.explanation)
                self.assertFalse(operation.evidence)

    def test_pre_request_and_unchanged_capture_timestamps_fail(self):
        for stamp in (999, 1000):
            with self.subTest(stamp=stamp):
                self.clock.now = 1000
                self.state.character_data["skills"] = self.record("skills", stamp=stamp)
                self.after = lambda stamp=stamp: self.state.character_data["skills"].update(self.record("skills", stamp=stamp))
                operation = self.perform()
                self.assertEqual(operation.status, "timed_out", operation.explanation)

    def test_state_sequence_must_advance(self):
        self.after = lambda: setattr(self.state, "sequence", 1)
        operation = self.perform()
        self.assertEqual(operation.status, "timed_out", operation.explanation)

    def test_inconsistent_skill_observed_level_cannot_succeed(self):
        self.after = lambda: self.state.character_data["skills"].update(observed_level=19)
        operation = self.perform()
        self.assertEqual(operation.status, "timed_out", operation.explanation)

    def test_missing_skill_observed_level_cannot_succeed_when_info_level_known(self):
        self.after = lambda: self.state.character_data["skills"].pop("observed_level")
        operation = self.perform()
        self.assertEqual(operation.status, "timed_out", operation.explanation)
        self.assertFalse(operation.evidence)

    def test_future_capture_is_rejected_even_when_within_operation_deadline(self):
        for future_seconds in (1, 30):
            with self.subTest(future_seconds=future_seconds):
                self.after = lambda future_seconds=future_seconds: self.state.character_data["skills"].update(
                    self.record("skills", stamp=self.clock() + future_seconds)
                )
                operation = self.perform()
                self.assertEqual(operation.status, "failed", operation.explanation)
                self.assertIn("future", operation.explanation)
                self.assertFalse(operation.evidence)

    def test_room_and_generation_changes_fail(self):
        for field in ("room_id", "generation"):
            with self.subTest(field=field):
                self.state.room_id, self.state.generation = "1234", "generation-1"
                self.after = lambda field=field: setattr(self.state, field, "changed")
                operation = self.perform()
                self.assertEqual(operation.status, "failed", operation.explanation)
                self.assertFalse(operation.evidence)

    def test_actions_disabled_and_stale_start_issue_nothing(self):
        self.broker.control(ActionControl("Testmage", False))
        operation = self.perform()
        self.assertEqual(operation.status, "failed", operation.explanation)
        self.assertFalse(self.commands)
        self.broker.control(ActionControl("Testmage", True))
        self.state.fresh = False
        operation = self.perform()
        self.assertEqual(operation.status, "failed", operation.explanation)
        self.assertFalse(self.commands)

    def test_broker_failure_is_not_overridden_by_populated_state(self):
        self.outcome = "failed"
        operation = self.perform()
        self.assertEqual(operation.status, "failed", operation.explanation)
        self.assertFalse(operation.evidence)

    def test_invalid_arguments_never_reach_broker(self):
        for args in ({"command": "skills"}, {"categories": []}, {"categories": ["info", "info"]},
                     {"categories": ["skills", "drop"]}, {"categories": "info"}, {"categories": [1]}):
            with self.subTest(args=args):
                operation = self.perform(args)
                self.assertEqual(operation.status, "failed", operation.explanation)
        self.assertFalse(self.commands)

    def test_recon_caps_long_requested_timeout(self):
        self.capture = False
        operation = self.perform(timeout=100)
        self.assertEqual(operation.status, "timed_out", operation.explanation)
        self.assertLessEqual(operation.deadline - operation.requested_at, 20)

    def test_fractional_deadline_cannot_leave_an_approvable_action_after_timeout(self):
        self.runner._step_hook = lambda _broker, proposal, _snapshot: self.proposals.append(proposal)
        operation = self.perform(timeout=1.25)
        proposal = self.proposals[0]
        self.assertLessEqual(proposal["expires_at"], operation.deadline)
        self.clock.now = operation.deadline + 0.001
        self.assertEqual(self.broker.get(proposal["action_id"])["status"], "expired")
        self.assertFalse(operation.evidence)

    def test_subsecond_recon_deadline_never_submits(self):
        operation = self.perform(timeout=0.5)
        self.assertEqual(operation.status, "timed_out")
        self.assertFalse(self.proposals)

    def test_interrupt_revokes_owned_pending_action_but_not_unrelated_work(self):
        for args in (None, {"categories": ["info"]}):
            with self.subTest(args=args):
                ready = threading.Event()
                self.runner._step_hook = lambda _broker, proposal, _snapshot: (self.proposals.append(proposal), ready.set())
                self.runner._sleeper = time.sleep
                operation = self.runner.start("Testmage", "character.recon", args, timeout_seconds=10)
                self.assertTrue(ready.wait(1))
                proposal = self.proposals[-1]
                unrelated = self.broker.submit(ActionProposal(character="Testmage", command="look"))
                self.runner.interrupt(operation.operation_id)
                self.assertEqual(self.broker.get(proposal["action_id"])["status"], "cancelled")
                with self.assertRaises(ValidationError):
                    self.broker.approve(ActionApproval(proposal["action_id"], "Testmage", self.state.room_id))
                self.assertEqual(self.broker.get(unrelated["action_id"])["status"], "queued")
                self.broker.cancel(unrelated["action_id"], character="Testmage", generation="generation-1")
                self.assertIsNone(self.broker.poll(ActionContext("Testmage", self.state.room_id)))
                self.wait_terminal(operation)
                self.assertEqual(operation.status, "interrupted", operation.explanation)

    def wait_terminal(self, operation):
        deadline = time.monotonic() + 1
        while operation.ended_at is None and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertIsNotNone(operation.ended_at)

    def test_interrupt_while_submit_is_returning_cancels_before_step_hook(self):
        created, release = threading.Event(), threading.Event()
        original_submit = self.broker.submit
        def delayed_submit(proposal):
            action = original_submit(proposal)
            self.proposals.append(action)
            created.set()
            release.wait(1)
            return action
        self.broker.submit = delayed_submit
        hook = Mock()
        self.runner._step_hook = hook
        operation = self.runner.start("Testmage", "character.recon", timeout_seconds=10)
        try:
            self.assertTrue(created.wait(1))
            self.runner.interrupt(operation.operation_id)
        finally:
            release.set()
        self.wait_terminal(operation)
        self.assertEqual(operation.status, "interrupted", operation.explanation)
        self.assertEqual(self.broker.get(self.proposals[0]["action_id"])["status"], "cancelled")
        hook.assert_not_called()

    def test_timeout_revokes_pending_recon_even_when_broker_expiry_is_later(self):
        # Model-question deadlines can shorten the operation after submission.
        def shorten(_broker, proposal, _snapshot):
            self.proposals.append(proposal)
            self.runner.get(next(iter(self.runner._operations))).deadline = self.clock() + 0.01
        self.runner._step_hook = shorten
        operation = self.perform(timeout=10)
        self.assertEqual(operation.status, "timed_out", operation.explanation)
        self.assertEqual(self.broker.get(self.proposals[0]["action_id"])["status"], "cancelled")

    def test_interrupt_after_dispatch_reports_that_commands_cannot_be_unsent(self):
        def dispatch_then_interrupt(broker, proposal, snapshot):
            self.proposals.append(proposal)
            broker.approve(ActionApproval(proposal["action_id"], "Testmage", snapshot.room_id))
            broker.poll(ActionContext("Testmage", snapshot.room_id))
            operation = self.runner.get(next(iter(self.runner._operations)))
            self.runner.interrupt(operation.operation_id)
        self.runner._step_hook = dispatch_then_interrupt
        operation = self.perform()
        self.assertEqual(operation.status, "interrupted", operation.explanation)
        self.assertEqual(self.broker.get(self.proposals[0]["action_id"])["status"], "dispatched")
        self.assertTrue(any("cannot be unsent" in alert for alert in operation.alerts))
        self.assertFalse(operation.evidence)
        self.assertFalse(self.runner._recon_actions)

    def test_bound_generation_replacement_before_admission_never_submits(self):
        self.state.generation = "generation-2"
        self.broker.admit_generation("Testmage", "generation-2")
        for asynchronous in (False, True):
            with self.subTest(asynchronous=asynchronous):
                call = self.runner.start if asynchronous else self.runner.perform
                operation = call("Testmage", "character.recon", expected_generation="generation-1")
                self.wait_terminal(operation)
                self.assertEqual(operation.status, "failed", operation.explanation)
                self.assertIn("stale session generation", operation.explanation)
                self.assertFalse(self.proposals)

    def test_interrupting_terminal_operation_does_not_cancel_successor(self):
        previous = self.perform()
        self.assertEqual(previous.status, "succeeded")
        ready = threading.Event()
        self.runner._sleeper = time.sleep
        self.runner._step_hook = lambda _broker, proposal, _snapshot: (self.proposals.append(proposal), ready.set())
        successor = self.runner.start("Testmage", "character.recon", timeout_seconds=10)
        try:
            self.assertTrue(ready.wait(1))
            proposal = self.proposals[-1]
            self.runner.interrupt(previous.operation_id)
            self.assertEqual(self.broker.get(proposal["action_id"])["status"], "confirmation_required")
        finally:
            self.runner.interrupt(successor.operation_id)
        self.wait_terminal(successor)
