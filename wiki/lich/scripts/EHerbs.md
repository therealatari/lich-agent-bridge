# EHerbs integration

Consult [EHerbs documentation](https://gswiki.play.net/Lich:Script_Eherbs)
and its current source before changing healing configuration.

Healing decisions are latency-sensitive. Avoid unconditional OPEN/LOOK round
trips when the tracked container state already satisfies the runtime contract.
Tests should reproduce incorrect evidence or behavior, not merely confirm
that an added scan executes.

Keep herb locations, wound thresholds, and resting policy in private user
settings. Determine which script owns healing and when it can yield safely.
See [container compatibility](../Lich-5.20-Container-Compatibility.md).
