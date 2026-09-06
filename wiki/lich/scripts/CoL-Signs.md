# Society upkeep integration

Society abilities need their own names, resources, availability, and activation
semantics; they are not ordinary prepare/cast spells. Consult the current Lich
society/effect interfaces and upstream game references.

Use one configured owner for routine upkeep. Keep resource thresholds,
ability selections, and emergency policy in private character configuration.
An absent or omitted effect is unknown unless the source explicitly reports it
inactive.

LAB should render observed society state without inferring new command
authority from it. See [Lich authoring references](../Lich-Authoring-References.md).
