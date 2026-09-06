"""Metadata-only latency recording and local timing summaries."""

from __future__ import annotations

from collections import defaultdict, deque
import json
import math
from pathlib import Path
import statistics
import threading
import time
from typing import Any, Mapping

from .actions import audit_log_path, default_state_directory

MAX_REPORT_RECORDS = 20_000


def timing_log_path() -> Path:
    return default_state_directory() / "timings.jsonl"


class TimingRecorder:
    """Append bounded-shape timing samples without payload or answer text."""

    def __init__(self, path: Path | None = None, *, clock=time.time):
        self.path = path or timing_log_path()
        self._clock = clock
        self._lock = threading.Lock()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    def record(self, metric: str, value_ms: float, **dimensions: object) -> None:
        self({"metric": metric, "value_ms": value_ms, **dimensions})

    def __call__(self, sample: Mapping[str, Any]) -> None:
        metric = sample.get("metric")
        value = sample.get("value_ms")
        if not isinstance(metric, str) or not metric.strip():
            return
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return
        numeric = float(value)
        if not math.isfinite(numeric) or numeric < 0:
            return
        record = {
            "timestamp": float(self._clock()),
            "metric": metric.strip(),
            "value_ms": round(numeric, 3),
        }
        for key in ("character", "capability", "status", "operation_id", "backend", "model", "effort"):
            candidate = sample.get(key)
            if isinstance(candidate, str) and candidate.strip():
                record[key] = candidate.strip()[:160]
        for key in ('tool_calls', 'rounds'):
            candidate = sample.get(key)
            if isinstance(candidate, int) and not isinstance(candidate, bool) and candidate >= 0:
                record[key] = candidate
        encoded = json.dumps(record, separators=(",", ":"), sort_keys=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(encoded + "\n")


def emit_timing(sink, metric: str, value_ms: float, **dimensions: object) -> None:
    """Best-effort instrumentation; measurement must never break gameplay."""

    if sink is None:
        return
    try:
        sink({"metric": metric, "value_ms": max(0.0, value_ms), **dimensions})
    except Exception:
        return


def timing_report(
    *,
    timings_path: Path | None = None,
    audit_path: Path | None = None,
    max_records: int = MAX_REPORT_RECORDS,
) -> dict[str, Any]:
    """Summarize direct samples and action audit phase deltas."""

    if max_records < 1:
        raise ValueError("max_records must be positive")
    samples: dict[str, list[float]] = defaultdict(list)
    timing_records = _read_records(timings_path or timing_log_path(), max_records)
    for record in timing_records:
        metric = record.get("metric")
        value = record.get("value_ms")
        if (
            isinstance(metric, str)
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and float(value) >= 0
        ):
            samples[metric].append(float(value))

    audit_records = _read_records(audit_path or audit_log_path(), max_records)
    phases: dict[str, dict[str, float]] = defaultdict(dict)
    phase_names = {
        "action_proposed": "submitted",
        "action_dispatched": "dispatched",
        "action_result": "result",
    }
    for record in audit_records:
        phase = phase_names.get(record.get("event"))
        action_id = record.get("action_id")
        timestamp = record.get("timestamp")
        if (
            phase
            and isinstance(action_id, str)
            and isinstance(timestamp, (int, float))
            and not isinstance(timestamp, bool)
        ):
            phases[action_id][phase] = float(timestamp)
    for phase in phases.values():
        _append_delta(samples, "action.submit_to_dispatch_ms", phase, "submitted", "dispatched")
        _append_delta(samples, "action.dispatch_to_result_ms", phase, "dispatched", "result")
        _append_delta(samples, "action.submit_to_result_ms", phase, "submitted", "result")

    return {
        "metrics": {
            metric: _summary(values)
            for metric, values in sorted(samples.items())
            if values
        },
        "sources": {
            "timing_records": len(timing_records),
            "action_audit_records": len(audit_records),
            "max_records_per_source": max_records,
        },
    }


def _read_records(path: Path, maximum: int) -> list[dict[str, Any]]:
    records: deque[dict[str, Any]] = deque(maxlen=maximum)
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                try:
                    value = json.loads(line)
                except (json.JSONDecodeError, UnicodeError):
                    continue
                if isinstance(value, dict):
                    records.append(value)
    except OSError:
        return []
    return list(records)


def _append_delta(
    samples: dict[str, list[float]],
    metric: str,
    phase: Mapping[str, float],
    start: str,
    end: str,
) -> None:
    if start not in phase or end not in phase:
        return
    delta = (phase[end] - phase[start]) * 1_000
    if math.isfinite(delta) and delta >= 0:
        samples[metric].append(delta)


def _summary(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min_ms": round(ordered[0], 3),
        "p50_ms": round(_percentile(ordered, 0.50), 3),
        "p95_ms": round(_percentile(ordered, 0.95), 3),
        "max_ms": round(ordered[-1], 3),
        "mean_ms": round(statistics.fmean(ordered), 3),
    }


def _percentile(ordered: list[float], fraction: float) -> float:
    index = max(0, math.ceil(len(ordered) * fraction) - 1)
    return ordered[index]
