"""Deterministic discovery ranking, not a source-authority or truth classifier.

The same pure ranking interface serves Markdown and wiki candidates after their
adapters enforce scope and location policy. No model or additional I/O is used.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from .knowledge import KnowledgeExcerpt


_WORD = re.compile(r"[a-z0-9]+(?:['-][a-z0-9]+)*")
_HEADING = re.compile(r'^#{1,6}\s+(.+?)\s*$', re.MULTILINE)
_CATALOG = re.compile(r'^\w*shop:|\b(?:shop|catalog|storefront|merchant inventory)\b', re.I)
_ARCHIVE = re.compile(r'/(?:saved posts|archive|archives)\b', re.I)
_SHOPPING = {'buy', 'buying', 'purchase', 'purchasing', 'shop', 'shopping', 'sold', 'sale', 'price'}
_HISTORY = {'history', 'historical', 'old', 'former', 'deprecated', 'archive', 'replaced'}


def _words(text: str) -> frozenset[str]:
    # Small plural normalization, shared by query and documents; no substring
    # matching (e.g. "scar" must not count occurrences of "scare").
    return frozenset(word[:-1] if len(word) > 4 and word.endswith('s') and not word.endswith('ss')
                     else word for word in _WORD.findall(text.casefold()))


def source_kind(title: str) -> str:
    """Conservative title hints, also used by the bounded FTS recall lane."""
    if _CATALOG.search(title):
        return 'catalog'
    if _ARCHIVE.search(title):
        return 'archive'
    return 'reference'


@dataclass(frozen=True)
class RankedCandidate:
    excerpt: KnowledgeExcerpt
    freshness: str
    scope: str
    score: int
    kind: str
    title_matches: int
    heading_matches: int
    body_matches: int
    identifier_match: bool
    intent: str

    def explanation(self) -> dict:
        return {'kind_hint': self.kind, 'score': self.score, 'intent': self.intent,
                'title_terms': self.title_matches, 'heading_terms': self.heading_matches,
                'body_terms': self.body_matches, 'numbered_title': self.identifier_match}


def rank_discovery(candidates: Sequence[tuple[KnowledgeExcerpt, str, str]],
                   terms: Sequence[str]) -> list[RankedCandidate]:
    """Order relevant, unique snapshots with diverse catalog editions.

    Scores use distinct terms, not term frequency or document length. All query
    intent adjustments are lexical hints. Different editions are deferred, never
    removed, so catalog-only searches can still fill their available slots.
    """
    query = _words(' '.join(terms))
    if not query:
        return []
    intent = ('shopping' if query & _SHOPPING else
              'history' if query & _HISTORY or any(re.fullmatch(r'(?:19|20)\d{2}', t) for t in query)
              else 'reference')
    ranked = []
    for excerpt, freshness, scope in candidates:
        title = _words(excerpt.title)
        title_hits = len(query & title)
        headings = [_words(match[1]) for match in _HEADING.finditer(excerpt.text)
                    if _words(match[1]) != title]
        heading_hits = max((len(query & heading) for heading in headings), default=0)
        body_hits = len(query & _words(excerpt.text))
        if not (title_hits or heading_hits or body_hits):
            continue
        kind = source_kind(excerpt.title)
        score = 24 * title_hits + 8 * heading_hits + 2 * body_hits
        identifier = re.search(r'\(([0-9]{3,4})\)$', excerpt.title)
        identifier_match = bool(identifier and identifier[1] in query)
        # The wiki's numbered-title convention identifies a spell page more
        # specifically than an incidental number in a recipe or shop title.
        if identifier_match:
            score += 80
        if title and title <= query:
            score += 50
        if kind == 'catalog':
            score += 100 if intent == 'shopping' else -40
        elif kind == 'archive':
            # Storage under saved posts does not establish obsolescence. Some
            # current mechanics are documented only in archived primary posts.
            score += 80 if intent == 'history' else 0
        ranked.append(RankedCandidate(excerpt, freshness, scope, score, kind,
                                      title_hits, heading_hits, body_hits, identifier_match, intent))
    ranked.sort(key=lambda item: (-item.score, item.excerpt.title.casefold(),
                                  item.excerpt.source, str(item.excerpt.revision_id)))
    selected, deferred, identities, families = [], [], set(), set()
    for item in ranked:
        excerpt = item.excerpt
        identity = (item.scope, excerpt.source, excerpt.revision_id if excerpt.revision_id is not None
                    else hashlib.sha256(excerpt.text.encode()).hexdigest())
        if identity in identities:
            continue
        identities.add(identity)
        # Wiki catalog editions share the path before their slash. Do not merge
        # unrelated reference subpages or guess families from body similarities.
        family = (item.kind, excerpt.title.casefold().split('/', 1)[0])
        if item.kind == 'catalog' and family in families:
            deferred.append(item)
        else:
            selected.append(item)
            if item.kind == 'catalog':
                families.add(family)
    return selected + deferred
