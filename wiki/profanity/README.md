# Frontend independence

[ProfanityFE](https://github.com/elanthia-online/ProfanityFE) is one frontend that
can connect through Lich. LAB's gameplay state and agent logic are independent
of which compatible frontend the user selects.

A frontend must pass private invocation input through Lich and render the
chosen local output stream or its fallback. Frontend-specific protocol frames
belong in an explicit adapter started by that frontend, not the general bridge.

Keep keybindings, layouts, login configuration, and user-specific paths private.
See [Architecture](../project/Architecture.md) and
[Frontend state](../project/Frontend-State-Protocol.md).
