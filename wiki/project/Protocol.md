# Loopback protocol

The Lich bridge exchanges bounded JSON with SessionHub, normally at
`http://127.0.0.1:18765`. The separate optional
[frontend-state feed](Frontend-State-Protocol.md) is not this HTTP protocol.

Consult [protocol validation](../../src/lich_agent_bridge/protocol.py),
[HTTP routing](../../src/lich_agent_bridge/server.py), and the generated
[MCP types](../../mcp/src/sdk-types.generated.ts) for exact current schemas.

## State and questions

`POST /v1/state` admits a structured snapshot with explicit character,
game, random bridge generation, increasing sequence, and timezone-aware
observation time. A retired generation cannot become current again.
`POST /v1/event` admits meaningful events for the current generation.

`GET /v1/state/CHARACTER` reads the snapshot;
`GET /v1/watch/CHARACTER?cursor=N&timeout=30` waits for bounded events.
Unknown values remain absent rather than being guessed.

`POST /v1/observe` accepts bounded textual observations.
`POST /v1/ask` requests a private answer. Questions can request only the
advertised [evidence tools](Evidence-Gathering-Arc.md); they cannot supply
arbitrary commands. `GET /health` identifies the service and its capabilities
so clients can reject an incompatible listener.

## SessionHub interface

Authenticated JSON POST routes provide the shared CLI/MCP facade:

- `/v1/session/snapshot`
- `/v1/session/watch`
- `/v1/session/capabilities`
- `/v1/session/inventory/find`
- `/v1/session/wiki/search`
- `/v1/session/alerts`
- `/v1/session/sources`
- `/v1/session/context`
- `/v1/session/forget`
- `/v1/session/perform`
- `/v1/session/operation/watch`
- `/v1/session/operation/stop`

Capability discovery returns registered names and strict schemas. The bundled
controller manifest is empty; a client must not assume personal controller or
combat-profile availability.

Perform admits an operation and returns its stable ID. Watch that operation to
`succeeded`, `failed`, `timed_out`, or `interrupted`; avoid submitting
a duplicate merely because the caller lost its connection.
Sources reports supplied references and diagnostics, not raw prompts.
Forget clears temporary dialogue and invalidates owned in-flight work without
deleting durable inventory or character knowledge.

## Actions and observations

Authenticated action routes separate proposal, confirmation, dispatch, result,
and control. Credentials stay in private local token files and are never tool
arguments. Actions are bound to character, generation, room, and expiry.

A proposal contains either one allowlisted command or one fully disclosed
bounded utility sequence. Approval applies only to that exact proposal.
Automatic approval remains an independently revocable local delegation.
The bridge revalidates every instruction before execution.

Action status and completion evidence are distinct. Legacy completion can mean
only sent-but-unverified; a registered capability requires its own verified
postconditions. Generation replacement and actions-off invalidate pending work.
Exact operation cancellation does not disable unrelated work.

INFO/SKILLS records include source, observation timestamp, completeness, values,
and skills' observed level where applicable. Recon requires an advancing
same-generation snapshot containing fresh matching records; cached values or
a successful send do not establish completion.

## Failure behavior

Invalid arguments, stale generation, wrong character, changed room, expired
approval, missing evidence, and conflicting ownership fail closed.
Questions share one deadline across retrieval, inference, and evidence work.
Cancellation suppresses late answers and revokes pending owned recon; commands
already sent cannot be recalled.

Clients should use typed interfaces and surface errors truthfully rather than
guessing success from silence. See [Safety](Safety.md).
