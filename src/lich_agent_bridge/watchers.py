"""Deterministic, read-only alerts derived from structured snapshots."""

from __future__ import annotations

import re
import threading
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .errors import ValidationError
from .protocol import CharacterSnapshot


ALERT_SEVERITIES = frozenset({"info", "warning", "critical"})


@dataclass(frozen=True, slots=True)
class CharacterProfile:
    """Explicit facts and thresholds for one character watcher."""

    character: str
    expected_hand_item_names: frozenset[str] = frozenset()
    expected_hand_item_label: str = "weapon"
    encumbrance_warning: int | None = None
    encumbrance_emergency: int | None = None
    required_defensive_spell_ids: frozenset[str] = frozenset()
    severe_wound_level: int = 2

    def __post_init__(self) -> None:
        if not self.character.strip():
            raise ValueError("profile character must not be blank")
        for name, value in (
            ("encumbrance_warning", self.encumbrance_warning),
            ("encumbrance_emergency", self.encumbrance_emergency),
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 1
            ):
                raise ValueError(f"{name} must be a positive integer or None")
        if self.severe_wound_level < 1:
            raise ValueError("severe_wound_level must be positive")
        if (
            self.encumbrance_warning is not None
            and self.encumbrance_emergency is not None
            and self.encumbrance_emergency < self.encumbrance_warning
        ):
            raise ValueError(
                "encumbrance_emergency must not be below encumbrance_warning"
            )
        if len(self.expected_hand_item_names) > 256:
            raise ValueError("expected_hand_item_names is too large")
        if len(self.required_defensive_spell_ids) > 256:
            raise ValueError("required_defensive_spell_ids is too large")
        if any(not value.strip() for value in self.expected_hand_item_names):
            raise ValueError("expected hand item names must not be blank")
        if any(not str(value).strip() for value in self.required_defensive_spell_ids):
            raise ValueError("required defensive spell IDs must not be blank")


@dataclass(frozen=True, slots=True)
class WatcherAlert:
    code: str
    severity: str
    status: str
    character: str
    generation: str
    snapshot_sequence: int
    evidence: Mapping[str, Any]

    def to_mapping(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "status": self.status,
            "character": self.character,
            "generation": self.generation,
            "snapshot_sequence": self.snapshot_sequence,
            "evidence": dict(self.evidence),
        }


@dataclass(slots=True)
class _CharacterWatcherState:
    generation: str
    sequence: int | None
    active: OrderedDict[str, WatcherAlert]
    history: deque[WatcherAlert]
    corpse_counts: dict[str, int] = field(default_factory=dict)
    corpse_evidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    seen_required_spells: set[str] = field(default_factory=set)
    previous: CharacterSnapshot | None = None


class WatcherReducer:
    """Compare snapshots and emit only alert transitions.

    Unknown fields preserve existing alert state and never establish a new
    absence.  A generation change discards all session-local temporal state.
    """

    def __init__(
        self,
        profiles: Iterable[CharacterProfile] = (),
        *,
        corpse_persistence_snapshots: int = 3,
        active_limit: int = 64,
        history_limit: int = 256,
    ):
        if corpse_persistence_snapshots < 1:
            raise ValueError("corpse_persistence_snapshots must be positive")
        if active_limit < 1:
            raise ValueError("active_limit must be positive")
        if history_limit < 1:
            raise ValueError("history_limit must be positive")
        selected: dict[str, CharacterProfile] = {}
        for profile in profiles:
            key = profile.character.casefold()
            if key in selected:
                raise ValueError(f"duplicate profile for {profile.character}")
            selected[key] = profile
        self._profiles = selected
        self._corpse_persistence_snapshots = corpse_persistence_snapshots
        self._active_limit = active_limit
        self._history_limit = history_limit
        self._states: dict[str, _CharacterWatcherState] = {}
        self._lock = threading.RLock()

    def supports(self, character: str) -> bool:
        """Only explicitly supplied profiles have character-specific rules."""
        return character.casefold() in self._profiles

    def reduce(self, snapshot: CharacterSnapshot) -> tuple[WatcherAlert, ...]:
        """Admit one snapshot and return newly active/cleared alerts."""

        key = snapshot.character.casefold()
        profile = self._profiles.get(key)
        if profile is None:
            raise ValidationError(f"no watcher profile for {snapshot.character}")
        with self._lock:
            state = self._states.get(key)
            if state is None or state.generation != snapshot.generation:
                state = self._new_state(snapshot.generation)
                self._states[key] = state
            elif state.sequence is not None and snapshot.sequence <= state.sequence:
                raise ValidationError(
                    "watcher snapshot sequence must strictly increase within a generation"
                )

            emitted: list[WatcherAlert] = []
            self._weapon_alert(profile, state, snapshot, emitted)
            self._encumbrance_alert(profile, state, snapshot, emitted)
            self._boolean_alerts(state, snapshot, emitted)
            self._wound_alert(state, snapshot, profile, emitted)
            self._spell_alerts(profile, state, snapshot, emitted)
            self._script_alerts(state, snapshot, emitted)
            self._corpse_alerts(state, snapshot, emitted)
            state.sequence = snapshot.sequence
            state.previous = snapshot
            return tuple(emitted)

    def active(self, character: str) -> tuple[WatcherAlert, ...]:
        with self._lock:
            state = self._states.get(character.casefold())
            return () if state is None else tuple(state.active.values())

    def history(self, character: str) -> tuple[WatcherAlert, ...]:
        with self._lock:
            state = self._states.get(character.casefold())
            return () if state is None else tuple(state.history)

    def _new_state(self, generation: str) -> _CharacterWatcherState:
        return _CharacterWatcherState(
            generation=generation,
            sequence=None,
            active=OrderedDict(),
            history=deque(maxlen=self._history_limit),
        )

    def _weapon_alert(
        self,
        profile: CharacterProfile,
        state: _CharacterWatcherState,
        snapshot: CharacterSnapshot,
        emitted: list[WatcherAlert],
    ) -> None:
        if not profile.expected_hand_item_names:
            return
        if snapshot.hands is None:
            condition = None
            observed: list[str] = []
        else:
            observed = [
                str(item["name"])
                for item in snapshot.hands.values()
                if item is not None
            ]
            expected = {
                self._normalize_item_name(name)
                for name in profile.expected_hand_item_names
            }
            condition = not any(
                self._normalize_item_name(name) in expected for name in observed
            )
        self._set_condition(
            state,
            snapshot,
            emitted,
            code="expected_weapon_missing",
            condition=condition,
            severity="critical",
            evidence={
                "expected": profile.expected_hand_item_label,
                "observed_hands": observed,
            },
        )

    def _encumbrance_alert(
        self,
        profile: CharacterProfile,
        state: _CharacterWatcherState,
        snapshot: CharacterSnapshot,
        emitted: list[WatcherAlert],
    ) -> None:
        if (
            profile.encumbrance_warning is None
            and profile.encumbrance_emergency is None
        ):
            return
        level = self._encumbrance_level(snapshot.encumbrance)
        if level is None:
            self._set_condition(
                state,
                snapshot,
                emitted,
                code="encumbrance",
                condition=None,
                severity="warning",
                evidence={"observed": snapshot.encumbrance},
            )
            return
        emergency = profile.encumbrance_emergency
        warning = profile.encumbrance_warning
        if emergency is not None and level >= emergency:
            severity = "critical"
            threshold = emergency
            condition = True
        elif warning is not None and level >= warning:
            severity = "warning"
            threshold = warning
            condition = True
        else:
            severity = "warning"
            threshold = warning if warning is not None else emergency
            condition = False
        self._set_condition(
            state,
            snapshot,
            emitted,
            code="encumbrance",
            condition=condition,
            severity=severity,
            evidence={
                "observed": snapshot.encumbrance,
                "level": level,
                "threshold": threshold,
            },
        )

    def _boolean_alerts(
        self,
        state: _CharacterWatcherState,
        snapshot: CharacterSnapshot,
        emitted: list[WatcherAlert],
    ) -> None:
        for code, condition, severity in (
            ("dead", snapshot.dead, "critical"),
            ("stunned", snapshot.stunned, "warning"),
        ):
            self._set_condition(
                state,
                snapshot,
                emitted,
                code=code,
                condition=condition,
                severity=severity,
                evidence={"observed": condition},
            )

    def _wound_alert(
        self,
        state: _CharacterWatcherState,
        snapshot: CharacterSnapshot,
        profile: CharacterProfile,
        emitted: list[WatcherAlert],
    ) -> None:
        if snapshot.wounds is None:
            condition = None
            severe: dict[str, int] = {}
        else:
            severe = {}
            for part, levels in snapshot.wounds.items():
                if not isinstance(levels, Mapping):
                    continue
                wound = levels.get("wound")
                if isinstance(wound, int) and not isinstance(wound, bool):
                    if wound >= profile.severe_wound_level:
                        severe[str(part)] = wound
            condition = bool(severe)
        self._set_condition(
            state,
            snapshot,
            emitted,
            code="severe_wounds",
            condition=condition,
            severity="critical",
            evidence={
                "minimum_level": profile.severe_wound_level,
                "wounds": severe,
            },
        )

    def _spell_alerts(
        self,
        profile: CharacterProfile,
        state: _CharacterWatcherState,
        snapshot: CharacterSnapshot,
        emitted: list[WatcherAlert],
    ) -> None:
        if not profile.required_defensive_spell_ids:
            return
        if snapshot.active_spells is None:
            return
        active = {str(spell["id"]) for spell in snapshot.active_spells}
        required = {str(spell_id) for spell_id in profile.required_defensive_spell_ids}
        state.seen_required_spells.update(active.intersection(required))
        for spell_id in sorted(required):
            condition = spell_id in state.seen_required_spells and spell_id not in active
            self._set_condition(
                state,
                snapshot,
                emitted,
                code=f"defensive_spell_dropped:{spell_id}",
                condition=condition,
                severity="warning",
                evidence={"spell_id": spell_id, "active_spell_ids": sorted(active)},
            )

    def _script_alerts(
        self,
        state: _CharacterWatcherState,
        snapshot: CharacterSnapshot,
        emitted: list[WatcherAlert],
    ) -> None:
        previous = state.previous
        if snapshot.owners is None or snapshot.scripts is None:
            return
        current_scripts = {name.casefold() for name in snapshot.scripts}
        current_keys: set[str] = set()
        previous_owners = (
            previous.owners
            if previous is not None and previous.owners is not None
            else {}
        )
        lanes = set(previous_owners).union(snapshot.owners)
        for lane in lanes:
            current_owner = snapshot.owners.get(lane)
            owner = current_owner or previous_owners.get(lane)
            if owner is None:
                continue
            owner_key = owner.casefold()
            code = f"owning_script_missing:{lane}:{owner_key}"
            current_keys.add(code)
            was_running = (
                previous is not None
                and previous.scripts is not None
                and previous_owners.get(lane) is not None
                and str(previous_owners[lane]).casefold() == owner_key
                and owner_key in {name.casefold() for name in previous.scripts}
            )
            condition = was_running and owner_key not in current_scripts
            if code in state.active:
                condition = (
                    current_owner is not None and owner_key not in current_scripts
                )
            self._set_condition(
                state,
                snapshot,
                emitted,
                code=code,
                condition=condition,
                severity="warning",
                evidence={
                    "lane": lane,
                    "owner": owner,
                    "running_scripts": sorted(snapshot.scripts),
                },
            )
        for code in tuple(state.active):
            if code.startswith("owning_script_missing:") and code not in current_keys:
                self._set_condition(
                    state,
                    snapshot,
                    emitted,
                    code=code,
                    condition=False,
                    severity="warning",
                    evidence={"owner_released": True},
                )

    def _corpse_alerts(
        self,
        state: _CharacterWatcherState,
        snapshot: CharacterSnapshot,
        emitted: list[WatcherAlert],
    ) -> None:
        if snapshot.nearby is None or "corpses" not in snapshot.nearby:
            for object_id in tuple(state.corpse_counts):
                if f"unlooted_corpse:{object_id}" not in state.active:
                    state.corpse_counts.pop(object_id, None)
                    state.corpse_evidence.pop(object_id, None)
            return
        corpses = snapshot.nearby["corpses"]
        current_ids = {str(corpse["id"]) for corpse in corpses}
        for object_id in tuple(state.corpse_counts):
            if object_id not in current_ids:
                state.corpse_counts.pop(object_id, None)
                state.corpse_evidence.pop(object_id, None)
        for corpse in corpses:
            object_id = str(corpse["id"])
            state.corpse_counts[object_id] = state.corpse_counts.get(object_id, 0) + 1
            state.corpse_evidence[object_id] = dict(corpse)
            self._set_condition(
                state,
                snapshot,
                emitted,
                code=f"unlooted_corpse:{object_id}",
                condition=(
                    state.corpse_counts[object_id]
                    >= self._corpse_persistence_snapshots
                ),
                severity="warning",
                evidence={
                    **state.corpse_evidence[object_id],
                    "consecutive_snapshots": state.corpse_counts[object_id],
                },
            )
        for code in tuple(state.active):
            if code.startswith("unlooted_corpse:"):
                object_id = code.rsplit(":", 1)[-1]
                if object_id not in current_ids:
                    self._set_condition(
                        state,
                        snapshot,
                        emitted,
                        code=code,
                        condition=False,
                        severity="warning",
                        evidence={"object_id": object_id, "corpse_absent": True},
                    )

    def _set_condition(
        self,
        state: _CharacterWatcherState,
        snapshot: CharacterSnapshot,
        emitted: list[WatcherAlert],
        *,
        code: str,
        condition: bool | None,
        severity: str,
        evidence: Mapping[str, Any],
    ) -> None:
        if condition is None:
            return
        existing = state.active.get(code)
        if condition:
            if existing is not None and existing.severity == severity:
                return
            if existing is None and len(state.active) >= self._active_limit:
                return
            alert = WatcherAlert(
                code=code,
                severity=severity,
                status="active",
                character=snapshot.character,
                generation=snapshot.generation,
                snapshot_sequence=snapshot.sequence,
                evidence=dict(evidence),
            )
            state.active[code] = alert
            state.active.move_to_end(code)
            state.history.append(alert)
            emitted.append(alert)
            return
        if existing is None:
            return
        state.active.pop(code, None)
        cleared = WatcherAlert(
            code=code,
            severity="info",
            status="cleared",
            character=snapshot.character,
            generation=snapshot.generation,
            snapshot_sequence=snapshot.sequence,
            evidence=dict(evidence),
        )
        state.history.append(cleared)
        emitted.append(cleared)

    @staticmethod
    def _normalize_item_name(value: str) -> str:
        return re.sub(
            r"\s+",
            " ",
            re.sub(r"\A(?:a|an|some)\s+", "", value.strip(), flags=re.IGNORECASE),
        ).casefold()

    @staticmethod
    def _encumbrance_level(value: str | int | None) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, int):
            return max(0, value)
        folded = " ".join(value.casefold().split())
        if folded.isdigit():
            return int(folded)
        exact = {
            "none": 0,
            "unencumbered": 0,
            "not encumbered": 0,
            "no noticeable encumbrance": 0,
            "light": 1,
            "lightly encumbered": 1,
            "moderate": 2,
            "moderately encumbered": 2,
            "heavy": 3,
            "heavily encumbered": 3,
            "very heavy": 4,
            "severely encumbered": 4,
            "overburdened": 5,
        }
        return exact.get(folded)
