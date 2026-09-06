# Developer testing with LAB

LAB gives Lich and script developers a structured interface to the actual game
environment. It does not grant an agent permission to invent commands, launch
arbitrary scripts, or experiment on a character without consent.

## Start with an isolated reproduction

Use the Python state, policy, operation, and HTTP tests plus the Ruby fake-Lich
harnesses before a live test. They exercise malformed input, state generations,
unknown identifiers, ownership conflicts, timeouts, rejection, and kill switches
without a game connection or model account. See [CONTRIBUTING](../../CONTRIBUTING.md).

Define success evidence before execution: what exact state or attributed output
must appear, what failure looks like, and how the character/item is restored.
“Command sent,” “script starting,” and “no exception” are not successful game
outcomes. Do not add retries that might repeat a non-idempotent game action.

## Player-authorized live sequence

1. Obtain authorization for the exact character, operation, resources, and
   recovery plan. Prefer a safe room and a harmless item. Do not begin with a
   hunt or combat-controller test.
2. Call `lab.snapshot` and inspect `character`, `generation`, `freshness`, room,
   resources, hands, and ownership. Stop if absent, stale, or inconsistent with
   the authorized setup.
3. Call `lab.capabilities` for that character. Use an advertised capability and
   its argument schema; discovery is not authorization and availability is not
   a guarantee that admission will succeed.
4. Resolve any target through current inventory/state. Use its exact current
   numeric object ID, not a remembered noun or an ID from a previous session.
5. Call `lab.perform` once. Direct MCP perform follows the operation to a
   terminal result. CLI `labctl perform --wait` supports the same workflow.
   Do not repeat a request just because the caller lost its connection.
6. Inspect `status`, `explanation`, `evidence`, `start_state`, and `end_state`.
   Require the capability's postconditions, not simply a transport success.
   `failed`, `timed_out`, and `interrupted` are terminal non-success outcomes.
7. Use `lab.watch` with the snapshot's cursor to inspect subsequent meaningful
   events, and read a fresh snapshot for handoff. A watch timeout means no event
   arrived in that interval, not that a command succeeded. After movement/combat,
   handoff requires the authorized safe room, survival, and released ownership.

MCP tools and their exact types are documented in the generated
[SDK declarations](../../mcp/src/sdk-types.generated.ts). For example, after
separate authorization and replacing the placeholder with a verified current ID:

```text
labctl state Testchar
labctl inventory Testchar "test item"
labctl perform Testchar item.audit --item-id CURRENT_NUMERIC_ID --method look --wait
labctl watch Testchar --once
```

`item.audit` may handle the bound item and restore it; it is not merely a database
query. Explicitly select `look` for an inspection-only diagnostic method; other
methods can involve spells. Every step still passes ActionBroker and the
independent Lich checks.

The isolated `lab.execute_code` tool can combine small state/query operations,
but permits only one perform per execution and has a short execution limit.
Use direct perform/watch for long operations; it is not a general script runner.

## Diagnosing conversation and latency

Conversation can request only advertised evidence tools; fixed character recon
still passes the independent action and approval gates. It cannot supply
arbitrary commands or launch scripts. `;lab sources` identifies evidence
actually supplied to the last answer; source diagnostics distinguish success,
missing data, disabled providers, and fallback decisions. `;lab context` reports
temporary dialogue availability; `;lab forget` clears it and invalidates older
in-flight answers without deleting durable knowledge.

Use `labctl timings` to compare context/retrieval, model, and end-to-end latency.
Model time includes startup, transport, and inference; do not claim one of those
is the bottleneck without a separate measurement. Questions have one active
slot per character, four globally, and the selected profile's deadline. Busy or
timeout is an explicit error, not permission to enqueue endless retries.

## Adding a supported test operation

If discovery has no suitable operation, propose the smallest capability needed
with its admission checks, exact target binding, evidence, restoration, and
failure tests. A controller must use the existing shared manifest and lifecycle.
Do not bypass the broker with a generic “run any script” capability. That would
change authority and requires a separate design and approval.

Record the tested commit, sanitized setup, capability/arguments, terminal result,
observed evidence, and what was not verified. Keep tokens, account information,
private conversations, and raw session logs out of public reports.
