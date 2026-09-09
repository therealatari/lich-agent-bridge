# Optional Bigshot Quick controllers

For bounded target finding rather than a room-pinned trial, use the opt-in
[`bigshot-quick-seek.json`](bigshot-quick-seek.json) example. Replace the synthetic
character, refuge room and return allowance with reviewed local settings, including the profile's
starting room/boundaries, attack routines, safety limits and eLoot choice. Load
the same private manifest on both sides after authorized deployment. It requests
one refuge-to-area-to-refuge outing, not a continuous hunt. Start in the configured
refuge; a cleared hunting room is not a safe handoff:

```text
labctl perform Testmage controller.quick-seek --arg 'preset="Reviewed-Encounter"' --expected-generation GENERATION --operation-timeout 90 --wait
```

Review the [seek contract](../../wiki/project/Controller-Controls.md#find-one-encounter-without-agent-round-trips).
No capability is installed by copying this example into a source checkout.
Live verification remains pending.

## Bounded named trial

This is an opt-in registration example, not an installed capability or proof of
live compatibility. The shipped `lich/lab-controllers.json` remains empty.

Before enabling, review compatible Bigshot Quick Combat and native Lich execution
guards/child lifecycle together. Bigshot must publish `quick_combat_runtime` and
`quick_combat_result` on its exact Script instance, and reject a stopping owner
before startup/reset or command entry. Both supervised startup/refuge v1 protocols
are required. Older Bigshot/Lich versions are unsupported.
Install `lab-controller-controls.rb` with the existing bridge dependencies.

Copy `bigshot-quick-trial.json` into your private configuration. Replace synthetic
`Testmage`, refuge-room `1000`, `return_seconds`, and the finite `sequence.values` list with your
explicitly reviewed values. Create the matching named trial in Bigshot Setup's
Quick Combat trial editor, with a bounded command list and action/time limits.
Keep only reviewed names in the enum. Numeric target IDs identify a current NPC,
not a creature noun. The target may have moved before the outing reaches it;
a missing target is a failed case, not permission to attack something else.
The profile must define a bounded area and a native route to/from the refuge.
Reserve 10–120 seconds for return inside a total operation limit of 300 seconds;
the remaining time must also fit work and ten seconds of equipment cleanup.

Set the existing `LAB_CONTROLLER_MANIFEST` to that same private manifest for both
the sidecar and Lich, then restart them only in an authorized session. There is
no new service or credential. The registration launches `bigshot` directly with
`quick trial probe-sequence --target 12345 --area profile`; no wrapper is required. The legacy
schema's `result_global` remains required but this controlled path derives its
terminal observation from the exact runtime, not that global.

After reviewing the live session's generation, safe handoff, and action approval
policy, an explicitly authorized small trial can use these commands (replace all
synthetic identities and IDs; do not run them as an unattended install step):

```text
labctl perform Testmage controller.quick-trial --arg 'sequence="probe-sequence"' --arg 'target_id=12345' --expected-generation GENERATION --operation-timeout 90
labctl control Testmage status --operation-id OPERATION_ID --expected-generation GENERATION
labctl control Testmage hold --operation-id OPERATION_ID --expected-generation GENERATION
labctl control Testmage resume --operation-id OPERATION_ID --expected-generation GENERATION
labctl control Testmage retreat --operation-id OPERATION_ID --expected-generation GENERATION
```

Use the operation ID returned by `perform`. Launch and mutations still need the
normal approval policy. Controls apply only while that exact operation/runtime
remains active; short trials can finish before a control arrives. Broker control
strings carrying a run token are intercepted by LAB, not sent as a second Bigshot
launch. Do not type those internal strings directly into Lich.

Ordinary operation stop requests bounded return after equipment recovery;
actions-off/hard revocation still denies further commands, including travel.
Hold is not extraction. A blocked return or unresolved equipment state fails the
handoff and blocks another agent test. Old `quick_area` and room-bound controlled
Quick registrations load for migration but cannot launch or accept controls.
Standalone manual Quick and the separate noncombat room-bound pilot are unchanged.
`sequence_dispatched` is not evidence that spells or attacks worked. Record fresh
survival, configured refuge arrival, owner release, and actual game effects
separately. LAB does not hash-pin the local named-trial settings file: Bigshot
resolves and snapshots the reviewed definition at startup. Do not edit it during
an admitted trial. See the [control contract](../../wiki/project/Controller-Controls.md).
