"""Import read-only GemStone character audits into the account SQLite ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


LINE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [^:]+: ?")
COMMAND_START = re.compile(r"^\[(?:lab|sol)\]>(.+)$", re.IGNORECASE)
COMMAND_END = re.compile(
    r"^--- (?:LAB|Sol): executed \[[0-9a-f]+\]: (.+)$", re.IGNORECASE
)
INFO_IDENTITY = re.compile(
    r"^Name: (?P<name>.+?) Race: (?P<race>.+?)\s+Profession: (?P<profession>.+?) "
    r"\((?:shown as: (?P<title>.+)|not shown)\)$"
)
INFO_DETAILS = re.compile(
    r"^Gender: (?P<gender>\S+)\s+Age: (?P<age>\d+)\s+Expr: (?P<experience>[\d,]+)\s+Level:\s+(?P<level>\d+)$"
)
STAT_LINE = re.compile(
    r"^\s*(?P<name>[A-Za-z]+) \((?P<code>[A-Z]{3})\):\s*"
    r"(?P<base>-?\d+) \((?P<bonus>-?\d+)\)\s+\.\.\.\s+"
    r"(?P<enhanced>-?\d+) \((?P<enhanced_bonus>-?\d+)\)$"
)
MANA_SILVER = re.compile(r"^Mana:\s+(?P<mana>[\d,]+)\s+Silver:\s+(?P<silver>[\d,]+)$")
VITALS = re.compile(
    r"^Health:\s*(?P<health>\d+)/(?P<max_health>\d+)\s+"
    r"Mana:\s*(?P<mana>\d+)/(?P<max_mana>\d+)\s+"
    r"Stamina:\s*(?P<stamina>\d+)/(?P<max_stamina>\d+)\s+"
    r"Spirit:\s*(?P<spirit>\d+)/(?P<max_spirit>\d+)$"
)
SKILL_LINE = re.compile(r"^\s*(?P<name>.+?)\.{2,}\|\s*(?P<bonus>\d+)\s+(?P<ranks>\d+)\s*$")
SPELL_LINE = re.compile(r"^\s*(?P<name>.+?)\.{2,}\|\s+(?P<ranks>\d+)\s*$")
TRAINING_POINTS = re.compile(
    r"^Training Points: (?P<physical>\d+) Phy (?P<mental>\d+) Mnt(?: \((?P<conversion>.+)\))?$"
)


@dataclass(frozen=True)
class Audit:
    character: str
    captured_at: str
    source_log: Path
    commands: dict[str, list[str]]
    raw_lines: list[str]
    snapshot: dict[str, Any]


def _clean(line: str) -> str:
    return LINE_PREFIX.sub("", line.rstrip("\r\n"))


def extract_commands(text: str) -> dict[str, list[str]]:
    commands: dict[str, list[str]] = {}
    current: str | None = None
    output: list[str] = []
    for raw_line in text.splitlines():
        line = _clean(raw_line)
        start = COMMAND_START.match(line)
        if start:
            current = " ".join(start.group(1).lower().split())
            output = []
            continue
        end = COMMAND_END.match(line)
        if end and current:
            commands[current] = output.copy()
            current = None
            output = []
            continue
        if current is not None:
            output.append(line)
    return commands


def parse_snapshot(
    character: str, commands: dict[str, list[str]], raw_lines: list[str] | None = None
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {"character": character, "commands": commands}
    # The game can finish printing one response after LAB has started the next
    # queued command.  Parse stable facts from the complete log, while retaining
    # the command groupings as useful (but non-authoritative) observations.
    evidence_lines = raw_lines if raw_lines is not None else [line for lines in commands.values() for line in lines]
    stats: dict[str, Any] = {}
    resources: dict[str, int] = {}
    for line in evidence_lines:
        if match := INFO_IDENTITY.match(line):
            snapshot["identity"] = {key: value for key, value in match.groupdict().items() if value}
        elif match := INFO_DETAILS.match(line):
            values = match.groupdict()
            snapshot["gender"] = values["gender"]
            snapshot["age"] = int(values["age"])
            snapshot["experience"] = int(values["experience"].replace(",", ""))
            snapshot["level"] = int(values["level"])
        elif match := STAT_LINE.match(line):
            values = match.groupdict()
            stats[values["code"]] = {
                "name": values["name"],
                "base": int(values["base"]),
                "bonus": int(values["bonus"]),
                "enhanced": int(values["enhanced"]),
                "enhanced_bonus": int(values["enhanced_bonus"]),
            }
        elif match := MANA_SILVER.match(line):
            snapshot["mana"] = int(match.group("mana").replace(",", ""))
            snapshot["silver"] = int(match.group("silver").replace(",", ""))
        elif match := VITALS.match(line):
            resources = {key: int(value) for key, value in match.groupdict().items()}
    snapshot["stats"] = stats
    if resources:
        snapshot["resources"] = resources
        snapshot["mana"] = resources["mana"]

    skills: dict[str, Any] = {}
    spell_circles: dict[str, int] = {}
    skill_lines = evidence_lines
    in_spell_lists = False
    for line in skill_lines:
        if line == "Spell Lists":
            in_spell_lists = True
            continue
        if match := TRAINING_POINTS.match(line):
            snapshot["training_points"] = {
                "physical": int(match.group("physical")),
                "mental": int(match.group("mental")),
                "conversion": match.group("conversion"),
            }
            continue
        if in_spell_lists and (match := SPELL_LINE.match(line)):
            spell_circles[match.group("name").strip()] = int(match.group("ranks"))
        elif not in_spell_lists and (match := SKILL_LINE.match(line)):
            skills[match.group("name").strip()] = {
                "bonus": int(match.group("bonus")),
                "ranks": int(match.group("ranks")),
            }
    snapshot["skills"] = skills
    snapshot["spell_circles"] = spell_circles

    exp_text = "\n".join(evidence_lines)
    for field, pattern in {
        "fame": r"Fame:\s*([\d,]+)",
        "field_experience": r"Field Exp:\s*([\d,]+)",
        "field_experience_capacity": r"Field Exp:\s*[\d,]+/([\d,]+)",
        "long_term_experience": r"Long-Term Exp:\s*([\d,]+)",
        "deeds": r"Deeds:\s*(\d+)",
        "experience_to_level": r"Exp until lvl:\s*([\d,]+)",
    }.items():
        if match := re.search(pattern, exp_text):
            snapshot[field] = int(match.group(1).replace(",", ""))

    society_lines = [
        line.strip().rstrip(".")
        for line in evidence_lines
        if re.match(
            r"^\s*You are (?:a Master in the|a member of the Guardians of Sunfist|not a member of any society)",
            line,
        )
    ]
    snapshot["society"] = society_lines[-1] if society_lines else (
        "No Society affiliation" if any("No Society affiliation" in line for line in evidence_lines) else "Unknown"
    )
    guild_lines = [
        line.strip().rstrip(".")
        for line in evidence_lines
        if "member of the " in line and line.strip().endswith("Guild.")
    ]
    snapshot["guild"] = guild_lines[-1] if guild_lines else (
        "No Guild affiliation"
        if any("No Guild affiliation" in line or "no guild affiliation" in line.lower() for line in evidence_lines)
        else "Unknown"
    )
    worn = [line for line in evidence_lines if line.startswith("You are wearing ")]
    hands = [line for line in evidence_lines if line.startswith("You are holding ")]
    snapshot["equipment_snapshot"] = worn[-1] if worn else ""
    snapshot["hands_snapshot"] = hands[-1] if hands else ""
    container_observations = []
    for line in evidence_lines:
        match = re.match(r"^In the (?P<container>.+?) you see (?P<contents>.+)\.$", line)
        if match:
            container_observations.append(
                {
                    "container": match.group("container"),
                    "contents": match.group("contents"),
                    "status": "protected_pending_item_audit",
                }
            )
    if container_observations:
        snapshot["container_observations"] = container_observations
    return snapshot


def load_audit(character: str, source_log: Path) -> Audit:
    raw = source_log.read_text(encoding="utf-8", errors="replace")
    raw_lines = [_clean(line) for line in raw.splitlines()]
    commands = extract_commands(raw)
    snapshot = parse_snapshot(character, commands, raw_lines)
    if "identity" not in snapshot or "training_points" not in snapshot:
        raise ValueError(f"{source_log} does not contain a complete LAB baseline audit")
    timestamp = datetime.fromtimestamp(source_log.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    return Audit(
        character,
        timestamp,
        source_log.resolve(),
        commands,
        raw_lines,
        snapshot,
    )


def _facts(snapshot: dict[str, Any]) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    for key in (
        "level", "experience", "fame", "mana", "silver", "gender", "age", "society", "guild",
        "field_experience", "field_experience_capacity", "long_term_experience", "deeds",
        "experience_to_level", "training_points", "resources", "equipment_snapshot", "hands_snapshot",
        "container_observations",
    ):
        if key in snapshot:
            facts[key] = snapshot[key]
    for key, value in snapshot.get("identity", {}).items():
        facts[f"identity.{key}"] = value
    for code, value in snapshot.get("stats", {}).items():
        facts[f"stat.{code}"] = value
    for name, value in snapshot.get("skills", {}).items():
        facts[f"skill.{name}"] = value
    for name, value in snapshot.get("spell_circles", {}).items():
        facts[f"spell_circle.{name}"] = value
    return facts


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE IF NOT EXISTS schema_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS characters (
          id INTEGER PRIMARY KEY, game TEXT NOT NULL, name TEXT NOT NULL,
          UNIQUE(game, name COLLATE NOCASE)
        );
        CREATE TABLE IF NOT EXISTS character_baselines (
          id INTEGER PRIMARY KEY, character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
          captured_at TEXT NOT NULL, source_log TEXT NOT NULL, content_sha256 TEXT NOT NULL,
          snapshot_json TEXT NOT NULL, UNIQUE(character_id, content_sha256)
        );
        CREATE TABLE IF NOT EXISTS character_facts (
          character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
          field TEXT NOT NULL, value_json TEXT NOT NULL, source TEXT NOT NULL,
          confidence TEXT NOT NULL, observed_at TEXT NOT NULL, evidence TEXT,
          PRIMARY KEY(character_id, field)
        );
        CREATE TABLE IF NOT EXISTS character_observations (
          baseline_id INTEGER NOT NULL REFERENCES character_baselines(id) ON DELETE CASCADE,
          command TEXT NOT NULL, ordinal INTEGER NOT NULL, text TEXT NOT NULL,
          PRIMARY KEY(baseline_id, command, ordinal)
        );
        INSERT OR REPLACE INTO schema_metadata(key, value) VALUES ('schema_version', '3');
        """
    )


def persist(database: Path, audit: Audit, *, game: str = "GSIV") -> int:
    payload = json.dumps(audit.snapshot, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    connection = sqlite3.connect(database, timeout=10)
    try:
        ensure_schema(connection)
        with connection:
            connection.execute("INSERT OR IGNORE INTO characters(game, name) VALUES (?, ?)", (game, audit.character))
            character_id = connection.execute(
                "SELECT id FROM characters WHERE game = ? AND name = ? COLLATE NOCASE", (game, audit.character)
            ).fetchone()[0]
            connection.execute(
                """INSERT OR IGNORE INTO character_baselines
                   (character_id, captured_at, source_log, content_sha256, snapshot_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (character_id, audit.captured_at, str(audit.source_log), digest, payload),
            )
            baseline_id = connection.execute(
                "SELECT id FROM character_baselines WHERE character_id = ? AND content_sha256 = ?",
                (character_id, digest),
            ).fetchone()[0]
            connection.execute("DELETE FROM character_observations WHERE baseline_id = ?", (baseline_id,))
            for command, lines in audit.commands.items():
                connection.executemany(
                    "INSERT INTO character_observations(baseline_id, command, ordinal, text) VALUES (?, ?, ?, ?)",
                    ((baseline_id, command, ordinal, line) for ordinal, line in enumerate(lines)),
                )
            connection.executemany(
                "INSERT INTO character_observations(baseline_id, command, ordinal, text) VALUES (?, 'raw-log', ?, ?)",
                ((baseline_id, ordinal, line) for ordinal, line in enumerate(audit.raw_lines)),
            )
            for field, value in _facts(audit.snapshot).items():
                connection.execute(
                    """INSERT INTO character_facts
                       (character_id, field, value_json, source, confidence, observed_at, evidence)
                       VALUES (?, ?, ?, ?, 'observed', ?, ?)
                       ON CONFLICT(character_id, field) DO UPDATE SET
                         value_json=excluded.value_json, source=excluded.source,
                         confidence=excluded.confidence, observed_at=excluded.observed_at,
                         evidence=excluded.evidence""",
                    (
                        character_id, field, json.dumps(value, ensure_ascii=False), str(audit.source_log),
                        audit.captured_at, f"baseline:{baseline_id}",
                    ),
                )
        return baseline_id
    finally:
        connection.close()


def render_markdown(audit: Audit) -> str:
    data = audit.snapshot
    identity = data.get("identity", {})
    title = identity.get("name", audit.character)
    lines = [f"# {title}", "", f"Last audited: {audit.captured_at}", "", "## Verified baseline", ""]
    lines.extend(
        [
            f"- Race/profession: {identity.get('race', 'Unknown')} {identity.get('profession', 'Unknown')}.",
            f"- Level: {data.get('level', 'Unknown')} ({data.get('experience', 'Unknown'):,} experience)."
            if isinstance(data.get("experience"), int) else f"- Level: {data.get('level', 'Unknown')}.",
            f"- Displayed profession title: {identity.get('title', 'none')}.",
            f"- Society: {data.get('society', 'Unknown')}.",
            f"- Guild: {data.get('guild', 'Unknown')}.",
            f"- Training points: {data.get('training_points', {}).get('physical', '?')} physical / "
            f"{data.get('training_points', {}).get('mental', '?')} mental.",
        ]
    )
    lines.extend(["", "## Statistics", "", "| Stat | Base | Bonus | Enhanced | Enhanced bonus |", "|---|---:|---:|---:|---:|"])
    for code, value in data.get("stats", {}).items():
        lines.append(f"| {code} | {value['base']} | {value['bonus']} | {value['enhanced']} | {value['enhanced_bonus']} |")
    lines.extend(["", "## Skills", "", "| Skill | Bonus | Ranks |", "|---|---:|---:|"])
    for name, value in data.get("skills", {}).items():
        lines.append(f"| {name} | {value['bonus']} | {value['ranks']} |")
    lines.extend(["", "## Spell circles", ""])
    if data.get("spell_circles"):
        lines.extend(f"- {name}: {ranks} ranks." for name, ranks in data["spell_circles"].items())
    else:
        lines.append("- None observed.")
    lines.extend(["", "## Equipment snapshot", "", data.get("equipment_snapshot") or "No worn inventory reported."])
    if data.get("hands_snapshot"):
        lines.extend(["", data["hands_snapshot"]])
    if data.get("container_observations"):
        lines.extend(["", "## Protected container observations", ""])
        for observation in data["container_observations"]:
            lines.append(
                f"- {observation['container']}: contents observed and protected pending an item-by-item audit."
            )
    lines.extend(
        [
            "", "## Evidence", "",
            f"- Source log: `{audit.source_log}`",
            "- Captured through read-only `INFO`, `SKILLS`, `EXP`, membership, ability, spell, readiness, stow, and inventory commands.",
            "- Item properties remain unknown until separately inspected and recorded in the inventory dossier database.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--character", required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    arguments = parser.parse_args()
    audit = load_audit(arguments.character, arguments.log)
    baseline_id = persist(arguments.database, audit)
    if arguments.markdown:
        arguments.markdown.parent.mkdir(parents=True, exist_ok=True)
        arguments.markdown.write_text(render_markdown(audit), encoding="utf-8")
    print(json.dumps({"character": arguments.character, "baseline_id": baseline_id, "facts": len(_facts(audit.snapshot))}))


if __name__ == "__main__":
    main()
