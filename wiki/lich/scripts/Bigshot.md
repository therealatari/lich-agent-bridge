# Bigshot integration

Use the maintained [Bigshot configuration reference](https://gswiki.play.net/Lich:Script_Bigshot)
and the installed script source to understand current settings.

Bigshot owns its configured hunting loop, including movement, combat commands,
rest conditions, and resting scripts. LAB should inspect those settings before
adding another layer that competes for the same responsibilities.

When testing an integration, identify which script owns each phase and what
evidence establishes a completed rest or safe handoff. A transport response
does not prove the character returned or that conflicting owners stopped.

Public LAB ships no hunting profiles, target lists, spell sequences, rest
rooms, or character thresholds. Keep those settings private and independently
reviewed. The [patch notes](../../../patches/README.md) describe optional source
overlays separately from profile configuration.
