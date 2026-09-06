import json
import tempfile
import unittest
from pathlib import Path

from lich_agent_bridge.timings import TimingRecorder, timing_report


class TimingTests(unittest.TestCase):
    def test_evidence_counts_survive_without_private_tool_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'timings.jsonl'
            recorder = TimingRecorder(path)
            recorder.record('ask.evidence_ms', 12, tool_calls=3, rounds=2,
                            arguments={'query': 'private question'})
            record = json.loads(path.read_text())
        self.assertEqual(record.get('tool_calls'), 3)
        self.assertEqual(record.get('rounds'), 2)
        self.assertNotIn('arguments', record)

    def test_evidence_counts_accept_only_nonnegative_integers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'timings.jsonl'
            recorder = TimingRecorder(path)
            for value in (False, -1, 'private text', 0.5, 0):
                recorder.record('ask.evidence_ms', 1, tool_calls=value, rounds=value)
            records = [json.loads(line) for line in path.read_text().splitlines()]
        for record in records[:-1]:
            self.assertNotIn('tool_calls', record)
            self.assertNotIn('rounds', record)
        self.assertEqual(records[-1]['tool_calls'], 0)
        self.assertEqual(records[-1]['rounds'], 0)

    def test_phase_metadata_excludes_private_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "timings.jsonl"
            recorder = TimingRecorder(path)
            recorder.record("ask.model_ms", 12, backend="codex-cli", model="configured-model",
                            effort="high", question="private question", answer="private answer")
            record = json.loads(path.read_text())
        self.assertEqual(record["backend"], "codex-cli")
        self.assertEqual(record["model"], "configured-model")
        self.assertEqual(record["effort"], "high")
        self.assertNotIn("question", record)
        self.assertNotIn("answer", record)

    def test_recorder_and_report_combine_direct_samples_with_action_phases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timings = root / "timings.jsonl"
            audit = root / "actions.jsonl"
            recorder = TimingRecorder(timings, clock=lambda: 100.0)
            recorder.record(
                "snapshot.age_ms",
                125.0,
                character="Testscout",
            )
            audit.write_text(
                "\n".join(
                    json.dumps(record)
                    for record in (
                        {"timestamp": 10.0, "event": "action_proposed", "action_id": "a1"},
                        {"timestamp": 10.2, "event": "action_dispatched", "action_id": "a1"},
                        {"timestamp": 10.7, "event": "action_result", "action_id": "a1"},
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            report = timing_report(timings_path=timings, audit_path=audit)

        self.assertEqual(report["metrics"]["snapshot.age_ms"]["count"], 1)
        self.assertEqual(report["metrics"]["snapshot.age_ms"]["p95_ms"], 125.0)
        self.assertAlmostEqual(
            report["metrics"]["action.submit_to_dispatch_ms"]["p50_ms"],
            200.0,
        )
        self.assertAlmostEqual(
            report["metrics"]["action.dispatch_to_result_ms"]["p50_ms"],
            500.0,
        )
        self.assertAlmostEqual(
            report["metrics"]["action.submit_to_result_ms"]["p50_ms"],
            700.0,
        )

    def test_report_ignores_malformed_and_incomplete_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timings = root / "timings.jsonl"
            audit = root / "actions.jsonl"
            timings.write_text('{broken\n', encoding="utf-8")
            audit.write_text(
                json.dumps(
                    {"timestamp": 10.0, "event": "action_proposed", "action_id": "a1"}
                )
                + "\n",
                encoding="utf-8",
            )

            report = timing_report(timings_path=timings, audit_path=audit)

        self.assertEqual(report["metrics"], {})
        self.assertEqual(report["sources"]["timing_records"], 0)


if __name__ == "__main__":
    unittest.main()
