"""Bounded, evidence-verified capability orchestration.

``CapabilityRunner`` owns operation plans and progress only.  It deliberately
has no command classification or dispatch path: every command is submitted to
the public ``ActionBroker`` interface and remains subject to that broker's
admission, confirmation, expiry, audit, and one-at-a-time dispatch lifecycle.
"""

from __future__ import annotations

import math
import re
import secrets
import threading
import time
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

from .actions import ActionBroker, ActionProposal
from .controller_manifest import ControllerDefinition, ControllerManifest
from .errors import ValidationError
from .script_adapters import BIGSHOT_ADAPTER, ELOOT_ADAPTER, ScriptAdapter
from .watchers import CharacterProfile
from .timings import emit_timing


TERMINAL_OPERATION_STATES = frozenset(
    {"succeeded", "failed", "timed_out", "interrupted"}
)
SUPPORTED_ITEM_AUDIT_METHODS = ("look", "inspect", "405", "735")
MAX_OPERATION_WAIT_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    """Public discovery metadata paired with one private runner method."""

    name: str
    summary: str
    arguments: Mapping[str, Any]
    handler_name: str
    supported_characters: tuple[str, ...] = ()


_EMPTY_ARGUMENTS: Mapping[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}
CAPABILITY_DEFINITIONS = (
    CapabilityDefinition(
        name="character.recon",
        summary="Refresh INFO and/or SKILLS and verify newly observed character records.",
        arguments={
            "type": "object",
            "properties": {"categories": {
                "type": "array", "items": {"type": "string", "enum": ["info", "skills"]},
                "minItems": 1, "maxItems": 2, "uniqueItems": True,
                "default": ["info", "skills"],
            }},
            "additionalProperties": False,
        },
        handler_name="_execute_character_recon",
    ),
    CapabilityDefinition(
        name="item.audit",
        summary="Collect attributed diagnostics for one exact live item and restore it.",
        arguments={
            "type": "object",
            "properties": {
                "item_id": {"type": "string", "pattern": r"^#?[0-9]+$"},
                "methods": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": list(SUPPORTED_ITEM_AUDIT_METHODS),
                    },
                    "minItems": 1,
                    "uniqueItems": True,
                },
            },
            "required": ["item_id"],
            "additionalProperties": False,
        },
        handler_name="_execute_item_audit",
    ),
    CapabilityDefinition(
        name="hunt.prepare",
        summary="Verify character readiness and hand off movement and combat to Bigshot.",
        arguments=_EMPTY_ARGUMENTS,
        handler_name="_execute_hunt_prepare",
    ),
    CapabilityDefinition(
        name="room.loot",
        summary="Run one verified ELoot sweep for exact corpses in the current safe room.",
        arguments=_EMPTY_ARGUMENTS,
        handler_name="_execute_room_loot",
    ),
)
@dataclass(frozen=True, slots=True)
class OwnedLocation:
    """A positively identified character-owned item location.

    ``restore_command`` is supplied by live state rather than synthesized from
    a noun.  The broker still independently classifies and admits it.
    """

    location_id: str
    kind: str
    owner: str
    verified_owned: bool
    safety_rank: int
    restore_command: str | None = None


@dataclass(frozen=True, slots=True)
class ItemState:
    object_id: str
    dossier_id: str
    fingerprint: str
    location: OwnedLocation


@dataclass(frozen=True, slots=True)
class HandItem:
    object_id: str
    name: str


@dataclass(frozen=True, slots=True)
class NearbyObject:
    object_id: str
    noun: str
    name: str | None = None


@dataclass(frozen=True, slots=True)
class SessionState:
    character: str
    generation: str
    room_id: str
    items: tuple[ItemState, ...] = ()
    fresh: bool | None = None
    sequence: int | None = None
    dead: bool | None = None
    stunned: bool | None = None
    wounds: Mapping[str, Mapping[str, int]] | None = None
    encumbrance: int | None = None
    hands: Mapping[str, HandItem | None] | None = None
    scripts: tuple[str, ...] | None = None
    owners: Mapping[str, str | None] | None = None
    nearby_creatures: tuple[NearbyObject, ...] | None = None
    nearby_corpses: tuple[NearbyObject, ...] | None = None
    script_status: Mapping[str, str] | None = None
    character_data: Mapping[str, Mapping[str, Any]] | None = None


@dataclass(frozen=True, slots=True)
class ItemBinding:
    character: str
    generation: str
    object_id: str
    dossier_id: str
    fingerprint: str
    original_location: OwnedLocation


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """Evidence emitted only for a previously registered diagnostic."""

    method: str
    generation: str
    object_id: str
    detail: str
    facts: Mapping[str, Any] = field(default_factory=dict)
    action_id: str | None = None


@dataclass(frozen=True, slots=True)
class OperationEvent:
    cursor: int
    operation_id: str
    status: str
    detail: str
    timestamp: float


@dataclass(slots=True)
class OperationRecord:
    operation_id: str
    capability: str
    character: str
    arguments: dict[str, Any]
    status: str
    requested_at: float
    deadline: float
    admitted_at: float | None = None
    started_at: float | None = None
    ended_at: float | None = None
    start_state: SessionState | None = None
    end_state: SessionState | None = None
    binding: ItemBinding | None = None
    evidence: list[EvidenceRecord] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    events: list[OperationEvent] = field(default_factory=list)
    explanation: str = ""
    expected_generation: str | None = None


class StateAdapter(Protocol):
    """Fresh live state needed by the reference item workflow."""

    def snapshot(self, character: str) -> SessionState: ...

    def safest_owned_locations(
        self, character: str, object_id: str
    ) -> Sequence[OwnedLocation]: ...


class EvidenceAdapter(Protocol):
    """Register an expectation before dispatch, then verify attributed output."""

    def register(
        self, operation_id: str, method: str, binding: ItemBinding
    ) -> object: ...

    def verify(
        self, registration: object, action_id: str | None = None
    ) -> EvidenceRecord | None: ...

    def register_controller(
        self,
        operation_id: str,
        controller: str,
        character: str,
        generation: str,
    ) -> object: ...

    def verify_controller(
        self,
        registration: object,
        action_id: str,
        timeout_seconds: float,
    ) -> EvidenceRecord | None: ...


StepHook = Callable[[ActionBroker, Mapping[str, Any], SessionState], None]
AlertSink = Callable[[Mapping[str, Any]], None]


class _OperationAbort(Exception):
    def __init__(self, status: str, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


class CapabilityRunner:
    """Run deep, deterministic capabilities through an ``ActionBroker``.

    ``step_hook`` is an adapter seam for tests and an embedding session hub.  It
    may advance the broker through its public ``poll``/``approve``/
    ``record_result`` methods; it is not a command path.
    """

    def __init__(
        self,
        *,
        actions: ActionBroker,
        state: StateAdapter,
        evidence: EvidenceAdapter,
        clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], None] = time.sleep,
        step_hook: StepHook | None = None,
        alert: AlertSink | None = None,
        timing=None,
        history_limit: int = 100,
        action_poll_interval: float = 0.01,
        controller_manifest: ControllerManifest | None = None,
        profiles: Iterable[CharacterProfile] = (),
    ):
        if history_limit < 1:
            raise ValueError("history_limit must be positive")
        if action_poll_interval <= 0:
            raise ValueError("action_poll_interval must be positive")
        self._actions = actions
        self._state = state
        self._evidence = evidence
        self._clock = clock
        self._sleeper = sleeper
        self._step_hook = step_hook
        self._alert = alert or (lambda _event: None)
        self._timing = timing
        self._history_limit = history_limit
        self._action_poll_interval = action_poll_interval
        self._controller_manifest = controller_manifest or ControllerManifest.load()
        self._profiles: dict[str, CharacterProfile] = {}
        for profile in profiles:
            key = profile.character.casefold()
            if key in self._profiles:
                raise ValueError(f"duplicate profile for {profile.character}")
            self._profiles[key] = profile
        definitions = [
            replace(definition, supported_characters=tuple(sorted(profile.character for profile in self._profiles.values())))
            if definition.name == "hunt.prepare" else definition
            for definition in CAPABILITY_DEFINITIONS
        ]
        for controller in self._controller_manifest.controllers:
            action = controller.action(controller.capability_action)
            definitions.append(
                CapabilityDefinition(
                    name=f"controller.{controller.name}",
                    summary=controller.summary,
                    arguments=action.argument_schema(),
                    handler_name="_execute_controller",
                    supported_characters=controller.characters,
                )
            )
        self._capability_definitions = tuple(definitions)
        self._capability_by_name = {
            definition.name: definition
            for definition in self._capability_definitions
        }
        self._operations: OrderedDict[str, OperationRecord] = OrderedDict()
        self._interruptions: set[str] = set()
        self._recon_actions: dict[str, tuple[str, str]] = {}
        self._cursor = 0
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)

    def perform(
        self,
        character: str,
        capability: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        timeout_seconds: float = 30.0,
        expected_generation: str | None = None,
    ) -> OperationRecord:
        """Execute one operation and return its complete truthful record."""

        operation = self._create_operation(
            character,
            capability,
            arguments,
            timeout_seconds=timeout_seconds,
            expected_generation=expected_generation,
        )
        try:
            return self._execute_operation(operation)
        except Exception as error:
            self._fail_unexpected(operation, error)
            return operation

    def describe_capabilities(
        self, character: str | None = None
    ) -> tuple[dict[str, Any], ...]:
        """Return bounded public metadata without exposing runner implementation names."""

        selected = None if character is None else character.strip().casefold()
        descriptions: list[dict[str, Any]] = []
        for definition in self._capability_definitions:
            supported = definition.supported_characters
            available = (
                None
                if selected is None
                else not supported
                or any(name.casefold() == selected for name in supported)
            )
            if definition.name == "hunt.prepare" and not supported:
                available = False
            descriptions.append(
                {
                    "name": definition.name,
                    "summary": definition.summary,
                    "arguments": deepcopy(definition.arguments),
                    "supported_characters": list(supported),
                    "available": available,
                }
            )
        return tuple(descriptions)

    def start(
        self,
        character: str,
        capability: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        timeout_seconds: float = 30.0,
        expected_generation: str | None = None,
    ) -> OperationRecord:
        """Admit an operation immediately and execute it in one background thread."""

        operation = self._create_operation(
            character,
            capability,
            arguments,
            timeout_seconds=timeout_seconds,
            expected_generation=expected_generation,
        )
        try:
            worker = threading.Thread(
                target=self._execute_background,
                args=(operation,),
                name=f"lab-operation-{operation.operation_id}",
                daemon=True,
            )
            worker.start()
        except Exception as error:
            self._fail_unexpected(operation, error)
        return operation

    def wait(
        self,
        operation_id: str,
        *,
        after_cursor: int = 0,
        timeout_seconds: float = MAX_OPERATION_WAIT_SECONDS,
    ) -> tuple[tuple[OperationEvent, ...], OperationRecord]:
        """Wait boundedly for progress or terminal state without changing it."""

        if isinstance(after_cursor, bool) or not isinstance(after_cursor, int):
            raise ValidationError("after_cursor must be an integer")
        if after_cursor < 0:
            raise ValidationError("after_cursor must not be negative")
        if isinstance(timeout_seconds, bool) or not isinstance(
            timeout_seconds, (int, float)
        ):
            raise ValidationError("timeout_seconds must be a number")
        timeout = float(timeout_seconds)
        if not 0 <= timeout <= MAX_OPERATION_WAIT_SECONDS:
            raise ValidationError(
                "timeout_seconds must be between 0 and "
                f"{MAX_OPERATION_WAIT_SECONDS:g}"
            )
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
                operation = self._find_operation_locked(operation_id)
                events = tuple(
                    event
                    for event in operation.events
                    if event.cursor > after_cursor
                )
                if events or operation.status in TERMINAL_OPERATION_STATES:
                    return events, operation
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return (), operation
                self._condition.wait(remaining)

    def _create_operation(
        self,
        character: str,
        capability: str,
        arguments: Mapping[str, Any] | None,
        *,
        timeout_seconds: float,
        expected_generation: str | None = None,
    ) -> OperationRecord:
        if not isinstance(character, str) or not character.strip():
            raise ValidationError("character must not be blank")
        if not isinstance(capability, str) or not capability.strip():
            raise ValidationError("capability must not be blank")
        if expected_generation is not None and (
            not isinstance(expected_generation, str) or not expected_generation.strip()
        ):
            raise ValidationError("expected_generation must not be blank")
        if isinstance(timeout_seconds, bool) or not isinstance(
            timeout_seconds, (int, float)
        ):
            raise ValidationError("timeout_seconds must be a number")
        duration = float(timeout_seconds)
        if not math.isfinite(duration) or duration <= 0:
            raise ValidationError("timeout_seconds must be positive")
        args = dict(arguments or {})
        now = self._clock()
        operation = OperationRecord(
            operation_id=secrets.token_hex(8),
            capability=capability.strip(),
            character=character.strip(),
            arguments=args,
            status="requested",
            requested_at=now,
            deadline=now + duration,
            expected_generation=expected_generation,
        )
        with self._lock:
            character_key = operation.character.casefold()
            if any(
                existing.character.casefold() == character_key
                and existing.status not in TERMINAL_OPERATION_STATES
                for existing in self._operations.values()
            ):
                raise ValidationError(
                    f"a nonterminal operation already owns {operation.character}"
                )
            if len(self._operations) >= self._history_limit:
                evicted_id = next(
                    (
                        operation_id
                        for operation_id, existing in self._operations.items()
                        if existing.status in TERMINAL_OPERATION_STATES
                    ),
                    None,
                )
                if evicted_id is None:
                    raise ValidationError("operation history is full of active work")
                self._operations.pop(evicted_id)
                self._interruptions.discard(evicted_id)
            self._operations[operation.operation_id] = operation
            self._emit_locked(operation, "requested", "operation requested")
        return operation

    def _execute_operation(self, operation: OperationRecord) -> OperationRecord:
        abort: _OperationAbort | None = None
        try:
            definition = self._capability_by_name.get(operation.capability)
            if definition is None:
                raise _OperationAbort(
                    "failed", f"unsupported capability: {operation.capability}"
                )
            handler = getattr(self, definition.handler_name)
            explanation = handler(operation)
            operation.explanation = explanation
            self._finish(operation, "succeeded", operation.explanation)
            return operation
        except _OperationAbort as error:
            abort = error
        except (ValidationError, ValueError, KeyError) as error:
            abort = _OperationAbort("failed", str(error))
        except Exception as error:  # adapters fail closed, never leak a command
            abort = _OperationAbort(
                "failed", f"operation adapter failed: {type(error).__name__}: {error}"
            )

        assert abort is not None
        try:
            self._safe_cleanup(operation, allow_commands=abort.status != "timed_out")
        except Exception as error:
            self._raise_alert(
                operation,
                f"cleanup adapter failed: {type(error).__name__}: {error}",
            )
        operation.end_state = self._safe_snapshot(operation.character)
        operation.explanation = abort.detail
        self._finish(operation, abort.status, abort.detail)
        return operation

    def _execute_background(self, operation: OperationRecord) -> None:
        try:
            self._execute_operation(operation)
        except Exception as error:
            self._fail_unexpected(operation, error)

    def _fail_unexpected(self, operation: OperationRecord, error: Exception) -> None:
        detail = f"operation worker failed: {type(error).__name__}: {error}"
        with self._condition:
            if operation.status in TERMINAL_OPERATION_STATES:
                return
            operation.explanation = detail
            try:
                operation.ended_at = self._clock()
            except Exception:
                operation.ended_at = None
            operation.status = "failed"
            try:
                self._emit_locked(operation, "failed", detail)
            except Exception:
                self._condition.notify_all()

    def get(self, operation_id: str) -> OperationRecord:
        with self._lock:
            return self._find_operation_locked(operation_id)

    def _find_operation_locked(self, operation_id: str) -> OperationRecord:
        try:
            return self._operations[operation_id]
        except KeyError as error:
            raise ValidationError("operation was not found") from error

    def history(self, character: str | None = None) -> tuple[OperationRecord, ...]:
        with self._lock:
            records = tuple(self._operations.values())
        if character is None:
            return records
        folded = character.casefold()
        return tuple(record for record in records if record.character.casefold() == folded)

    def events(
        self, operation_id: str, *, after_cursor: int = 0
    ) -> tuple[OperationEvent, ...]:
        if after_cursor < 0:
            raise ValidationError("after_cursor must not be negative")
        operation = self.get(operation_id)
        with self._lock:
            return tuple(
                event for event in operation.events if event.cursor > after_cursor
            )

    def interrupt(self, operation_id: str) -> None:
        operation = self.get(operation_id)
        with self._lock:
            if operation.status not in TERMINAL_OPERATION_STATES:
                self._interruptions.add(operation_id)
        self._cancel_recon_action(operation)

    def _cancel_recon_action(self, operation: OperationRecord) -> None:
        with self._lock:
            owned = self._recon_actions.get(operation.operation_id)
        if owned is None:
            return
        action_id, generation = owned
        result = self._actions.cancel(
            action_id, character=operation.character, generation=generation,
        )
        if result["cancelled"]:
            self._progress(operation, f"cancelled owned pending recon action {action_id}")
        elif result["status"] == "dispatched":
            self._raise_alert(operation, "recon was already dispatched; sent commands cannot be unsent")

    def _execute_item_audit(self, operation: OperationRecord) -> str:
        methods = self._parse_item_audit_arguments(operation.arguments)
        start = self._state.snapshot(operation.character)
        operation.start_state = start
        binding = self._bind_item(
            operation.character, operation.arguments["item_id"], start
        )
        operation.binding = binding
        self._admit_and_start(
            operation,
            admitted_detail="item identity and session admitted",
            running_detail="item audit running",
        )
        self._run_item_audit(operation, binding, methods)
        end = self._state.snapshot(operation.character)
        self._verify_binding(end, binding)
        if self._exact_item(end, binding).location.location_id != (
            binding.original_location.location_id
        ):
            raise _OperationAbort(
                "failed", "same-ID item was not restored to its original location"
            )
        operation.end_state = end
        return (
            "registered diagnostic evidence collected and the exact same item "
            "was restored to its original owned location"
        )

    def _execute_character_recon(self, operation: OperationRecord) -> str:
        operation.deadline = min(operation.deadline, operation.requested_at + 20)
        if set(operation.arguments) - {"categories"}:
            raise _OperationAbort("failed", "character.recon accepts only categories")
        requested = operation.arguments.get("categories", ["info", "skills"])
        if (
            not isinstance(requested, list) or not 1 <= len(requested) <= 2
            or any(not isinstance(item, str) or item not in {"info", "skills"} for item in requested)
            or len(set(requested)) != len(requested)
        ):
            raise _OperationAbort("failed", "categories must contain one or two unique values: info, skills")
        # INFO precedes SKILLS so the skill capture can record its observed level.
        categories = tuple(name for name in ("info", "skills") if name in requested)
        start = self._require_fresh_session(operation)
        if not start.room_id:
            raise _OperationAbort("failed", "live room ID is unavailable")
        operation.start_state = start
        self._admit_and_start(
            operation, admitted_detail="character inspection categories and session admitted",
            running_detail="refreshing character records",
        )
        action = self._run_broker_step(
            operation, start, categories if len(categories) > 1 else categories[0],
            "requesting " + ", ".join(categories),
        )
        self._progress(operation, "commands completed; waiting for newly observed character evidence")
        while True:
            self._check_deadline_and_interruption(operation)
            current = self._require_fresh_session(
                operation, expected_generation=start.generation, minimum_sequence=start.sequence,
            )
            if current.room_id != start.room_id:
                raise _OperationAbort("failed", "room changed during character recon")
            records = self._recon_records(
                current, start, categories, operation.requested_at,
                observed_before=min(self._clock(), operation.deadline),
            )
            if current.sequence > start.sequence and records is not None:
                for category, record in records.items():
                    operation.evidence.append(EvidenceRecord(
                        method=f"character.{category}", generation=current.generation,
                        object_id=operation.character,
                        detail=f"new complete {category} response observed in advancing snapshot",
                        facts={"category": category, "snapshot_sequence": current.sequence, **deepcopy(dict(record))},
                        action_id=str(action["action_id"]),
                    ))
                operation.end_state = current
                return "newly observed " + ", ".join(categories) + " character records verified"
            self._sleeper(min(self._action_poll_interval, max(0, operation.deadline - self._clock())))

    @staticmethod
    def _recon_records(
        current: SessionState, start: SessionState, categories: tuple[str, ...], requested_at: float,
        *, observed_before: float,
    ) -> dict[str, Mapping[str, Any]] | None:
        records = current.character_data or {}
        previous = start.character_data or {}
        verified: dict[str, Mapping[str, Any]] = {}
        for category in categories:
            record = records.get(category)
            if not isinstance(record, Mapping) or record.get("source") != category or record.get("complete") is not True:
                return None
            values = record.get("values")
            if not isinstance(values, Mapping) or not values:
                return None
            observed = _record_timestamp(record)
            prior = _record_timestamp(previous.get(category))
            if observed is not None and observed > observed_before:
                raise _OperationAbort("failed", f"{category} capture timestamp is in the future")
            if observed is None or observed < requested_at or (prior is not None and observed <= prior):
                return None
            verified[category] = record
        skills = records.get("skills")
        info = records.get("info")
        if "skills" in categories and isinstance(skills, Mapping) and isinstance(info, Mapping):
            values = info.get("values")
            level = values.get("level") if isinstance(values, Mapping) else None
            observed_level = skills.get("observed_level")
            if level is not None and level != observed_level:
                return None
        return verified

    def _execute_hunt_prepare(self, operation: OperationRecord) -> str:
        self._require_empty_arguments(operation)
        profile = self._profiles.get(operation.character.casefold())
        if profile is None:
            raise _OperationAbort(
                "failed", f"hunt.prepare has no profile for {operation.character}"
            )
        start = self._require_fresh_session(operation)
        operation.start_state = start
        self._validate_hunt_readiness(start, profile, BIGSHOT_ADAPTER)
        self._admit_and_start(
            operation,
            admitted_detail="hunt readiness and Bigshot handoff admitted",
            running_detail="hunt preparation running",
        )

        current = self._require_fresh_session(
            operation,
            expected_generation=start.generation,
            minimum_sequence=start.sequence,
        )
        self._validate_hunt_readiness(current, profile, BIGSHOT_ADAPTER)
        self._run_broker_step(
            operation,
            current,
            BIGSHOT_ADAPTER.command("start"),
            "starting registered Bigshot adapter",
        )
        end = self._require_fresh_session(
            operation,
            expected_generation=start.generation,
            after_sequence=current.sequence,
        )
        self._validate_hunt_readiness(end, profile, BIGSHOT_ADAPTER)
        self._verify_script_owns_lanes(end, BIGSHOT_ADAPTER)
        operation.end_state = end
        return "Bigshot is verified running with movement and combat ownership"

    def _execute_room_loot(self, operation: OperationRecord) -> str:
        self._require_empty_arguments(operation)
        start = self._require_fresh_session(operation)
        operation.start_state = start
        corpse_ids = self._validate_room_loot_start(start)
        self._require_no_owner_conflicts(start, ELOOT_ADAPTER)
        self._admit_and_start(
            operation,
            admitted_detail="safe current-room loot sweep admitted",
            running_detail="current-room loot sweep running",
        )

        current = self._require_fresh_session(
            operation,
            expected_generation=start.generation,
            minimum_sequence=start.sequence,
        )
        self._validate_room_loot_start(current, expected_corpse_ids=corpse_ids)
        self._require_no_owner_conflicts(current, ELOOT_ADAPTER)
        action = self._run_broker_step(
            operation,
            current,
            ELOOT_ADAPTER.command("loot_current_room"),
            "running registered ELoot current-room sweep",
        )
        end = self._require_fresh_session(
            operation,
            expected_generation=start.generation,
            after_sequence=current.sequence,
        )
        self._verify_room_loot_end(
            end, corpse_ids, str(action.get("action_id", ""))
        )
        operation.end_state = end
        return "ELoot completion and removal of every starting exact corpse ID verified"

    def _execute_controller(self, operation: OperationRecord) -> str:
        controller_name = operation.capability.removeprefix("controller.")
        controller = self._controller_manifest.controller(controller_name)
        if not controller.available_for(operation.character):
            raise _OperationAbort(
                "failed",
                f"{operation.capability} is unavailable for {operation.character}",
            )
        action = controller.action(controller.capability_action)
        command, _script_args, normalized = action.build(operation.arguments)
        operation.arguments = normalized

        start = self._require_fresh_session(operation)
        operation.start_state = start
        self._validate_controller_start(start, controller)
        registration = self._evidence.register_controller(
            operation.operation_id,
            controller.name,
            operation.character,
            start.generation,
        )
        self._admit_and_start(
            operation,
            admitted_detail=f"{controller.name} controller handoff admitted",
            running_detail=f"{controller.name} controller running",
        )

        current = self._require_fresh_session(
            operation,
            expected_generation=start.generation,
            minimum_sequence=start.sequence,
        )
        self._validate_controller_start(current, controller)
        broker_result = self._run_broker_step(
            operation,
            current,
            command,
            f"starting registered {controller.name} controller",
        )
        action_id = str(broker_result.get("action_id", ""))
        remaining = operation.deadline - self._clock()
        if remaining <= 0:
            raise _OperationAbort(
                "timed_out", "operation timed out waiting for controller result"
            )
        evidence = self._evidence.verify_controller(
            registration,
            action_id,
            remaining,
        )
        if evidence is None:
            raise _OperationAbort(
                "failed", "registered controller result evidence was not observed"
            )
        self._verify_controller_evidence(
            evidence,
            controller=controller,
            generation=start.generation,
            action_id=action_id,
        )
        operation.evidence.append(evidence)
        self._progress(
            operation,
            f"verified {controller.name} result {evidence.facts['code']}",
        )

        end = self._require_fresh_session(
            operation,
            expected_generation=start.generation,
            after_sequence=current.sequence,
        )
        self._verify_controller_handoff(end, controller, operation.arguments)
        operation.end_state = end
        return (
            f"{controller.name} controller reported {evidence.facts['code']} and "
            "safe owner release was verified"
        )

    @staticmethod
    def _validate_controller_start(
        snapshot: SessionState, controller: ControllerDefinition
    ) -> None:
        if snapshot.dead is not False:
            raise _OperationAbort("failed", "known alive state is required")
        if snapshot.stunned is not False:
            raise _OperationAbort("failed", "known unstunned state is required")
        if snapshot.owners is None:
            raise _OperationAbort("failed", "known ownership state is required")
        for lane in sorted(controller.lanes):
            if lane not in snapshot.owners:
                raise _OperationAbort("failed", f"ownership lane {lane} is unknown")
            owner = snapshot.owners[lane]
            if owner is not None:
                raise _OperationAbort(
                    "failed", f"ownership conflict in {lane}: {owner}"
                )

    @staticmethod
    def _verify_controller_evidence(
        evidence: EvidenceRecord,
        *,
        controller: ControllerDefinition,
        generation: str,
        action_id: str,
    ) -> None:
        if (
            evidence.method != f"controller.{controller.name}"
            or evidence.generation != generation
            or evidence.object_id != controller.name
            or evidence.action_id != action_id
        ):
            raise _OperationAbort(
                "failed", "controller result evidence did not match the operation"
            )
        facts = evidence.facts
        if (
            not isinstance(facts.get("ok"), bool)
            or not isinstance(facts.get("code"), str)
            or not isinstance(facts.get("message"), str)
            or not isinstance(facts.get("details"), Mapping)
        ):
            raise _OperationAbort("failed", "controller result evidence is malformed")
        if facts["ok"] is not True:
            raise _OperationAbort(
                "failed", f"controller failed: {facts['code']}: {facts['message']}"
            )

    @staticmethod
    def _verify_controller_handoff(
        snapshot: SessionState,
        controller: ControllerDefinition,
        arguments: Mapping[str, object],
    ) -> None:
        if snapshot.owners is None:
            raise _OperationAbort("failed", "post-state ownership is unknown")
        for lane in sorted(controller.lanes):
            if lane not in snapshot.owners:
                raise _OperationAbort(
                    "failed", f"post-state ownership lane {lane} is unknown"
                )
            if snapshot.owners[lane] is not None:
                raise _OperationAbort(
                    "failed", f"controller did not release {lane} ownership"
                )
        safe_room = controller.safe_room(arguments)
        if safe_room is not None and snapshot.room_id != safe_room:
            raise _OperationAbort(
                "failed",
                f"controller did not return to safe room {safe_room}",
            )

    def _admit_and_start(
        self,
        operation: OperationRecord,
        *,
        admitted_detail: str,
        running_detail: str,
    ) -> None:
        operation.admitted_at = self._clock()
        self._transition(operation, "admitted", admitted_detail)
        self._check_deadline_and_interruption(operation)
        operation.started_at = self._clock()
        self._transition(operation, "running", running_detail)

    @staticmethod
    def _require_empty_arguments(operation: OperationRecord) -> None:
        if operation.arguments:
            raise _OperationAbort(
                "failed",
                f"{operation.capability} does not accept arguments",
            )

    def _require_fresh_session(
        self,
        operation: OperationRecord,
        *,
        expected_generation: str | None = None,
        minimum_sequence: int | None = None,
        after_sequence: int | None = None,
    ) -> SessionState:
        snapshot = self._state.snapshot(operation.character)
        if snapshot.character.casefold() != operation.character.casefold():
            raise _OperationAbort("failed", "state belongs to another character")
        if not snapshot.generation:
            raise _OperationAbort("failed", "active session generation is unavailable")
        if operation.expected_generation is not None and snapshot.generation != operation.expected_generation:
            raise _OperationAbort("failed", "stale session generation")
        if expected_generation is not None and snapshot.generation != expected_generation:
            raise _OperationAbort("failed", "stale session generation")
        if snapshot.fresh is not True:
            raise _OperationAbort("failed", "fresh structured session state is required")
        if isinstance(snapshot.sequence, bool) or not isinstance(snapshot.sequence, int):
            raise _OperationAbort("failed", "snapshot sequence is unknown")
        if minimum_sequence is not None and snapshot.sequence < minimum_sequence:
            raise _OperationAbort("failed", "snapshot sequence regressed")
        if after_sequence is not None and snapshot.sequence <= after_sequence:
            raise _OperationAbort("failed", "verified post-state did not advance")
        return snapshot

    def _validate_hunt_readiness(
        self,
        snapshot: SessionState,
        profile: CharacterProfile,
        adapter: ScriptAdapter,
    ) -> None:
        if snapshot.dead is not False:
            raise _OperationAbort("failed", "known alive state is required")
        if snapshot.stunned is not False:
            raise _OperationAbort("failed", "known unstunned state is required")
        if snapshot.wounds is None:
            raise _OperationAbort("failed", "known wound state is required")
        severe: dict[str, int] = {}
        for part, levels in snapshot.wounds.items():
            if not isinstance(levels, Mapping):
                raise _OperationAbort("failed", "wound severity is unknown")
            wound = levels.get("wound")
            if isinstance(wound, bool) or not isinstance(wound, int):
                raise _OperationAbort("failed", "wound severity is unknown")
            if wound >= profile.severe_wound_level:
                severe[str(part)] = wound
        if severe:
            raise _OperationAbort("failed", f"severe wounds prevent hunting: {severe}")
        if snapshot.hands is None:
            raise _OperationAbort("failed", "known hand state is required")
        expected = {
            self._normalize_item_name(name)
            for name in profile.expected_hand_item_names
        }
        observed = {
            self._normalize_item_name(item.name)
            for item in snapshot.hands.values()
            if item is not None
        }
        if not observed.intersection(expected):
            raise _OperationAbort(
                "failed", f"expected {profile.expected_hand_item_label} is not in hand"
            )
        if profile.encumbrance_emergency is not None:
            if (
                isinstance(snapshot.encumbrance, bool)
                or not isinstance(snapshot.encumbrance, int)
                or snapshot.encumbrance >= profile.encumbrance_emergency
            ):
                raise _OperationAbort(
                    "failed", "known encumbrance below the configured emergency threshold is required"
                )
        self._require_no_owner_conflicts(snapshot, adapter)

    @staticmethod
    def _normalize_item_name(value: str) -> str:
        without_article = re.sub(
            r"\A(?:a|an|some)\s+", "", value.strip(), flags=re.IGNORECASE
        )
        return re.sub(r"\s+", " ", without_article).casefold()

    @staticmethod
    def _require_no_owner_conflicts(
        snapshot: SessionState, adapter: ScriptAdapter
    ) -> None:
        if snapshot.owners is None:
            raise _OperationAbort("failed", "known ownership state is required")
        for lane in sorted(adapter.ownership_lanes):
            if lane not in snapshot.owners:
                raise _OperationAbort("failed", f"ownership lane {lane} is unknown")
            owner = snapshot.owners[lane]
            if owner is not None and owner.casefold() != adapter.name:
                raise _OperationAbort(
                    "failed", f"ownership conflict in {lane}: {owner}"
                )

    @staticmethod
    def _verify_script_owns_lanes(
        snapshot: SessionState, adapter: ScriptAdapter
    ) -> None:
        if snapshot.scripts is None or snapshot.owners is None:
            raise _OperationAbort("failed", "post-state script ownership is unknown")
        running = {name.casefold() for name in snapshot.scripts}
        if adapter.name not in running:
            raise _OperationAbort("failed", f"{adapter.name} is not verified running")
        for lane in sorted(adapter.ownership_lanes):
            owner = snapshot.owners.get(lane)
            if owner is None or owner.casefold() != adapter.name:
                raise _OperationAbort(
                    "failed", f"{adapter.name} does not own {lane} in post-state"
                )

    def _validate_room_loot_start(
        self,
        snapshot: SessionState,
        *,
        expected_corpse_ids: frozenset[str] | None = None,
    ) -> frozenset[str]:
        if snapshot.nearby_creatures is None:
            raise _OperationAbort("failed", "known nearby creature state is required")
        if snapshot.nearby_creatures:
            raise _OperationAbort("failed", "live creatures prevent room.loot")
        if snapshot.nearby_corpses is None:
            raise _OperationAbort("failed", "known nearby corpse state is required")
        if snapshot.scripts is None or snapshot.script_status is None:
            raise _OperationAbort(
                "failed", "known script execution state is required"
            )
        running = {name.casefold() for name in snapshot.scripts}
        prior_status = snapshot.script_status.get(ELOOT_ADAPTER.name)
        clean_status = (
            prior_status is None
            or prior_status.casefold() in {"idle", "stopped"}
            or prior_status.casefold().startswith("completed:")
        )
        if ELOOT_ADAPTER.name in running or not clean_status:
            raise _OperationAbort(
                "failed", "a clean ELoot execution baseline is required"
            )
        corpse_ids = frozenset(corpse.object_id for corpse in snapshot.nearby_corpses)
        if (
            not corpse_ids
            or any(not object_id for object_id in corpse_ids)
            or len(corpse_ids) != len(snapshot.nearby_corpses)
        ):
            raise _OperationAbort("failed", "room.loot requires exact corpse IDs")
        if expected_corpse_ids is not None and corpse_ids != expected_corpse_ids:
            raise _OperationAbort("failed", "starting exact corpse set changed")
        return corpse_ids

    @staticmethod
    def _verify_room_loot_end(
        snapshot: SessionState,
        starting_corpse_ids: frozenset[str],
        action_id: str,
    ) -> None:
        if snapshot.nearby_creatures is None or snapshot.nearby_creatures:
            raise _OperationAbort(
                "failed", "post-state is unknown or live creatures are present"
            )
        if snapshot.nearby_corpses is None:
            raise _OperationAbort("failed", "post-state corpse IDs are unknown")
        remaining = starting_corpse_ids.intersection(
            corpse.object_id for corpse in snapshot.nearby_corpses
        )
        if remaining:
            raise _OperationAbort(
                "failed", f"starting corpse IDs remain after ELoot: {sorted(remaining)}"
            )
        if snapshot.script_status is None:
            raise _OperationAbort("failed", "ELoot completion state is unknown")
        status = snapshot.script_status.get(ELOOT_ADAPTER.name)
        if status is None or status.casefold() != f"completed:{action_id}".casefold():
            raise _OperationAbort("failed", "ELoot completion was not verified")
        if snapshot.scripts is None:
            raise _OperationAbort("failed", "post-state running scripts are unknown")
        if ELOOT_ADAPTER.name in {name.casefold() for name in snapshot.scripts}:
            raise _OperationAbort("failed", "ELoot has not finished")

    def _parse_item_audit_arguments(self, args: dict[str, Any]) -> tuple[str, ...]:
        unknown = set(args) - {"item_id", "methods"}
        if unknown:
            raise _OperationAbort(
                "failed", f"unsupported item.audit argument(s): {', '.join(sorted(unknown))}"
            )
        item_id = args.get("item_id")
        if isinstance(item_id, int) and not isinstance(item_id, bool):
            item_id = str(item_id)
            args["item_id"] = item_id
        if not isinstance(item_id, str) or not item_id.strip():
            raise _OperationAbort("failed", "item.audit requires item_id")
        item_id = item_id.removeprefix("#")
        if not item_id.isdigit():
            raise _OperationAbort("failed", "item_id must be a live numeric object ID")
        args["item_id"] = item_id
        raw_methods = args.get("methods", ("look", "inspect"))
        if isinstance(raw_methods, str) or not isinstance(raw_methods, Sequence):
            raise _OperationAbort("failed", "methods must be a sequence")
        requested: set[str] = set()
        for value in raw_methods:
            method = str(value).strip().casefold()
            if method not in SUPPORTED_ITEM_AUDIT_METHODS:
                raise _OperationAbort("failed", f"unsupported item.audit method: {method}")
            requested.add(method)
        if not requested:
            raise _OperationAbort("failed", "item.audit requires at least one method")
        return tuple(method for method in SUPPORTED_ITEM_AUDIT_METHODS if method in requested)

    def _bind_item(
        self, character: str, object_id: str, snapshot: SessionState
    ) -> ItemBinding:
        if snapshot.character.casefold() != character.casefold():
            raise _OperationAbort("failed", "state belongs to another character")
        if not snapshot.generation:
            raise _OperationAbort("failed", "active session generation is unavailable")
        matches = tuple(item for item in snapshot.items if item.object_id == object_id)
        if len(matches) != 1:
            raise _OperationAbort(
                "failed",
                "ambiguous item identity: expected one live object "
                f"#{object_id}, found {len(matches)}",
            )
        item = matches[0]
        if not item.dossier_id or not item.fingerprint:
            raise _OperationAbort("failed", "item dossier/fingerprint is incomplete")
        self._require_owned_location(character, item.location)
        return ItemBinding(
            character=character,
            generation=snapshot.generation,
            object_id=object_id,
            dossier_id=item.dossier_id,
            fingerprint=item.fingerprint,
            original_location=item.location,
        )

    def _run_item_audit(
        self, operation: OperationRecord, binding: ItemBinding, methods: Sequence[str]
    ) -> None:
        spell_methods = {"405", "735"}.intersection(methods)
        for method in (value for value in methods if value not in spell_methods):
            self._run_diagnostic(operation, binding, method)

        if spell_methods:
            current = self._fresh_bound_item(operation, binding)
            if current.location.kind not in {"right_hand", "left_hand"}:
                self._run_action_step(
                    operation,
                    binding,
                    f"get #{binding.object_id}",
                    "taking exact item for spell diagnostics",
                )
                held = self._fresh_bound_item(operation, binding)
                if held.location.kind not in {"right_hand", "left_hand"}:
                    raise _OperationAbort(
                        "failed", "exact item was not verified in hand after take"
                    )

            for method in (value for value in methods if value in spell_methods):
                self._run_diagnostic(operation, binding, method)

        self._restore_original(operation, binding)

    def _run_diagnostic(
        self, operation: OperationRecord, binding: ItemBinding, method: str
    ) -> None:
        commands = {
            "look": f"look #{binding.object_id}",
            "inspect": f"inspect #{binding.object_id}",
            "405": f"diagnose item 405 exact #{binding.object_id}",
            "735": f"diagnose item 735 exact #{binding.object_id}",
        }
        registration = self._evidence.register(operation.operation_id, method, binding)
        self._progress(operation, f"registered {method} evidence expectation")
        action = self._run_action_step(
            operation,
            binding,
            commands[method],
            f"running {method} diagnostic",
        )
        self._fresh_bound_item(operation, binding)
        evidence = self._evidence.verify(
            registration, str(action.get("action_id", ""))
        )
        if evidence is None:
            raise _OperationAbort("failed", f"registered {method} evidence was not observed")
        if (
            evidence.method != method
            or evidence.generation != binding.generation
            or evidence.object_id != binding.object_id
        ):
            raise _OperationAbort(
                "failed", f"registered {method} evidence did not match the bound item"
            )
        operation.evidence.append(evidence)
        self._progress(operation, f"verified {method} evidence for #{binding.object_id}")

    def _run_action_step(
        self,
        operation: OperationRecord,
        binding: ItemBinding,
        command: str,
        detail: str,
        *,
        cleanup: bool = False,
    ) -> Mapping[str, Any]:
        if not cleanup:
            self._check_deadline_and_interruption(operation)
        if re.search(
            rf"(?<![0-9])#{re.escape(binding.object_id)}(?![0-9])", command
        ) is None:
            raise _OperationAbort(
                "failed",
                f"{detail} command does not reference exact object #{binding.object_id}",
            )
        snapshot = self._state.snapshot(operation.character)
        self._verify_binding(snapshot, binding)
        return self._run_broker_step(
            operation,
            snapshot,
            command,
            detail,
            cleanup=cleanup,
        )

    def _run_broker_step(
        self,
        operation: OperationRecord,
        snapshot: SessionState,
        command: str | tuple[str, ...],
        detail: str,
        *,
        cleanup: bool = False,
    ) -> Mapping[str, Any]:
        if not cleanup:
            self._check_deadline_and_interruption(operation)
        remaining = operation.deadline - self._clock()
        if remaining <= 0:
            raise _OperationAbort("timed_out", "operation timed out before next action")
        ttl = max(1, min(120, math.ceil(remaining)))
        if operation.capability == "character.recon":
            if remaining < 1:
                raise _OperationAbort("timed_out", "insufficient time remains for character inspection")
            # An undispatched inspection must expire no later than its owning
            # recon operation, including fractional request deadlines.
            ttl = min(120, math.floor(remaining))
        try:
            action = self._actions.submit(
                ActionProposal(
                    character=operation.character,
                    command=command if isinstance(command, str) else None,
                    commands=command if isinstance(command, tuple) else (),
                    expected_room_id=snapshot.room_id,
                    expected_generation=snapshot.generation,
                    ttl_seconds=ttl,
                )
            )
        except ValidationError as error:
            raise _OperationAbort("failed", f"broker denied {detail}: {error}") from error
        recon = operation.capability == "character.recon"
        if recon:
            with self._lock:
                self._recon_actions[operation.operation_id] = (str(action["action_id"]), snapshot.generation)
        try:
            # An interrupt can arrive while submit is returning, before its ID
            # can be associated with the operation. Recheck before dispatch.
            if recon:
                self._check_deadline_and_interruption(operation)
            self._progress(operation, f"broker admitted action {action['action_id']}: {detail}")
            if self._step_hook is not None:
                self._step_hook(self._actions, action, snapshot)
            while True:
                if recon:
                    self._check_deadline_and_interruption(operation)
                result = self._actions.get(str(action["action_id"]))
                status = str(result["status"])
                if status == "completed":
                    self._progress(
                        operation,
                        f"{detail}: {result.get('completion', 'sent_unverified')}",
                    )
                    return result
                if status in {"failed", "expired", "cancelled", "denied_stale_room"}:
                    raise _OperationAbort("failed", f"broker action {status}: {detail}")
                self._check_deadline_and_interruption(operation, allow_interrupt=not cleanup)
                self._sleeper(self._action_poll_interval)
        finally:
            if recon:
                try:
                    self._cancel_recon_action(operation)
                finally:
                    with self._lock:
                        self._recon_actions.pop(operation.operation_id, None)

    def _restore_original(
        self, operation: OperationRecord, binding: ItemBinding
    ) -> None:
        current = self._fresh_bound_item(operation, binding)
        original = binding.original_location
        if current.location.location_id == original.location_id:
            self._progress(operation, "same-ID item already in original owned location")
            return
        if not original.restore_command:
            raise _OperationAbort(
                "failed", "original owned location has no exact restore command"
            )
        try:
            self._run_action_step(
                operation,
                binding,
                original.restore_command,
                "restoring exact item to original owned location",
            )
        except _OperationAbort as error:
            raise _OperationAbort("failed", f"restore failed: {error.detail}") from error
        restored = self._fresh_bound_item(operation, binding)
        if restored.location.location_id != original.location_id:
            raise _OperationAbort(
                "failed", "restore failed: same-ID restoration was not verified"
            )
        self._progress(operation, "verified same-ID restoration")

    def _safe_cleanup(self, operation: OperationRecord, *, allow_commands: bool) -> None:
        binding = operation.binding
        if binding is None:
            return
        snapshot = self._safe_snapshot(operation.character)
        if snapshot is None:
            self._raise_alert(operation, "cleanup blocked: live state is unavailable")
            return
        try:
            self._verify_binding(snapshot, binding)
            current = self._exact_item(snapshot, binding)
        except _OperationAbort as error:
            self._raise_alert(operation, f"cleanup blocked: {error.detail}")
            return
        if current.location.location_id == binding.original_location.location_id:
            self._raise_alert(
                operation,
                "operation failed; exact item retained in original owned location "
                f"{current.location.location_id}",
            )
            return
        candidates = [binding.original_location]
        candidates.extend(
            self._state.safest_owned_locations(operation.character, binding.object_id)
        )
        safe = [
            location
            for location in candidates
            if self._is_owned_location(operation.character, location)
        ]
        if not safe:
            self._raise_alert(
                operation, "cleanup blocked: no positively identified owned location"
            )
            return
        target = max(safe, key=lambda location: location.safety_rank)
        if current.location.location_id == target.location_id:
            self._raise_alert(
                operation,
                "operation failed; exact item retained in safest owned location "
                f"{target.location_id}",
            )
            return
        if not allow_commands:
            self._raise_alert(
                operation,
                "operation timed out; no cleanup command issued after the deadline",
            )
            return
        if not target.restore_command:
            self._raise_alert(
                operation,
                "cleanup blocked: safest owned location "
                f"{target.location_id} has no restore command",
            )
            return
        try:
            self._run_action_step(
                operation,
                binding,
                target.restore_command,
                f"placing exact item in safest owned location {target.location_id}",
                cleanup=True,
            )
            after = self._fresh_bound_item(operation, binding)
            if after.location.location_id != target.location_id:
                raise _OperationAbort("failed", "safe-location verification failed")
            self._raise_alert(
                operation,
                f"operation failed; exact item secured in owned location {target.location_id}",
            )
        except _OperationAbort as error:
            self._raise_alert(operation, f"safe cleanup failed: {error.detail}")

    def _fresh_bound_item(
        self, operation: OperationRecord, binding: ItemBinding
    ) -> ItemState:
        snapshot = self._state.snapshot(operation.character)
        self._verify_binding(snapshot, binding)
        return self._exact_item(snapshot, binding)

    def _verify_binding(self, snapshot: SessionState, binding: ItemBinding) -> None:
        if snapshot.character.casefold() != binding.character.casefold():
            raise _OperationAbort("failed", "character changed during operation")
        if snapshot.generation != binding.generation:
            raise _OperationAbort("failed", "stale session generation")
        item = self._exact_item(snapshot, binding)
        self._require_owned_location(binding.character, item.location)

    def _exact_item(self, snapshot: SessionState, binding: ItemBinding) -> ItemState:
        matches = tuple(
            item for item in snapshot.items if item.object_id == binding.object_id
        )
        if len(matches) != 1:
            raise _OperationAbort(
                "failed",
                "ambiguous item identity for live object "
                f"#{binding.object_id}: found {len(matches)}",
            )
        item = matches[0]
        if (
            item.dossier_id != binding.dossier_id
            or item.fingerprint != binding.fingerprint
        ):
            raise _OperationAbort("failed", "item dossier/fingerprint changed")
        return item

    def _check_deadline_and_interruption(
        self, operation: OperationRecord, *, allow_interrupt: bool = True
    ) -> None:
        if self._clock() >= operation.deadline:
            raise _OperationAbort("timed_out", "operation timed out")
        with self._lock:
            interrupted = operation.operation_id in self._interruptions
        if allow_interrupt and interrupted:
            raise _OperationAbort("interrupted", "operation interrupted before next step")

    def _safe_snapshot(self, character: str) -> SessionState | None:
        try:
            return self._state.snapshot(character)
        except Exception:
            return None

    @staticmethod
    def _is_owned_location(character: str, location: OwnedLocation) -> bool:
        return (
            bool(location.location_id)
            and location.verified_owned
            and location.owner.casefold() == character.casefold()
        )

    def _require_owned_location(self, character: str, location: OwnedLocation) -> None:
        if not self._is_owned_location(character, location):
            raise _OperationAbort(
                "failed", "item location is not positively identified as owned"
            )

    def _transition(
        self, operation: OperationRecord, status: str, detail: str
    ) -> None:
        allowed = {
            "requested": {"admitted", "failed", "timed_out", "interrupted"},
            "admitted": {"running", "failed", "timed_out", "interrupted"},
            "running": TERMINAL_OPERATION_STATES,
        }
        with self._lock:
            if status not in allowed.get(operation.status, frozenset()):
                raise RuntimeError(
                    f"invalid operation transition {operation.status} -> {status}"
                )
            operation.status = status
            self._emit_locked(operation, status, detail)

    def _progress(self, operation: OperationRecord, detail: str) -> None:
        with self._lock:
            self._emit_locked(operation, operation.status, detail)

    def _finish(self, operation: OperationRecord, status: str, detail: str) -> None:
        operation.ended_at = self._clock()
        self._transition(operation, status, detail)
        emit_timing(
            self._timing,
            "operation.end_to_end_ms",
            (operation.ended_at - operation.requested_at) * 1_000,
            character=operation.character,
            capability=operation.capability,
            operation_id=operation.operation_id,
            status=status,
        )

    def _emit_locked(
        self, operation: OperationRecord, status: str, detail: str
    ) -> None:
        self._cursor += 1
        operation.events.append(
            OperationEvent(
                cursor=self._cursor,
                operation_id=operation.operation_id,
                status=status,
                detail=detail,
                timestamp=self._clock(),
            )
        )
        self._condition.notify_all()

    def _raise_alert(self, operation: OperationRecord, detail: str) -> None:
        operation.alerts.append(detail)
        try:
            self._alert(
                {
                    "event": "operation_alert",
                    "operation_id": operation.operation_id,
                    "capability": operation.capability,
                    "character": operation.character,
                    "detail": detail,
                }
            )
        except Exception:
            pass
        self._progress(operation, f"alert: {detail}")


def _record_timestamp(record: Mapping[str, Any] | None) -> float | None:
    if not isinstance(record, Mapping) or not isinstance(record.get("observed_at"), str):
        return None
    try:
        value = datetime.fromisoformat(record["observed_at"].replace("Z", "+00:00"))
        return value.timestamp() if value.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None
