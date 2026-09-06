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

`;lab sources` lists references actually supplied to the answer model and
retrieval status. `;lab context` reports category/dialogue availability.
Timing diagnostics distinguish context, model, evidence, and total latency
without logging raw private prompts.

See [Evidence gathering](Evidence-Gathering-Arc.md).
