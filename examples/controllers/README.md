# Optional Bigshot Quick trial

This is an opt-in registration example, not an installed capability or proof of
live compatibility. The shipped `lich/lab-controllers.json` remains empty.

Before enabling, review compatible Bigshot Quick Combat and native Lich execution
guards/child lifecycle together. Bigshot must publish `quick_combat_runtime` and
`quick_combat_result` on its exact Script instance, and reject a stopping owner
before startup/reset or command entry. Older Bigshot/Lich versions are unsupported.
Install `lab-controller-controls.rb` with the existing bridge dependencies.

Copy `bigshot-quick-trial.json` into your private configuration. Replace synthetic
`Testmage`, safe-room `1000`, and the finite `sequence.values` list with your
explicitly reviewed values. Create the matching named trial in Bigshot Setup's
Quick Combat trial editor, with a bounded command list and action/time limits.
Keep only reviewed names in the enum. Numeric target IDs identify a current NPC,
not a creature noun; inspect the current room and target before each trial.

Set the existing `LAB_CONTROLLER_MANIFEST` to that same private manifest for both
the sidecar and Lich, then restart them only in an authorized session. There is
no new service or credential. The registration launches `bigshot` directly with
`quick trial probe-sequence --target 12345`; no wrapper is required. The legacy
schema's `result_global` remains required but this controlled path derives its
terminal observation from the exact runtime, not that global.

After reviewing the live session's generation, safe handoff, and action approval
policy, an explicitly authorized small trial can use these commands (replace all
synthetic identities and IDs; do not run them as an unattended install step):

```text
labctl perform Testmage controller.quick-trial --arg 'sequence="probe-sequence"' --arg 'target_id=12345' --expected-generation GENERATION
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

This registration supports room-pinned trials, not moving watch/assist sessions.
Review escape settings before any retreat test. Stop/hold is not safe extraction;
`sequence_dispatched` is not evidence that spells or attacks worked. Record fresh
survival, configured safe-room arrival, owner release, and actual game effects
separately. LAB does not hash-pin the local named-trial settings file: Bigshot
resolves and snapshots the reviewed definition at startup. Do not edit it during
an admitted trial. See the [control contract](../../wiki/project/Controller-Controls.md).
