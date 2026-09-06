# Bounded model-directed evidence gathering

The model may answer from supplied context or ask LAB for missing observations.
This is an implemented application protocol, not general model tool authority.

## Tools

| Tool | Scope |
| --- | --- |
| `state.read` | Observed room, vitals, effects, wounds, scripts, and hands |
| `character.read` | Recorded/current stats and training; fixed INFO/SKILLS refresh when eligible |
| `inventory.search` | This character's recorded item dossiers |
| `knowledge.search` | Configured local wiki and permitted configured fallback |

Character, generation, provider configuration, and deadlines are application
bound. Model arguments cannot replace them. Every request batch is validated
before any member runs.

## Budget

A direct answer uses one model call. Evidence gathering allows at most three
rounds, four requests per batch, and eight total requests under one existing
question deadline. Identical requests reuse their first result rather than
repeating commands. The selected agent profile sets `evidence_result_chars`
(default 12,000) and `evidence_total_chars` (default 36,000). These are serialized
character allowances, not token counts, and do not change tool permissions,
request counts, or the question deadline. Tool payload packing follows the
per-result allowance while reserving 1,500 characters for its envelope.

Different knowledge queries returning the exact same result envelope can refer
back to the earlier rendered record rather than repeat its text. Changed
content, timestamps, revisions, or status remain separate evidence. Omitted
results are never reused as though their contents were supplied.

Individual and aggregate result budgets omit whole records with an explicit
unknown/omitted status; truncated source fragments must not be reported as
complete evidence. Raising an allowance does not force every source to return
more results or make an incomplete reference complete. Initial context retains
its separate bound. See [setup](Setup-and-Operations.md#evidence-allowances) for
configuration and privacy/performance tradeoffs.
If tool packing omits matching items, the result is `partial`, not `not_found`;
source diagnostics distinguish budget omissions from genuinely empty results.

All model adapters consume the same answer-or-request contract. Source text,
tool output, room descriptions, and item descriptions remain untrusted data.

## Character freshness

Recent same-session INFO/SKILLS observations can be reused. Missing, stale,
incomplete, or level-inconsistent categories may request registered
`character.recon`, with only the fixed `info` and `skills` commands.
Actions-off blocks execution, and approval remains independently required where
broker policy says so.

Recon requires a fresh starting snapshot, the bound generation and room, and
new completed observations followed by an advancing snapshot. Cached arrays,
unchanged timestamps, a sent result, or a model assertion cannot substitute
for that evidence. Skills must agree with the known observed level.

## Cancellation and persistence

Forget, timeout, and session replacement invalidate the question. Exact owned
pending recon is cancelled synchronously; late approvals cannot revive it.
Cancellation racing operation admission waits for the returned operation ID
to be revoked. Unrelated actions and successor operations remain untouched.
Already-dispatched commands cannot be unsent.

Only verified observations flow through the existing private persistence
adapter. The loop does not edit wiki pages or promote model output to truth.

## Verification

Tests cover direct answers, dependent/multiple sources, fresh reuse, rejected
arguments, whole-batch validation, actions-off, approval expiry, identity fences,
duplicates, budgets, injection-like source text, cancellation races, and
rendered provenance. Live tests require separate player authorization and must
report actual observed evidence, not just successful transport.
