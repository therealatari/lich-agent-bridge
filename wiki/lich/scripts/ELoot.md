# ELoot integration

Consult the maintained [ELoot documentation](https://gswiki.play.net/Lich:Script_Eloot)
and installed source for current commands and settings.

Looting, container destinations, appraisal policy, selling, and locksmith
routing are separate concerns. A general integration must not turn every
recorded possession into a sell candidate. Keep protected-item rules and
container choices in the user's private configuration.

For container bugs, identify the exact object and refresh boundary before
assuming a Lich cache defect. A delayed floating disk reaching a service room
differs from a tracked carried container. See
[container compatibility](../Lich-5.20-Container-Compatibility.md).

Local overlays are documented in the [patch notes](../../../patches/README.md).
Recheck them after upstream updates; a successful patch application is not
evidence of correct live routing or selling.
