# LAB dispatcher and bridge

`lab.lic` routes short management commands; `lab-bridge.lic` owns the running
bridge, hooks, workers, and private question routing. A management invocation
must not silently create another long-lived worker.

Use `;lab help` for the current interface. Bare `, QUESTION` is intercepted
locally for conversation rather than spoken to the game. Answers use the local
Familiar stream with presentation fallback where supported.

Status, state, sources, context, and stop remain responsive while a model is
working. Forget invalidates temporary dialogue and the current question without
erasing durable item/character records.

The bridge validates instructions independently of ActionBroker. Starting LAB
currently enables action execution and allowlisted auto-approval; use
`;lab actions off` for conversation without game commands. See
[Safety](../../project/Safety.md).

LAB requires its own runtime files, not a personal frontend or private gameplay
controller. See [Setup](../../project/Setup-and-Operations.md).
