# Container state and compatibility

Container investigations must distinguish tracked live state from local copies,
uninspected containers, and objects that move independently of the character.

## Contract to inspect

In the referenced Lich 5 implementation, GameObj publishes container contents
through a registry. A close event removes the tracked entry; staged inspection
results commit at a prompt boundary. The command-wait helper's completion
boundary therefore matters when judging freshness.

Inspect `lib/common/gameobj.rb`, `lib/common/xmlparser.rb`, and the relevant
command helper in the exact target checkout. See
[Lich authoring references](Lich-Authoring-References.md).

An array-shaped contents value for a tracked, open carried container is not,
by itself, evidence of a stale-cache bug. Neither is a failing standalone-Ruby
call whose behavior differs under Lich's class extensions.

## Investigation method

Record the item's exact ID, location, command, response boundary, registry state,
and server update sequence. Determine whether the issue concerns a carried
container, a room object, a delayed disk arrival, or script-owned references.

A forced OPEN/LOOK test proves that an extra scan occurs; it does not prove the
original cache was stale. Avoid adding network round trips to healing or combat
paths without a reproduced failure at that call site.

The [local patch notes](../../patches/README.md) distinguish disk routing from
experimental seller rescanning. Treat each patch separately and recheck against
the installed upstream revision.
