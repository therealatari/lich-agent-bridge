"""Deterministic cancellation ownership semantics; no model or game needed."""

import threading
import unittest

from lich_agent_bridge.errors import QuestionInvalidated, QuestionTimeout
from lich_agent_bridge.question import QuestionControl


class QuestionControlTests(unittest.TestCase):
    def test_cancel_runs_cleanup_before_return_and_keeps_first_reason(self):
        control = QuestionControl(10)
        calls = []
        control.on_cancel(lambda: calls.append("owned recon cancelled"))
        control.cancel("invalidated")
        self.assertEqual(calls, ["owned recon cancelled"])
        control.cancel("timeout")
        self.assertEqual(control.reason, "invalidated")
        self.assertEqual(len(calls), 1)
        with self.assertRaises(QuestionInvalidated):
            control.remaining()

    def test_registration_after_cancel_runs_immediately_and_removal_is_safe(self):
        control = QuestionControl(10)
        control.cancel("timeout")
        calls = []
        remove = control.on_cancel(lambda: calls.append("late operation"))
        self.assertEqual(calls, ["late operation"])
        remove()
        remove()
        control.cancel("invalidated")
        self.assertEqual(calls, ["late operation"])
        with self.assertRaises(QuestionTimeout):
            control.remaining()

    def test_removed_cleanup_does_not_interrupt_unrelated_successor(self):
        control = QuestionControl(10)
        calls = []
        remove = control.on_cancel(lambda: calls.append("completed operation"))
        remove()
        remove()
        control.on_cancel(lambda: calls.append("current operation"))
        control.cancel("invalidated")
        self.assertEqual(calls, ["current operation"])

    def test_cancel_cleans_up_while_question_worker_is_blocked_in_watch(self):
        control = QuestionControl(10)
        watching, release = threading.Event(), threading.Event()
        cancelled = threading.Event()
        def worker():
            remove = control.on_cancel(cancelled.set)
            watching.set()
            release.wait(1)
            remove()
        thread = threading.Thread(target=worker)
        thread.start()
        try:
            self.assertTrue(watching.wait(1))
            control.cancel("invalidated")
            self.assertTrue(cancelled.is_set())
            self.assertTrue(thread.is_alive(), "cleanup must not wait for watch to return")
        finally:
            release.set()
            thread.join(1)
        self.assertFalse(thread.is_alive())

    def test_concurrent_cancel_waits_for_cleanup_and_does_not_change_reason(self):
        control = QuestionControl(10)
        entered, release = threading.Event(), threading.Event()
        second_started, second_returned = threading.Event(), threading.Event()
        calls = []
        def cleanup():
            calls.append("cleanup")
            entered.set()
            release.wait(1)
        control.on_cancel(cleanup)
        first = threading.Thread(target=lambda: control.cancel("invalidated"))
        def second_cancel():
            second_started.set()
            control.cancel("timeout")
            second_returned.set()
        second = threading.Thread(target=second_cancel)
        first.start()
        try:
            self.assertTrue(entered.wait(1))
            second.start()
            self.assertTrue(second_started.wait(1))
            self.assertFalse(second_returned.wait(0.02))
        finally:
            release.set()
            first.join(1)
            if second.ident is not None:
                second.join(1)
        self.assertTrue(second_returned.is_set())
        self.assertEqual(calls, ["cleanup"])
        self.assertEqual(control.reason, "invalidated")

    def test_registration_racing_cancel_is_never_lost(self):
        control = QuestionControl(10)
        entered, release = threading.Event(), threading.Event()
        registered, cleaned = threading.Event(), threading.Event()
        control.on_cancel(lambda: (entered.set(), release.wait(1)))
        cancelling = threading.Thread(target=lambda: control.cancel("invalidated"))
        def register():
            control.on_cancel(cleaned.set)
            registered.set()
        registering = threading.Thread(target=register)
        cancelling.start()
        try:
            self.assertTrue(entered.wait(1))
            registering.start()
            self.assertFalse(registered.wait(0.02))
        finally:
            release.set()
            cancelling.join(1)
            if registering.ident is not None:
                registering.join(1)
        self.assertTrue(registered.is_set())
        self.assertTrue(cleaned.is_set())

    def test_deadline_runs_registered_cleanup(self):
        control = QuestionControl(10)
        calls = []
        control.on_cancel(lambda: calls.append("cancelled"))
        control.deadline = 0
        with self.assertRaises(QuestionTimeout):
            control.remaining()
        self.assertEqual(calls, ["cancelled"])

    def test_one_cleanup_error_does_not_skip_other_owned_cleanup(self):
        control = QuestionControl(10)
        def broken():
            raise RuntimeError("private detail must not enter cancellation diagnostics")
        calls = []
        control.on_cancel(broken)
        control.on_cancel(lambda: calls.append("second"))
        with self.assertLogs("lich_agent_bridge.question", level="WARNING") as logs:
            control.cancel("invalidated")
        self.assertEqual(calls, ["second"])
        self.assertNotIn("private detail", " ".join(logs.output))
