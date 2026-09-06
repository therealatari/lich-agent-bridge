# Script authoring and supervision

Status: proposed bounded follow-on, 2026-09-01. This document is a design
contract, not a claim that online exception handling or automatic patching is
implemented.

## Outcome

LAB should act as the author and supervisor of deterministic Lich policies, not
as a conversational player on the combat path. GemStone and Lich react in
milliseconds; a model turn reacts in seconds. No model call may be the only
thing keeping a character alive.

The mature open Lich ecosystem is the starting policy corpus. Bigshot, Go2,
ELoot, EHerbs, and related scripts already encode decades of discovered game
messages, edge cases, and recovery behavior. LAB should search that corpus,
extract the relevant rule, and prefer configuration or a narrow overlay before
inventing a new private implementation.

The reproducible [community script corpus](../lich/Community-Script-Corpus.md)
provides the first bounded local source set. Its manifest preserves repository
ratings, popularity, revision, authorship, and checksums; the downloaded Ruby is
reference material and is never implicitly trusted or executed.

All Lich integrations must also follow the
[Lich authoring reference order](../lich/Lich-Authoring-References.md): use the
current local Lich source as runtime authority, use the human-reviewed YARD
documentation and DeepWiki for discovery, and require a concrete log or replay
before claiming a framework defect. Tests must reproduce the failure rather
than merely assert that a proposed workaround executes.

## Three timescales

### 1. Authoring: offline

The authoring loop may take minutes or hours:

1. A script produces a structured exception, failed outcome, or sanitized trace.
2. LAB inspects the current configuration and searches maintained Lich scripts
   for an existing solution.
3. LAB proposes the smallest configuration change or code overlay.
4. The original and modified decision logic are replayed over recorded cases.
5. Divergence is allowed only for the named target situation.
6. A low-risk canary validates the change before normal live use.

Every code rule records provenance: the triggering exception or trace, the
source script or wiki evidence consulted, the intended behavior change, and the
validation result. The goal is an auditable diff per rule, not a drifting fork
that can no longer absorb upstream fixes.

### 2. Exception handling: online and interrupt-driven

A deterministic controller handles safety before it asks for help. Only after a
safe posture or extraction has been reached may it raise a bounded question:

```json
{
  "situation": "unknown_creature",
  "snapshot": {"room_id": "123", "creatures": ["grifflet"]},
  "options": ["fight", "flee", "ignore", "ask_human"],
  "safe_state_reached": true
}
```

The answer must equal one offered option before it can become controller input.
If the agent is unavailable, late, malformed, or uncertain, the local safe
default remains in force. Open-ended analysis belongs in the offline authoring
loop, not this online seam.

The current stack does not yet provide this script-to-agent exception route.
When implemented, it must remain distinct from watcher alerts and from arbitrary
game commands.

### 3. Strategy: online at natural pauses

Between hunts or while safely resting, a full agent turn may select a registered
mode and arguments: where to hunt, whether to sell, what task to attempt, or
whether the current policy needs review. The local script executes that choice
and returns a verified result.

## Learning rule

Online exceptions are authoring input. A repeated exception should become a
candidate deterministic rule, not a permanent model dependency. Track at least:

- exception count per controller-hour;
- situation and selected safe outcome;
- repeats by normalized situation key;
- unresolved and human-escalated counts;
- replay/canary status for promoted rules.

Exception frequency should trend toward zero for a mature controller. A spike
is evidence that the game, configuration, or parser changed.

## Validation gate

Start where a wrong choice costs time or silver rather than a character:

1. loot classification and protected-item handling;
2. selling and banking;
3. travel and safe handoff;
4. resting and healing coordination;
5. combat only after the gate has demonstrated useful regression detection.

For each change, replay the same recordings through the baseline and candidate
policy and compare structured decisions. Reject unexplained divergence outside
the intended situation. A passing replay permits only a deliberately safe
canary; it is not by itself permission for unattended live deployment.

## Non-goals

- No model calls in the sub-second combat or survival loop.
- No automatic adoption of entire community scripts without inspection.
- No silent private fork whose local changes lack provenance.
- No conversion of one model answer into durable policy without replay evidence.
- No growing exception path merely because a model appears smarter than the
  deterministic rule.

This design extends the existing three-speed doctrine: Lich owns reflexes,
SessionHub owns bounded operations and verified outcomes, and the agent improves
the policy at safe timescales.
