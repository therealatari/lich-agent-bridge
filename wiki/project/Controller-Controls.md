# Exact-operation controller controls

Status: authenticated HTTP/CLI control admission and exact-child Quick runtime
binding are implemented with offline tests. No controller is registered by the
public distribution. This work does not deploy scripts or establish live
compatibility. The [direct Bigshot trial example](../../examples/controllers/README.md)
requires explicit local review and registration.

## Implemented interface

The matching Python/Ruby controller schemas accept actions of `kind: control`,
named `status`, `hold`, `resume`, or `retreat`. Each takes exactly one `run_id`
parameter of type `action_id`: 16 lowercase hexadecimal digits identifying the
original launch's broker action. Controls cannot contain script arguments or a
launch mode, become the controller's launch capability, or enter a command batch.
Mutating controls retain combat classification and confirmation policy. Status is
inspection. Immediate script kill is not a typed control or verified extraction.

Controllers opting in must declare `control_owner_scripts`, including their
native script and drawn from the existing `owner_scripts` exclusion list.
An exclusion is not permission to control a competing owner. The shipped registry
remains empty; synthetic fixtures are not active registrations.

`CapabilityRunner.control_controller(operation_id, character=...,
expected_generation=..., control=...)` submits a control through ActionBroker for
an existing active operation. It does not create another operation or relax the
one-operation-per-character rule. It verifies fresh identity and ownership,
retains the original launch token across secondary actions, and bounds pending
controls to 32 with at most five seconds of authority, never beyond the operation
deadline. The response includes the broker action and `applied: null`: admission
is not evidence that the control was applied.

`POST /v1/session/operation/control` uses the existing authenticated server and
requires exactly `character`, `operation_id`, `expected_generation`, and `control`.
It returns HTTP 202 for broker admission, 400 for invalid/stale requests, and 401
for missing/wrong authentication. No additional operation, listener, credential,
or model invocation is created. The matching CLI is:

```text
labctl control CHARACTER hold --operation-id OPERATION_ID --expected-generation GENERATION
```

The same command accepts `status`, `resume`, and `retreat`. It sends once and
prints admission JSON; it does not wait for application or retry ambiguities.
The HTTP/CLI path is tested through the actual local server with a synthetic
active controller. No MCP control tool is added by this slice.

Cancellation revokes exact owned pending controls and marks the original launch.
A dispatched control receives
a `stop_requested` marker through existing action-status observations; it cannot
be unsent. Unrelated actions are not revoked.

## Optional native Quick binding

The bridge launches opted-in controllers with native `Script.start_child`, pins
its exact returned Script object, original launch, character, and session, then
binds only that instance's fixed `quick_combat_runtime` publication using
`LabControllerControls::Binding`. No arbitrary method names or script-name
rediscovery are accepted. A fast completed run can supply its exact-instance
immutable `quick_combat_result` snapshot instead. Older native lifecycle or
Bigshot publication/guard implementations fail closed.

The available predicate checks current local run/session/room/ownership pins
without issuing commands. This slice is room-pinned trial support, not a generic
moving watch/assist controller. An admitted retreat may change rooms while its
controls are closed and bounded cleanup is observed.
The separate authority reader uses the existing authenticated action-status
transport on a bridge worker, never on Bigshot's owner thread.

The runtime interface is `request(action, valid: Proc)` plus immutable cached
`status`. Bigshot's owner checks the predicate immediately before applying a
queued control and again before deferred retreat. This requires no LAB import or
global in Bigshot. A rejected runtime request revokes and removes its lease.
The application predicate expires at the control's deadline, not the lifetime
of an already entered escape. Original launch authority governs that lifetime.

The lease reads cached broker authority for at most 250 milliseconds and obeys
absolute expiry. Observed revocation latches; missing, mismatched, or failed
authority reads deny. Refresh must run off the owner thread. Remote revocation
has polling latency; neither this cache nor control admission retracts an already
applied control or a server command already sent.

Controlled launches carry an internal `controller_deadline` copied from their
owning operation. Public action proposals cannot supply it. Dispatch `expires_at`
is only the admission window; it is not the launched controller's run deadline.
Startup publication wait is capped at three seconds and the operation deadline.
Failure before runtime publication cancels only the exact native child via
`kill(async: true)`, setting its stopping flag synchronously. Compatible Quick
startup/guards reject that flag before commands, including late publication.
This forced startup cancellation is not safe extraction.

Once bound, missing/revoked authority requests cooperative runtime stop, even
during retreat. Ordinary admitted retreat room movement is not itself a hard
revocation. Cleanup is awaited for three seconds (plus in-flight bounded polling);
incomplete cleanup reports failure and retains the exact-child exclusion until
join can be confirmed. No successor is killed or released by script name.

Queued acknowledgements and cached status are not attributed application results.
Terminal success still requires fresh survival, configured safe-room arrival,
and owner release. The bridge preserves these distinctions and the existing
broker/independent Lich checks, without another listener or authentication path.

### Bounded status presentation

Terminal runtime reports and control acknowledgements share the bridge's Quick
status presentation adapter. The existing 32,768-byte status limit and server
event depth/string limits remain unchanged. Small plain-command reports are
unchanged. A native grouped command is rendered as JSON **text**, marked
`command_presentation: "json"`; this is display data, not a new command or replay
format. Command text exceeding 4,000 characters is shortened and marked with
`command_omitted_characters`. Truncated JSON text need not be valid JSON.

If needed to meet the byte limit, only the oldest transcript entries are omitted;
the newest outcome/send/sequence records are retained. `observation_transport`
reports `omitted_entries` and the transmitted `retained_sequence_range`.
Bigshot's original `observations_total`, `observations_dropped`, and
`observation_sequence_range` still describe its own runtime ring, not this
additional transport trimming. Selected configuration names, limits, timings,
usage totals, control fields, and exact result identities are preserved. The
runtime's immutable snapshot is never modified. A summary which exceeds the
limit even without transcript entries is still rejected, not silently rewritten.
These presentation changes do not verify game effects or control application.

Verified offline with 712 Python tests and 111 focused Ruby bridge/controller
tests (675 assertions, no skips). A cross-check using Bigshot's actual controller
report producer and LAB's event validator covers simple commands, grouped
commands, oversized grouped transcripts, and long command text. This confirms
transport compatibility, not live combat behavior.

## Verification boundary

Tests use the production schemas, ActionBroker, CapabilityRunner, Ruby bridge
launch/dispatch/monitor and lease adapter, plus authenticated HTTP/CLI transport,
with synthetic state, authority, child lifecycle, and runtime observations. They cover
malformed controls, exact tokens, competing ownership, stale sessions/rooms,
expiry, cancellation, queue bounds, and queued-versus-applied reporting. They do
not prove live game behavior. Native child ownership is additionally source-backed
by Lich's `Script.start_child` lifecycle tests; native Quick stopping-owner
refusal belongs to Bigshot's startup/execution tests, not the synthetic bridge
fixture. Live verification requires explicit authorization.
