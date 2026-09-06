# Map integration

Keep Lich room IDs and game UIDs distinct in data and presentation. A displayed
room title is not a stable unique identity.

Map consumers should use the source's current room identity and preserve a
user's viewing state across unrelated room-population updates. Browsing a
different map is presentation, not permission to move.

Any click-to-move adapter must pass a validated destination through the normal
navigation authority boundary. Use [Lich source](../Lich-Authoring-References.md)
to verify current map and room APIs.
