"""Strict controller registry shared conceptually with the Lich bridge."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping

from .errors import ConfigurationError, ValidationError

_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_GLOBAL = re.compile(r"^\$lab_[a-z0-9_]+$")
_TOKEN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$", re.IGNORECASE)
_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")
_LANES = frozenset({"movement", "combat", "inventory", "communication"})
_KINDS = frozenset({"launch", "stop", "signal", "status", "sync"})
_CATEGORIES = frozenset({"inspection", "configuration", "movement", "combat"})
_PARAMETER_TYPES = frozenset({"enum", "numeric", "flag_suffix"})


def _strict(
    value: Any, *, label: str, allowed: set[str], required: set[str]
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{label} must be an object")
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown:
        raise ConfigurationError(
            f"{label} has unsupported field(s): {', '.join(sorted(unknown))}"
        )
    if missing:
        raise ConfigurationError(
            f"{label} is missing field(s): {', '.join(sorted(missing))}"
        )
    return value


def _name(value: Any, label: str) -> str:
    result = str(value)
    if _NAME.fullmatch(result) is None:
        raise ConfigurationError(f"{label} is invalid")
    return result


def _token(value: Any, label: str) -> str:
    result = str(value)
    if _TOKEN.fullmatch(result) is None:
        raise ConfigurationError(f"{label} is invalid")
    return result


def _text(value: Any, label: str, *, allow_empty: bool = False) -> str:
    result = str(value)
    if not allow_empty and not result.strip():
        raise ConfigurationError(f"{label} must not be blank")
    if len(result) > 500 or any(character in result for character in "\r\n;|&"):
        raise ConfigurationError(f"{label} is invalid")
    return result


def _string_array(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ConfigurationError(f"{label} must be a nonempty array")
    result = tuple(_token(item, label) for item in value)
    if len({item.casefold() for item in result}) != len(result):
        raise ConfigurationError(f"{label} contains duplicates")
    return result


@dataclass(frozen=True, slots=True)
class ControllerParameter:
    name: str
    type: str
    values: tuple[str, ...] = ()
    true_value: str = ""
    default: bool = False

    @classmethod
    def from_mapping(cls, raw: Any, label: str) -> "ControllerParameter":
        value = _strict(
            raw,
            label=label,
            allowed={"name", "type", "values", "true_value", "default"},
            required={"name", "type"},
        )
        name = _name(value["name"], f"{label}.name")
        parameter_type = str(value["type"])
        if parameter_type not in _PARAMETER_TYPES:
            raise ConfigurationError(f"{label}.type is unsupported")
        raw_values = value.get("values", [])
        if not isinstance(raw_values, list):
            raise ConfigurationError(f"{label}.values must be an array")
        values = tuple(_token(item, f"{label}.values") for item in raw_values)
        true_value = str(value.get("true_value", ""))
        default = value.get("default", False)
        if parameter_type == "enum":
            if not values or len({item.casefold() for item in values}) != len(values):
                raise ConfigurationError(f"{label}.values must be nonempty and unique")
        elif parameter_type == "numeric" and values:
            raise ConfigurationError(f"{label} numeric parameters do not accept values")
        elif parameter_type == "flag_suffix":
            if not isinstance(default, bool):
                raise ConfigurationError(f"{label}.default must be boolean")
            if not true_value.startswith(" ") or any(
                character in true_value for character in "\r\n;|&"
            ):
                raise ConfigurationError(f"{label}.true_value is invalid")
        return cls(name, parameter_type, values, true_value, bool(default))

    @property
    def required(self) -> bool:
        return self.type != "flag_suffix"

    def regex_fragment(self) -> str:
        if self.type == "enum":
            return "|".join(re.escape(item) for item in self.values)
        if self.type == "numeric":
            return r"[0-9]+"
        return re.escape(self.true_value)

    def render(self, raw: object) -> str:
        if self.type == "enum":
            candidate = str(raw)
            canonical = next(
                (item for item in self.values if item.casefold() == candidate.casefold()),
                None,
            )
            if canonical is None:
                raise ValidationError(
                    f"{self.name} must be one of {', '.join(self.values)}"
                )
            return canonical
        if self.type == "numeric":
            if isinstance(raw, bool):
                raise ValidationError(f"{self.name} must be numeric")
            candidate = str(raw).strip()
            if not candidate.isdigit():
                raise ValidationError(f"{self.name} must be numeric")
            return candidate
        selected = self.default if raw is None else raw
        if not isinstance(selected, bool):
            raise ValidationError(f"{self.name} must be boolean")
        return self.true_value if selected else ""

    def normalize_capture(self, raw: str | None) -> str | bool:
        if self.type == "flag_suffix":
            return raw is not None and raw != ""
        if self.type == "enum":
            return next(
                item for item in self.values if item.casefold() == str(raw).casefold()
            )
        return str(raw)

    def json_schema(self) -> dict[str, Any]:
        if self.type == "enum":
            return {"type": "string", "enum": list(self.values)}
        if self.type == "numeric":
            return {"type": "string", "pattern": "^[0-9]+$"}
        return {"type": "boolean", "default": self.default}


@dataclass(frozen=True, slots=True)
class ControllerAction:
    name: str
    kind: str
    command_template: str
    script_args_template: str
    launch_mode: str | None
    category: str
    confirmation_required: bool
    parameters: tuple[ControllerParameter, ...]
    pattern: re.Pattern[str]

    @classmethod
    def from_mapping(cls, raw: Any, label: str) -> "ControllerAction":
        value = _strict(
            raw,
            label=label,
            allowed={
                "name",
                "kind",
                "command_template",
                "script_args_template",
                "launch_mode",
                "policy",
                "parameters",
            },
            required={
                "name",
                "kind",
                "command_template",
                "script_args_template",
                "policy",
                "parameters",
            },
        )
        name = _name(value["name"], f"{label}.name")
        kind = str(value["kind"])
        if kind not in _KINDS:
            raise ConfigurationError(f"{label}.kind is unsupported")
        command_template = _text(value["command_template"], f"{label}.command_template")
        script_args_template = _text(
            value["script_args_template"],
            f"{label}.script_args_template",
            allow_empty=True,
        )
        launch_mode = None if value.get("launch_mode") is None else str(value["launch_mode"])
        if kind in {"launch", "sync"} and launch_mode not in {"start", "run"}:
            raise ConfigurationError(f"{label}.launch_mode must be start or run")
        policy = _strict(
            value["policy"],
            label=f"{label}.policy",
            allowed={"category", "confirmation_required"},
            required={"category", "confirmation_required"},
        )
        category = str(policy["category"])
        confirmation = policy["confirmation_required"]
        if category not in _CATEGORIES or not isinstance(confirmation, bool):
            raise ConfigurationError(f"{label}.policy is invalid")
        raw_parameters = value["parameters"]
        if not isinstance(raw_parameters, list):
            raise ConfigurationError(f"{label}.parameters must be an array")
        parameters = tuple(
            ControllerParameter.from_mapping(item, f"{label}.parameters[{index}]")
            for index, item in enumerate(raw_parameters)
        )
        names = tuple(item.name for item in parameters)
        if len(set(names)) != len(names):
            raise ConfigurationError(f"{label}.parameters contains duplicates")
        command_names = tuple(sorted(_PLACEHOLDER.findall(command_template)))
        if command_names != tuple(sorted(names)):
            raise ConfigurationError(
                f"{label}.command_template placeholders do not match parameters"
            )
        if not set(_PLACEHOLDER.findall(script_args_template)).issubset(names):
            raise ConfigurationError(f"{label}.script_args_template has invalid placeholders")
        parameter_by_name = {item.name: item for item in parameters}
        pieces = re.split(r"(\{[a-z][a-z0-9_]*\})", command_template)
        regex_parts: list[str] = []
        for piece in pieces:
            match = re.fullmatch(r"\{([a-z][a-z0-9_]*)\}", piece)
            if match is None:
                regex_parts.append(re.escape(piece))
                continue
            parameter = parameter_by_name[match.group(1)]
            capture = f"(?P<{parameter.name}>{parameter.regex_fragment()})"
            regex_parts.append(f"(?:{capture})?" if parameter.type == "flag_suffix" else capture)
        pattern = re.compile(r"\A" + "".join(regex_parts) + r"\Z", re.IGNORECASE)
        return cls(
            name,
            kind,
            command_template,
            script_args_template,
            launch_mode,
            category,
            confirmation,
            parameters,
            pattern,
        )

    def build(self, arguments: Mapping[str, object]) -> tuple[str, str, dict[str, object]]:
        source = {str(key): value for key, value in arguments.items()}
        allowed = {item.name for item in self.parameters}
        required = {item.name for item in self.parameters if item.required}
        unknown = set(source) - allowed
        missing = required - set(source)
        if unknown:
            raise ValidationError(
                f"unsupported controller argument(s): {', '.join(sorted(unknown))}"
            )
        if missing:
            raise ValidationError(
                f"missing controller argument(s): {', '.join(sorted(missing))}"
            )
        rendered: dict[str, str] = {}
        normalized: dict[str, object] = {}
        for parameter in self.parameters:
            raw = source.get(parameter.name, parameter.default)
            rendered[parameter.name] = parameter.render(raw)
            normalized[parameter.name] = (
                bool(raw) if parameter.type == "flag_suffix" else rendered[parameter.name]
            )
        command = _PLACEHOLDER.sub(lambda found: rendered[found.group(1)], self.command_template)
        script_args = _PLACEHOLDER.sub(
            lambda found: rendered[found.group(1)], self.script_args_template
        )
        return command, script_args, normalized

    def match(self, command: str) -> dict[str, object] | None:
        found = self.pattern.fullmatch(command)
        if found is None:
            return None
        return {
            parameter.name: parameter.normalize_capture(found.group(parameter.name))
            for parameter in self.parameters
        }

    def argument_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                parameter.name: parameter.json_schema()
                for parameter in self.parameters
            },
            "required": [
                parameter.name for parameter in self.parameters if parameter.required
            ],
            "additionalProperties": False,
        }


@dataclass(frozen=True, slots=True)
class ControllerDefinition:
    name: str
    script: str
    summary: str
    characters: tuple[str, ...]
    result_global: str
    signal_global: str | None
    lanes: frozenset[str]
    owner_scripts: tuple[str, ...]
    safe_handoff: Mapping[str, Any]
    capability_action: str
    actions: tuple[ControllerAction, ...]

    def action(self, name: str) -> ControllerAction:
        selected = next((item for item in self.actions if item.name == name), None)
        if selected is None:
            raise ValidationError(f"controller action was not found: {self.name}.{name}")
        return selected

    def available_for(self, character: str) -> bool:
        folded = character.casefold()
        return any(item.casefold() == folded for item in self.characters)

    def safe_room(self, arguments: Mapping[str, object]) -> str | None:
        kind = self.safe_handoff["kind"]
        if kind == "room":
            return str(self.safe_handoff["room_id"])
        if kind == "profile_room":
            profile = str(arguments.get("profile", ""))
            rooms = self.safe_handoff["rooms"]
            return str(rooms.get(profile)) if isinstance(rooms, Mapping) and profile in rooms else None
        return None


@dataclass(frozen=True, slots=True)
class ControllerCommand:
    controller: ControllerDefinition
    action: ControllerAction
    arguments: Mapping[str, object]
    script_args: str


class ControllerManifest:
    def __init__(self, controllers: tuple[ControllerDefinition, ...], path: Path):
        if len({item.name for item in controllers}) != len(controllers):
            raise ConfigurationError("controller names must be unique")
        if len({item.script for item in controllers}) != len(controllers):
            raise ConfigurationError("controller scripts must be unique")
        self.controllers = controllers
        self.path = path

    @classmethod
    def load(cls, path: Path | None = None) -> "ControllerManifest":
        selected = path or default_controller_manifest_path()
        try:
            raw = json.loads(selected.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ConfigurationError(f"cannot load controller manifest: {error}") from error
        root = _strict(
            raw,
            label="manifest",
            allowed={"version", "controllers"},
            required={"version", "controllers"},
        )
        if root["version"] != 1:
            raise ConfigurationError("manifest.version must be 1")
        raw_controllers = root["controllers"]
        if not isinstance(raw_controllers, list):
            raise ConfigurationError("manifest.controllers must be an array")
        controllers = tuple(
            _controller_from_mapping(item, f"controllers[{index}]")
            for index, item in enumerate(raw_controllers)
        )
        return cls(controllers, selected)

    def controller(self, name: str) -> ControllerDefinition:
        selected = next(
            (item for item in self.controllers if item.name == name.casefold()), None
        )
        if selected is None:
            raise ValidationError(f"controller was not found: {name}")
        return selected

    def match_command(self, command: str) -> ControllerCommand | None:
        for controller in self.controllers:
            for action in controller.actions:
                arguments = action.match(command)
                if arguments is None:
                    continue
                _, script_args, normalized = action.build(arguments)
                return ControllerCommand(controller, action, normalized, script_args)
        return None


def _controller_from_mapping(raw: Any, label: str) -> ControllerDefinition:
    value = _strict(
        raw,
        label=label,
        allowed={
            "name",
            "script",
            "summary",
            "characters",
            "result_global",
            "signal_global",
            "lanes",
            "owner_scripts",
            "safe_handoff",
            "capability_action",
            "actions",
        },
        required={
            "name",
            "script",
            "summary",
            "characters",
            "result_global",
            "lanes",
            "owner_scripts",
            "safe_handoff",
            "capability_action",
            "actions",
        },
    )
    name = _name(value["name"], f"{label}.name")
    script = _name(value["script"], f"{label}.script")
    summary = _text(value["summary"], f"{label}.summary")
    characters = _string_array(value["characters"], f"{label}.characters")
    result_global = str(value["result_global"])
    signal_global = None if value.get("signal_global") is None else str(value["signal_global"])
    if _GLOBAL.fullmatch(result_global) is None or (
        signal_global is not None and _GLOBAL.fullmatch(signal_global) is None
    ):
        raise ConfigurationError(f"{label} has an invalid result/signal global")
    lanes = frozenset(_string_array(value["lanes"], f"{label}.lanes"))
    if not lanes.issubset(_LANES):
        raise ConfigurationError(f"{label}.lanes is invalid")
    owner_scripts = _string_array(value["owner_scripts"], f"{label}.owner_scripts")
    safe = _strict(
        value["safe_handoff"],
        label=f"{label}.safe_handoff",
        allowed={"kind", "room_id", "rooms"},
        required={"kind"},
    )
    kind = str(safe["kind"])
    if kind not in {"owners_released", "room", "profile_room"}:
        raise ConfigurationError(f"{label}.safe_handoff.kind is unsupported")
    if kind == "room" and not str(safe.get("room_id", "")).isdigit():
        raise ConfigurationError(f"{label}.safe_handoff.room_id must be numeric")
    if kind == "profile_room":
        rooms = safe.get("rooms")
        if not isinstance(rooms, Mapping) or not rooms:
            raise ConfigurationError(f"{label}.safe_handoff.rooms must be nonempty")
        if any(not _TOKEN.fullmatch(str(key)) or not str(room).isdigit() for key, room in rooms.items()):
            raise ConfigurationError(f"{label}.safe_handoff.rooms is invalid")
    raw_actions = value["actions"]
    if not isinstance(raw_actions, list) or not raw_actions:
        raise ConfigurationError(f"{label}.actions must be a nonempty array")
    actions = tuple(
        ControllerAction.from_mapping(item, f"{label}.actions[{index}]")
        for index, item in enumerate(raw_actions)
    )
    if len({item.name for item in actions}) != len(actions):
        raise ConfigurationError(f"{label}.actions contains duplicates")
    capability_action = _name(value["capability_action"], f"{label}.capability_action")
    if not any(item.name == capability_action for item in actions):
        raise ConfigurationError(f"{label}.capability_action was not found")
    if any(item.kind == "signal" for item in actions) and signal_global is None:
        raise ConfigurationError(f"{label}.signal_global is required")
    return ControllerDefinition(
        name,
        script,
        summary,
        characters,
        result_global,
        signal_global,
        lanes,
        owner_scripts,
        dict(safe),
        capability_action,
        actions,
    )


def default_controller_manifest_path() -> Path:
    """Compatibility wrapper around the central settings module."""

    from .settings import Settings

    return Settings.load().storage.controller_manifest
