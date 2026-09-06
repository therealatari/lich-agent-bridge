"""Cooperative deadline shared by one bounded question and its model adapter."""

from __future__ import annotations

import time
import logging
from threading import Event, RLock
from typing import Callable

from .errors import QuestionInvalidated, QuestionTimeout


class QuestionControl:
    def __init__(self, timeout_seconds: float):
        self.deadline = time.monotonic() + timeout_seconds
        self.cancelled = Event()
        self.changed = Event()
        self.reason = ""
        self._cancel_lock = RLock()
        self._cancel_callbacks: dict[object, Callable[[], None]] = {}

    def cancel(self, reason: str) -> None:
        # Keep cleanup synchronous, including for concurrent cancel callers.
        # Callbacks must be short exact-owner revocations, never model/network
        # work or waits for the question worker to return.
        with self._cancel_lock:
            if self.cancelled.is_set():
                return
            self.reason = reason
            self.cancelled.set()
            callbacks = tuple(self._cancel_callbacks.values())
            self._cancel_callbacks.clear()
            try:
                for callback in callbacks:
                    self._run_cancel_callback(callback)
            finally:
                self.changed.set()

    def on_cancel(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register owned cleanup; late registration runs before returning.

        The returned idempotent remover releases a completed operation's
        callback without cancelling anything else owned by the question.
        """
        if not callable(callback):
            raise TypeError("cancellation callback must be callable")
        token = object()
        with self._cancel_lock:
            if self.cancelled.is_set():
                self._run_cancel_callback(callback)
            else:
                self._cancel_callbacks[token] = callback

        def remove() -> None:
            with self._cancel_lock:
                self._cancel_callbacks.pop(token, None)
        return remove

    @staticmethod
    def _run_cancel_callback(callback: Callable[[], None]) -> None:
        try:
            callback()
        except Exception:
            # One cleanup failure must not skip another owner or expose raw
            # callback exception text in diagnostics.
            logging.getLogger(__name__).warning("question cancellation cleanup failed")

    def remaining(self) -> float:
        if self.cancelled.is_set():
            if self.reason == "timeout":
                raise QuestionTimeout("question deadline exceeded; no answer was retained")
            raise QuestionInvalidated("question discarded because conversation or session changed")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            self.cancel("timeout")
            if self.reason != "timeout":
                raise QuestionInvalidated("question discarded because conversation or session changed")
            raise QuestionTimeout("question deadline exceeded; no answer was retained")
        return remaining
