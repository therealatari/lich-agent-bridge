# Context system

The context assembler provides one bounded interface for building a question
packet. Callers should not coordinate retrieval, privacy filters, token budgets,
or provenance themselves.

## Evidence layers

1. LAB's identity, safety policy, and evidence-tool contract.
2. Current player intent and bounded temporary dialogue.
3. Structured state with character, generation, timestamp, and freshness.
4. Optional historical character/item knowledge and reference excerpts.
5. Recent game text, explicitly treated as untrusted observations.

Observed state describes when it was captured, not necessarily the world when
a slow answer arrives. Preserve unknown, zero, false, inactive, and omitted as
different states. A recorded profile cannot overrule newer observed values.

## Retrieval

Model-directed questions start without automatic broad wiki excerpts. Their
question-owned research session supports compact scoped discovery followed by
deliberate source/section reads. A bounded evidence workspace rebuilds the working
context each turn, retaining recovery handles for displaced results. Legacy search
callers retain the existing excerpt interface described below; see
[research semantics](Evidence-Gathering-Arc.md#research-sources) for scope ownership,
freshness, and paging limitations.

Discovery outlines expose each section's half-open character range in its source
revision. Parent ranges include descendant sections, making overlapping choices
visible before reading. These are full-section ranges, not evidence already
supplied: bounded reads report their actual range, completeness, and continuation
cursor. Offsets must not be compared across sources or revisions. This metadata
helps selection but does not guarantee that a model avoids redundant reads.

When verifying a selected stale GSWiki source finds a new revision, a whole-page
read or a uniquely matching structural section read supplies the replacement
passage in that same call. Returned handles and provenance identify the new
revision; `refreshed_from` records the prior snapshot. Missing or ambiguous section
paths require explicit replacement selection. Continuations never cross revisions,
and snapshots already being read remain pinned for the question.

Successful exact-page verification uses the shared live-source cache, before
checking the network rate limiter. Later questions can reuse that page within
the existing cache lifetime, retaining its original retrieval timestamp and
receiving their own independent handles. New or expired pages still pass the
limiter; failed refreshes remain explicitly stale. This does not make cached
evidence current indefinitely or remove the configured online-policy gate.

The Markdown adapter reads only the configured root. Selected-character pages
and associated topic pages may be used from a private knowledge directory;
other characters' notes are excluded. Gameplay questions avoid project
implementation plans, while development questions can retrieve technical docs.
Curated gameplay passages must match a topic heading or multiple distinct query
terms rather than qualify through one incidental body word. Single-term
lookups and selected-character build records retain their existing routing.
Follow-up prompt labels are not treated as search topics.

Explicit spell questions prioritize canonical spell evidence over incidental
mentions. Current-spell queries exclude deprecated pages and unresolved
redirects unless history is requested. Relevant recorded skill summaries retain
their date and historical provenance.

The GSWiki adapter searches an optional local SQLite FTS mirror. Canonical URL
and revision deduplication occurs before budgeting. Sufficient local evidence
does not trigger redundant web work; missing or stale evidence can use configured
fallback. Source status distinguishes success, disabled, unavailable, and
not-needed. A fixture that merely proves a lookup occurred does not establish
that the right passage reached the model.

Research discovery uses three bounded FTS lanes (general, title, and non-catalog
matches, including saved posts), twelve rows each, deduplicated before existing one-hop
redirect resolution. A pure ranker then prioritizes distinct title/heading matches,
numbered spell titles, and query intent over repeated body keywords. Catalog and
archive title hints are adjusted for shopping/history questions, but archive
location alone does not penalize a source for ordinary mechanics questions.
Only catalog editions are diversified with backfill; distinct archived references
are not presumed duplicates. At most six candidates still
reach the model, subject to the existing output allowance. Legacy excerpt-search
callers keep their prior retrieval path.

Each candidate's `ranking` field explains lexical match counts, intent, and a
kind hint. These are relevance heuristics, not authority or truth scores. They
cannot infer unknown terminology or guarantee all relevant pages survived the
shortlist. See the [ranking plan](Discovery-Ranking-Plan.md) for tests and limits.

## Character and item knowledge

INFO/SKILLS observations carry source, completion, observation time, generation,
and level context. Only validated observations update the private character
database. Infomon cache values without verified observation provenance do not
establish freshness.

Inventory dossiers retain exact observed object IDs, descriptive fingerprints,
facts, locations, and provenance. IDs can change, and recorded location is not
proof that an item remains accessible. Queries inspect recorded knowledge;
they do not silently scan live containers.

## Dialogue and cancellation

Temporary per-character dialogue is bounded and cleared by sidecar restart,
session-generation replacement, or `;lab forget`. It helps resolve follow-up
questions without making prior model answers authoritative.

Question cancellation suppresses the result and revokes owned pending recon.
A blocked worker retains its concurrency slot until it actually exits.
Durable inventory and character records are not deleted by forgetting a question.

## Diagnostics

`;lab sources` lists references in the final answer model's selected evidence,
distinguishing discovery snippets from read passages, and
retrieval status. `;lab context` reports category/dialogue availability.
Timing diagnostics distinguish context, model, evidence, and total latency
without logging raw private prompts.

See [Evidence gathering](Evidence-Gathering-Arc.md).
