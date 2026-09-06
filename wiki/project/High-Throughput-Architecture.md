# Interaction architecture

LAB separates three timescales so model latency does not become a game-safety
dependency.

| Layer | Responsibility |
| --- | --- |
| Lich runtime | Immediate state parsing, command checks, deterministic script behavior |
| SessionHub and capabilities | Bounded operations, ownership, deadlines, verified outcomes |
| Agent/model | Explanation, missing-evidence requests, and reviewed development decisions |

## Deep interfaces

A caller requests a named operation with validated arguments. The owning
capability handles admission, current identity, execution, evidence, and the
terminal result. Callers should not reproduce controller sequencing or infer
completion by counting transport responses.

The broker remains the single command-authority boundary shared by operations,
CLI, and MCP. A local utility sequence reduces avoidable round trips only when
the complete sequence is disclosed, individually allowlisted, and bound to the
same character, generation, room, and expiry.

## Responsiveness

Keep status and stop paths independent of model inference. Question admission
returns busy rather than building an unbounded queue. Cancellation wakes callers
and revokes owned pending work, while uncooperative work retains its slot.

Use server watches for bounded event waiting rather than repeatedly fetching
full state. Preserve cursors and terminal outcomes across client polling.
A watch timeout means no event was received during that interval.

## Extension boundary

The controller registry describes reviewed local capabilities and their
lifecycle. This source distribution intentionally has no bundled combat or
hunting profiles. New controllers require exact admission, ownership,
postconditions, cancellation behavior, and tests before live use.

A faster interface is not broader authority. Keep arbitrary shell, script,
SQL, movement, spending, and combat commands out of conversational evidence
requests. See [Architecture](Architecture.md) and [Safety](Safety.md).
