# Design decisions

## Frontend-independent integration

Lich owns game integration; LAB owns agent context and coordination; frontends
render presentation data. A frontend-specific adapter must not become a runtime
dependency of the general bridge.

## One authority path

CLI, MCP, and registered operations share SessionHub and ActionBroker.
The Ruby bridge independently validates instructions. Conversational evidence
requests use this path for fixed observations rather than arbitrary commands.

## Verified outcomes

Command dispatch is distinct from success. Capabilities report starting state,
attributed evidence, terminal status, and ending state. Historical item and
character records preserve provenance instead of masquerading as current state.

## One settings and knowledge interface

Validated configuration feeds all callers. Provider-specific details stay inside
model adapters; retrieval sources share one bounded provenance-aware interface.
Source installation and XDG/private local paths are portable defaults.

## Bounded dialogue and evidence

Temporary dialogue helps follow-ups while remaining non-authoritative.
Evidence gathering is model-directed within fixed request/round/deadline
limits. Cancellation invalidates answers and revokes exact owned pending work.

## Private gameplay policy

The public repository contains generic software, contracts, and synthetic tests.
Character builds, equipment, hunting routines, personal logs, and installed
configuration remain in private locations. Names alone are not anonymization.
