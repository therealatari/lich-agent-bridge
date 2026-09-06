import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from lich_agent_bridge.lich_corpus import (
    CorpusCriteria,
    CorpusError,
    RepositoryEntry,
    parse_repository_list,
    select_entries,
    synchronize_corpus,
)


def entry(
    filename: str,
    *,
    game: str = "gs",
    total: int = 120,
    count: int = 12,
    downloads: int = 500,
) -> RepositoryEntry:
    return RepositoryEntry(
        filename=filename,
        game=game,
        size=100,
        last_update=1_700_000_000,
        author="Tester",
        downloads=downloads,
        rating_total=total,
        rating_count=count,
        tags="utility",
    )


class FakeRepository:
    host = "repo.example"
    port = 7157
    client_version = "test"

    def __init__(self, entries: tuple[RepositoryEntry, ...]):
        self.entries = entries
        self.downloaded: list[str] = []

    def list_entries(self) -> tuple[RepositoryEntry, ...]:
        return self.entries

    def download(self, selected: RepositoryEntry):
        self.downloaded.append(selected.filename)
        payload = f"# {selected.filename}\n".encode()
        return payload, {
            "md5sum": hashlib.md5(payload, usedforsecurity=False).hexdigest(),
            "uploaded by": selected.author,
            "timestamp": str(selected.last_update),
        }


class FlakyRepository(FakeRepository):
    def __init__(self, entries: tuple[RepositoryEntry, ...], failures: dict[str, int]):
        super().__init__(entries)
        self.failures = failures

    def download(self, selected: RepositoryEntry):
        remaining = self.failures.get(selected.filename, 0)
        if remaining:
            self.failures[selected.filename] = remaining - 1
            raise OSError("temporary repository reset")
        return super().download(selected)


class LichCorpusTests(unittest.TestCase):
    def test_parses_repository_columns_by_name(self):
        payload = (
            "file\tgame\tsize\tlast update\tauthor\tdownloads\trating total\t"
            "rating count\ttags\n"
            "bigshot.lic\tgs\t123\t1700000000\tTillmen\t5000\t150\t15\thunting\n"
        ).encode()
        parsed = parse_repository_list(payload)
        self.assertEqual(parsed[0].filename, "bigshot.lic")
        self.assertEqual(parsed[0].average_rating, 10.0)
        self.assertEqual(parsed[0].rating_count, 15)

    def test_selects_only_perfect_well_reviewed_gs_or_any_lic_files(self):
        available = (
            entry("perfect.lic"),
            entry("neutral.lic", game="any", total=110, count=11),
            entry("only-ten.lic", total=100, count=10),
            entry("nine-point-nine.lic", total=119, count=12),
            entry("dragonrealms.lic", game="dr"),
            entry("metadata.json"),
        )
        selected = select_entries(available, CorpusCriteria())
        self.assertEqual(
            [item.filename for item in selected], ["neutral.lic", "perfect.lic"]
        )

    def test_optional_download_floor_supports_a_broader_popularity_proxy(self):
        available = (
            entry("popular.lic", total=9, count=1, downloads=500),
            entry("obscure.lic", total=10, count=1, downloads=499),
        )
        criteria = CorpusCriteria(
            minimum_average=8,
            vote_count_greater_than=0,
            minimum_downloads=500,
        )
        self.assertEqual(
            [item.filename for item in select_entries(available, criteria)],
            ["popular.lic"],
        )

    def test_sync_writes_separate_scripts_and_provenance_manifest(self):
        repository = FakeRepository((entry("one.lic"), entry("two.lic", game="any")))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            manifest = synchronize_corpus(
                repository, output, CorpusCriteria(), workers=1
            )
            self.assertEqual(manifest["count"], 2)
            self.assertEqual(repository.downloaded, ["two.lic", "one.lic"])
            self.assertEqual((output / "gs" / "one.lic").read_text(), "# one.lic\n")
            saved = json.loads((output / "manifest.json").read_text())
            self.assertEqual(saved["criteria"]["vote_count_greater_than"], 10)
            self.assertEqual(saved["criteria"]["minimum_downloads"], 0)
            self.assertEqual(saved["source"]["rating_scale_maximum"], 10)
            self.assertRegex(saved["scripts"][0]["sha256"], r"^[0-9a-f]{64}$")

    def test_unsafe_repository_filename_fails_without_escaping_output(self):
        repository = FakeRepository((entry("../escape.lic"),))
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(CorpusError, "unsafe filename"):
                synchronize_corpus(
                    repository, Path(directory), CorpusCriteria(), workers=1
                )
            self.assertFalse((Path(directory).parent / "escape.lic").exists())

    def test_unsafe_repository_game_fails_without_escaping_output(self):
        repository = FakeRepository((entry("escape.lic", game="../gs"),))
        criteria = CorpusCriteria(games=("../gs",))
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(CorpusError, "unsafe game identifier"):
                synchronize_corpus(repository, Path(directory), criteria, workers=1)
            self.assertFalse((Path(directory).parent / "gs" / "escape.lic").exists())

    def test_transient_download_failure_is_retried(self):
        repository = FlakyRepository((entry("flaky.lic"),), {"flaky.lic": 1})
        with tempfile.TemporaryDirectory() as directory:
            manifest = synchronize_corpus(
                repository,
                Path(directory),
                CorpusCriteria(),
                workers=1,
                attempts=2,
            )
            self.assertTrue(manifest["complete"])
            self.assertEqual(manifest["count"], 1)

    def test_failed_sync_writes_truthful_partial_manifest(self):
        repository = FlakyRepository(
            (entry("good.lic"), entry("bad.lic")), {"bad.lic": 3}
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with self.assertRaisesRegex(CorpusError, "bad.lic"):
                synchronize_corpus(
                    repository,
                    output,
                    CorpusCriteria(),
                    workers=1,
                    attempts=1,
                )
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertFalse(manifest["complete"])
            self.assertEqual(manifest["selected_count"], 2)
            self.assertEqual(manifest["count"], 1)
            self.assertEqual(len(manifest["failures"]), 1)

    def test_valid_manifest_record_resumes_without_redownload(self):
        selected = (entry("cached.lic"),)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            synchronize_corpus(
                FakeRepository(selected), output, CorpusCriteria(), workers=1
            )
            second = FakeRepository(selected)
            manifest = synchronize_corpus(
                second, output, CorpusCriteria(), workers=1
            )
            self.assertEqual(second.downloaded, [])
            self.assertTrue(manifest["complete"])


if __name__ == "__main__":
    unittest.main()
