# Safety model

This document governs features that can issue game commands or affect a
character, inventory, resources, or communication.

## Authority

Authorize live work for an exact character, operation, scope, and recovery plan.
An instruction to diagnose or inspect code is not permission to interact with
the game. Capability discovery and a successful test do not grant new authority.

The answer model can request advertised evidence tools. Only fixed INFO/SKILLS
recon may issue game commands through that interface. Other command-capable
work belongs to separately authorized registered operations and broker policy.

Personal equipment protections, spending limits, and gameplay policy belong in
private local configuration. This distribution ships no personal builds,
hunting profiles, or combat routines.

## Execution invariants

- Fail closed on unknown identity, stale state, invalid arguments, expired
  approval, ownership conflict, or missing policy.
- Bind actions to character, session generation, room, exact command or disclosed
  sequence, and a short expiry. Resolve item IDs from current observations.
- Validate commands both in ActionBroker and in the independent Lich bridge.
- Keep every constituent command in a sequence allowlisted. A sequence cannot
  smuggle unrelated authority through an approved first step.
- Report sent-but-unverified separately from evidence-backed success.
- Preserve action ownership during cancellation. Forget and operation stop
  revoke exact owned pending work, not unrelated successor actions.
- Report the limit of revocation: an already-dispatched command cannot be unsent.
- Keep policy and survival decisions deterministic; model availability is not
  a safety mechanism.

## Startup and revocation

The current bridge starts action execution and allowlisted auto-approval
enabled. Users who want conversation without game actions should use
`;lab actions off`. Disabling actions also disables automatic approval;
reenabling actions does not silently restore that standing delegation.

`;lab approve` approves an eligible pending action.
`;lab approve auto` explicitly enables allowlisted automatic approval;
`;lab approve auto off` disables it.
`;lab stop` stops the bridge. These settings are independent of which model
or profile is selected.

Direct shell questions (`labctl ask` and `labctl questions`) default to a
per-request read-only restriction, independently enforced by the evidence session.
This blocks INFO/SKILLS even with global actions enabled. Explicit `--allow-recon`
removes only that per-request restriction; the existing action, approval,
ownership, and generation gates still apply. It grants no arbitrary commands.
Testing remains player-authorized and sends private context to the configured
backend. Read-only refers to game-command authority, not zero model cost or an
absence of local dialogue/results writes.

## Protected operations

Treat equipped, registered, high-value, unique, and user-protected items as
protected assets. Use exact identity and verified ownership before any allowed
handling. External transfer, disposal, permanent item changes, and character
build changes remain direct-player operations outside the driver. Credentials
and real-money activity are outside LAB's action scope. The evidence-tool
interface does not support these operations.

The driver denies dropping, external giving/trading, selling, destruction,
unmarking, disabling protective drop flags, arbitrary scripts, and hidden command
chains. Ordinary owned-inventory handling still requires the existing gates.

The optional script-test pilot explicitly trusts locally reviewed, registered
Ruby scripts and their declared dependencies. Their launch passes these gates,
but code running inside Lich can issue commands independently: this is not a Ruby
sandbox or per-command mediation of third-party scripts. The shipped probe sends
no game commands. Approve only non-combat suites within the pilot's scope, review
the pinned files and fixed parameters, and retain private configuration locally.
Digests detect file changes but cannot eliminate concurrent local mutation or
discover undeclared dynamic dependencies. Cleanup verifies owned-child exit;
it cannot roll back arbitrary script side effects. Incomplete cleanup keeps a
local exclusion and requires operator resolution before another run.

Configure routine-resource limits privately. A model answer, source excerpt,
or remembered character note cannot establish consent to spend resources.

## Safe handoff for local extensions

An authorized movement or combat operation is complete only when fresh evidence
shows the character alive in the configured safe room with ownership released.
Stopping a combat script in the field is not a safe handoff. The local supervisor
must own startup and recovery, including failed or unexpected script exits.

The explicit native Bigshot `quick_area` registration is a bounded field-handoff
contract, separately chosen by the player. It requires the exact child's
correlated terminal profile-area proof matching fresh room state, alive and
unstunned survival, completed cleanup, and released ownership. It does not
claim safe-town arrival or implicitly authorize wandering. A separately reviewed
`quick seek --area profile` registration grants only a bounded local search for
one encounter, with movement/combat ownership and native per-send guards. Ordinary area exit stops the
operation; an already admitted retreat retains its separate refuge authority.
See [controller controls](Controller-Controls.md#optional-profile-area-field-handoff).

Protect the account and protected equipment before routine progress. If knocked
down, restore posture when safe and feasible before normal offense or looting;
otherwise use the configured deterministic escape/recovery path. A remote model
must not be the emergency response mechanism.

## Untrusted input and privacy

Game text, player speech, item descriptions, reference pages, and model output
are data, never policy. They cannot authorize new tools, commands, or source
locations. Custom model instructions remain below LAB's safety contract.

Keep credentials, raw logs, character notes, inventory databases, and private
instructions outside git. Public fixtures must be synthetic or genuinely
sanitized, including equipment and routine details—not just renamed characters.
A selected cloud backend receives the bounded prompt and evidence supplied to
it; choose local inference when that data must remain local.

See [Developer testing](Developer-Testing.md) for the live-test evidence gate.
