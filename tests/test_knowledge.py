import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from lich_agent_bridge.gswiki import main as gswiki_main
from lich_agent_bridge.gswiki import sync, wikitext_to_text
from lich_agent_bridge.knowledge import (
    BraveWebSearchSource,
    KnowledgeBase,
    LiveGSWikiSource,
)
from lich_agent_bridge.settings import OnlineFallbackPolicy


class FakeResponse:
    def __init__(self, payload):
        import json

        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit=None):
        return self.body


def one_page_opener(request, *, timeout):
    query = parse_qs(urlsplit(request.full_url).query)
    namespace = int(query["gapnamespace"][0])
    return FakeResponse(
        {
            "batchcomplete": True,
            "query": {
                "pages": [
                    {
                        "pageid": 42,
                        "ns": namespace,
                        "title": "War Cries",
                        "revisions": [
                            {
                                "revid": 9001,
                                "timestamp": "2026-08-30T00:00:00Z",
                                "slots": {
                                    "main": {
                                        "content": (
                                            "Seanette's Shout grants +20 AS at rank 40."
                                        )
                                    }
                                },
                            }
                        ],
                    }
                ]
            },
        }
    )


def tether_opener(request, *, timeout):
    query = parse_qs(urlsplit(request.full_url).query)
    namespace = int(query["gapnamespace"][0])
    return FakeResponse(
        {
            "batchcomplete": True,
            "query": {
                "pages": [
                    {
                        "pageid": 706,
                        "ns": namespace,
                        "title": "Tenebrous Tether (706)",
                        "revisions": [
                            {
                                "revid": 7061,
                                "timestamp": "2026-09-01T00:00:00Z",
                                "slots": {
                                    "main": {
                                        "content": (
                                            "Tenebrous Tether immobilizes a target and "
                                            "has updated mechanics."
                                        )
                                    }
                                },
                            }
                        ],
                    },
                    {
                        "pageid": 7060,
                        "ns": namespace,
                        "title": "Mind Jolt (706)",
                        "revisions": [
                            {
                                "revid": 7060,
                                "timestamp": "2026-09-01T00:00:00Z",
                                "slots": {
                                    "main": {
                                        "content": "#REDIRECT [[Tenebrous Tether (706)]]"
                                    }
                                },
                            }
                        ],
                    },
                ]
            },
        }
    )


class LiveOpener:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def __call__(self, request, *, timeout):
        self.calls.append((request, timeout))
        return FakeResponse(self.payload)


def live_tether_payload():
    return {
        "query": {
            "pages": [
                {
                    "pageid": 706,
                    "ns": 0,
                    "title": "Tenebrous Tether (706)",
                    "revisions": [
                        {
                            "revid": 7061,
                            "timestamp": "2026-09-01T00:00:00Z",
                            "slots": {
                                "main": {
                                    "content": "Tenebrous Tether has updated mechanics."
                                }
                            },
                        }
                    ],
                }
            ]
        }
    }


def brave_payload():
    return {
        "web": {
            "results": [
                {
                    "title": "Spell mechanics guide",
                    "url": "https://example.test/spells/706",
                    "description": "A bounded external reference excerpt.",
                }
            ]
        }
    }


class ContinuingOpener:
    def __init__(self):
        self.calls = 0

    def __call__(self, request, *, timeout):
        self.calls += 1
        first = self.calls == 1
        pages = [
            {
                "pageid": 100,
                "ns": 0,
                "title": "Alpha technique",
                **(
                    {
                        "revisions": [
                            {
                                "revid": 101,
                                "timestamp": "2026-08-30T00:00:00Z",
                                "slots": {"main": {"content": "alpha knowledge"}},
                            }
                        ]
                    }
                    if first
                    else {}
                ),
            },
            {
                "pageid": 200,
                "ns": 0,
                "title": "Beta technique",
                **(
                    {}
                    if first
                    else {
                        "revisions": [
                            {
                                "revid": 201,
                                "timestamp": "2026-08-30T00:00:00Z",
                                "slots": {"main": {"content": "beta knowledge"}},
                            }
                        ]
                    }
                ),
            },
        ]
        payload = {"query": {"pages": pages}}
        if first:
            payload["continue"] = {"rvcontinue": "200|201", "continue": "||"}
        return FakeResponse(payload)


class KnowledgeBaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.wiki = self.root / "wiki"
        (self.wiki / "characters").mkdir(parents=True)
        (self.wiki / "characters" / "Testscout.md").write_text(
            "# Testscout\n\n## Combat\nTestscout uses Berserk with a two-handed maul.\n",
            encoding="utf-8",
        )
        self.database = self.root / "gswiki.sqlite3"
        sync(
            self.database,
            namespaces=(0,),
            delay=0,
            opener=one_page_opener,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_search_blends_character_notes_and_external_reference(self):
        knowledge = KnowledgeBase(
            wiki_root=self.wiki, gswiki_database=self.database
        )

        results = knowledge.search(
            character="Testscout", question="Which warrior guild war cry helps his AS?"
        )

        self.assertTrue(any(result.source.endswith("Testscout.md") for result in results))
        external = next(result for result in results if result.title == "War Cries")
        self.assertEqual(external.revision_id, 9001)
        self.assertIn("+20 AS", external.text)

    def test_character_profiles_are_isolated(self):
        (self.wiki / "characters" / "Testmage.md").write_text(
            "# Testmage\n\nTestmage uses focused implosion.\n", encoding="utf-8"
        )
        knowledge = KnowledgeBase(wiki_root=self.wiki)

        results = knowledge.search(
            character="Testscout", question="Could Testscout use focused implosion?"
        )

        rendered = "\n".join(result.text for result in results)
        self.assertIn("Berserk", rendered)
        self.assertNotIn("implosion", rendered)

    def test_unrelated_character_sections_do_not_hide_general_reference(self):
        (self.wiki / "characters" / "Testscout.md").write_text(
            """# Testscout

## Combat
Testscout uses Berserk with a two-handed maul.

## Herbs
Testscout carries acantha leaf.

## Society
Testscout belongs to the Council of Light.

## Equipment
Testscout wears heavy armor.
""",
            encoding="utf-8",
        )
        (self.wiki / "lich").mkdir()
        (self.wiki / "lich" / "Authoring.md").write_text(
            "# Lich authoring references\n\nUse YARD and DeepWiki for API discovery.\n",
            encoding="utf-8",
        )
        knowledge = KnowledgeBase(wiki_root=self.wiki)

        results = knowledge.search(
            character="Testscout", question="Lich YARD DeepWiki references"
        )

        self.assertTrue(
            any(result.source == "wiki/lich/Authoring.md" for result in results)
        )
        self.assertLessEqual(
            sum(result.source.endswith("Testscout.md") for result in results), 1
        )

    def test_missing_external_database_degrades_to_curated_notes(self):
        knowledge = KnowledgeBase(
            wiki_root=self.wiki, gswiki_database=self.root / "missing.sqlite3"
        )

        results = knowledge.search(character="Testscout", question="Berserk weapon")

        self.assertEqual(results[0].authority, "curated project knowledge")
        self.assertEqual(results.diagnostics[1].status, "missing")

    def test_missing_local_mirror_reaches_live_gswiki_with_provenance(self):
        opener = LiveOpener(live_tether_payload())
        source = LiveGSWikiSource(
            cache_path=self.root / "live-cache.json",
            opener=opener,
            now=lambda: datetime(2026, 9, 6, tzinfo=UTC),
            min_request_interval_seconds=0,
        )
        knowledge = KnowledgeBase(
            wiki_root=self.wiki,
            gswiki_database=self.root / "missing.sqlite3",
            online_fallback=OnlineFallbackPolicy.WHEN_NEEDED,
            live_gswiki=source,
        )

        results = knowledge.search(
            character="Testmage", question="what are the updated mechanics of 706?"
        )

        live = next(item for item in results if item.authority == "live GSWiki API")
        self.assertEqual(live.title, "Tenebrous Tether (706)")
        self.assertEqual(live.revision_id, 7061)
        self.assertEqual(live.retrieved_at, "2026-09-06T00:00:00+00:00")
        self.assertEqual(results.diagnostics[2].status, "success")
        self.assertEqual(len(opener.calls), 1)

    def test_sufficient_local_mirror_result_skips_live_lookup(self):
        opener = LiveOpener(live_tether_payload())
        source = LiveGSWikiSource(
            cache_path=None,
            opener=opener,
            min_request_interval_seconds=0,
        )
        knowledge = KnowledgeBase(
            wiki_root=self.wiki,
            gswiki_database=self.database,
            online_fallback=OnlineFallbackPolicy.WHEN_NEEDED,
            live_gswiki=source,
        )

        results = knowledge.search(character="Testscout", question="War Cries")

        self.assertTrue(any(item.title == "War Cries" for item in results))
        self.assertEqual(results.diagnostics[2].status, "not_needed")
        self.assertEqual(opener.calls, [])

    def test_enabled_credentialed_general_web_is_only_used_after_gswiki_fails(self):
        opener = LiveOpener(brave_payload())
        web = BraveWebSearchSource(
            enabled=True,
            credential_env="TEST_BRAVE_KEY",
            environment={"TEST_BRAVE_KEY": "private-test-key"},
            opener=opener,
            min_request_interval_seconds=0,
            now=lambda: datetime(2026, 9, 6, tzinfo=UTC),
        )
        knowledge = KnowledgeBase(
            wiki_root=self.wiki,
            gswiki_database=self.root / "missing.sqlite3",
            online_fallback=OnlineFallbackPolicy.WHEN_NEEDED,
            general_web=web,
        )

        results = knowledge.search(character="Testmage", question="706 spell mechanics")

        external = next(item for item in results if item.authority.startswith("general web"))
        self.assertEqual(external.url, "https://example.test/spells/706")
        self.assertEqual(external.retrieved_at, "2026-09-06T00:00:00+00:00")
        self.assertEqual(results.diagnostics[3].status, "success")
        self.assertEqual(len(opener.calls), 1)
        self.assertEqual(
            opener.calls[0][0].get_header("X-subscription-token"), "private-test-key"
        )

    def test_live_gswiki_cache_failure_and_rate_diagnostics_are_bounded(self):
        opener = LiveOpener(live_tether_payload())
        source = LiveGSWikiSource(
            cache_path=self.root / "live-cache.json",
            opener=opener,
            now=lambda: datetime(2026, 9, 6, tzinfo=UTC),
            monotonic=lambda: 10.0,
            min_request_interval_seconds=1,
        )

        first, first_diagnostic = source.search("Tenebrous Tether 706", ("tenebrous", "706"))
        second, second_diagnostic = source.search("Tenebrous Tether 706", ("tenebrous", "706"))

        self.assertEqual(first_diagnostic.status, "success")
        self.assertEqual(second_diagnostic.status, "success")
        self.assertEqual([item.title for item in first], [item.title for item in second])
        self.assertEqual(len(opener.calls), 1)

        offline = LiveGSWikiSource(
            cache_path=None,
            opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError()),
            monotonic=lambda: 10.0,
            min_request_interval_seconds=1,
        )
        _, unavailable = offline.search("Tenebrous Tether", ("tenebrous",))
        _, limited = offline.search("Tenebrous Tether", ("tenebrous",))
        self.assertEqual(unavailable.status, "unavailable")
        self.assertEqual(limited.status, "rate_limited")

        oversized = LiveGSWikiSource(
            cache_path=None,
            opener=LiveOpener(live_tether_payload()),
            max_response_bytes=8,
            min_request_interval_seconds=0,
        )
        _, oversized_diagnostic = oversized.search("Tenebrous Tether", ("tenebrous",))
        self.assertEqual(oversized_diagnostic.status, "oversized")

        invalid = LiveGSWikiSource(
            cache_path=None,
            opener=LiveOpener(["not", "a", "mapping"]),
            min_request_interval_seconds=0,
        )
        _, invalid_diagnostic = invalid.search("Tenebrous Tether", ("tenebrous",))
        self.assertEqual(invalid_diagnostic.status, "unreadable")

    def test_natural_spell_question_prefers_the_canonical_page_over_redirect(self):
        database = self.root / "tether.sqlite3"
        sync(database, namespaces=(0,), delay=0, opener=tether_opener)
        knowledge = KnowledgeBase(
            wiki_root=self.wiki,
            gswiki_database=database,
            now=lambda: datetime(2026, 9, 1, tzinfo=UTC),
        )

        results = knowledge.search(
            character="Testmage", question="what are the updated mechanics of 706?"
        )

        self.assertEqual(results[0].title, "Tenebrous Tether (706)")
        self.assertEqual(results.diagnostics[1].status, "success")

    def test_local_source_diagnostics_distinguish_empty_unreadable_and_stale(self):
        empty = KnowledgeBase(wiki_root=self.wiki, gswiki_database=self.database)
        no_terms = empty.search(character="Testscout", question="it")
        self.assertEqual(no_terms.diagnostics[1].status, "empty")

        malformed = self.root / "not-a-mirror.sqlite3"
        malformed.write_text("not sqlite", encoding="utf-8")
        unreadable = KnowledgeBase(wiki_root=self.wiki, gswiki_database=malformed)
        self.assertEqual(
            unreadable.search(character="Testscout", question="Berserk").diagnostics[1].status,
            "unreadable",
        )

        stale = KnowledgeBase(
            wiki_root=self.wiki,
            gswiki_database=self.database,
            mirror_max_age_hours=1,
            now=lambda: datetime(2027, 1, 1, tzinfo=UTC),
        )
        self.assertEqual(
            stale.search(character="Testscout", question="War Cries").diagnostics[1].status,
            "stale",
        )

    def test_curated_markdown_is_read_at_search_time(self):
        page = self.wiki / "gsiv.md"
        page.write_text("# First fact\n\nThe old fact applies.\n", encoding="utf-8")
        knowledge = KnowledgeBase(wiki_root=self.wiki)

        self.assertTrue(
            any("old fact" in item.text for item in knowledge.search(
                character="Testscout", question="old fact"
            ))
        )
        page.write_text("# Second fact\n\nThe new fact applies.\n", encoding="utf-8")

        results = knowledge.search(character="Testscout", question="new fact")

        self.assertTrue(any("new fact" in item.text for item in results))

    def test_wikitext_conversion_keeps_searchable_labels(self):
        converted = wikitext_to_text(
            "== Combat ==\n[[Seanette's Shout|Shout]] gives '''+20 AS'''.<ref>note</ref>"
        )

        self.assertIn("Combat", converted)
        self.assertIn("Shout gives +20 AS", converted)
        self.assertNotIn("note", converted)

    def test_revision_continuation_does_not_overwrite_pages_with_placeholders(self):
        database = self.root / "continued.sqlite3"
        result = sync(
            database,
            namespaces=(0,),
            delay=0,
            opener=ContinuingOpener(),
        )
        knowledge = KnowledgeBase(wiki_root=self.wiki, gswiki_database=database)

        alpha = knowledge.search(character="Testscout", question="alpha")
        beta = knowledge.search(character="Testscout", question="beta")

        self.assertEqual(result.pages, 2)
        self.assertTrue(any("alpha knowledge" in hit.text for hit in alpha))
        self.assertTrue(any("beta knowledge" in hit.text for hit in beta))

    def test_failed_refresh_preserves_the_previous_usable_mirror(self):
        original = self.database.read_bytes()

        def unavailable(*_args, **_kwargs):
            raise OSError("offline")

        with self.assertRaises(OSError):
            sync(self.database, namespaces=(0,), delay=0, opener=unavailable)

        knowledge = KnowledgeBase(wiki_root=self.wiki, gswiki_database=self.database)
        results = knowledge.search(character="Testscout", question="War Cries")
        self.assertTrue(any(item.title == "War Cries" for item in results))
        self.assertEqual(self.database.read_bytes(), original)

    def test_gswiki_main_uses_database_from_explicit_settings_file(self):
        settings = Mock()
        settings.knowledge.gswiki_database = self.root / "configured.sqlite3"
        result = Mock(pages=1, namespaces=(0,), database=settings.knowledge.gswiki_database)

        with (
            patch("lich_agent_bridge.gswiki.Settings.load", return_value=settings) as load,
            patch("lich_agent_bridge.gswiki.sync", return_value=result) as run_sync,
            patch("builtins.print"),
        ):
            gswiki_main(
                [
                    "--config",
                    "/tmp/lab-config.toml",
                    "--namespace",
                    "0",
                    "--delay",
                    "0",
                ]
            )

        load.assert_called_once_with(path="/tmp/lab-config.toml")
        self.assertEqual(run_sync.call_args.args[0], settings.knowledge.gswiki_database)

    def test_gswiki_main_database_flag_overrides_settings(self):
        settings = Mock()
        settings.knowledge.gswiki_database = self.root / "configured.sqlite3"
        explicit = self.root / "explicit.sqlite3"
        result = Mock(pages=1, namespaces=(0,), database=explicit)

        with (
            patch("lich_agent_bridge.gswiki.Settings.load", return_value=settings),
            patch("lich_agent_bridge.gswiki.sync", return_value=result) as run_sync,
            patch("builtins.print"),
        ):
            gswiki_main(
                [
                    "--config",
                    "/tmp/lab-config.toml",
                    "--database",
                    str(explicit),
                    "--namespace",
                    "0",
                    "--delay",
                    "0",
                ]
            )

        self.assertEqual(run_sync.call_args.args[0], explicit)


if __name__ == "__main__":
    unittest.main()
