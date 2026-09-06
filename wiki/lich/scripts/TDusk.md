# Arena event attribution

TDusk is an external script; install and configure it independently of LAB.
The public repository contains no character-specific arena attack routine.

When investigating arena event attribution, distinguish local progression from
status announcements and another combatant's results. Inspect the upstream
version and replay the relevant messages before changing a parser. No private
arena overlay or supporting attack policy is required by LAB.

An event parser should require positive local attribution. A message that
mentions a round, creature, or result is not sufficient by itself to advance
the local sequence.
