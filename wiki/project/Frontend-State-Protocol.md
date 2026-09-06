# Optional frontend-state feed

`despana-state.lic` is a presentation adapter over the frontend-neutral
`LichState::LichSource` extractor. It is independent of LAB's HTTP service and
does not issue game commands. LAB and the frontend are peer consumers of the
shared extractor; neither should automatically start or control the other.

## Envelope and identity

The adapter emits versioned `despanaState` XML frames containing canonical
base64-encoded JSON. The adapter and consumer validate envelope shape, version,
type, size, and payload structure. Protocol frames must not leak into Story.

A complete publication starts with session identity. Inactive or changed
identity clears character-derived presentation state before later frames are
accepted. Every payload includes observation time; unknown values are omitted.

The implementation publishes inventory, bounty, society, recent loot, combat,
experience, known spells, and cooldowns when the underlying Lich source exposes
them. Consumers must tolerate unavailable categories.

## Refresh and data ownership

A newly attached frontend explicitly starts or refreshes its adapter.
Change detection avoids unnecessary publication; session heartbeat and forced
attachment refresh establish the consumer's initial state.

Inventory comes from observed GameObj objects and relationships. Durable dossiers
are a separate system. Exact object IDs are observation-scoped and may change;
container relationships do not establish an object's current accessibility.

Recent loot requires explicit acquisition attribution. An item listed on the
ground is not proof that the character acquired it. Presentation capabilities
must come from trusted structured fields, not verbs inferred from prose.

See the [adapter](../../lich/despana-state-core.rb),
[extractor](../../lich/lich-state-core.rb), and their isolated tests for the
exact current protocol fields. The optional feed is not required to use LAB.
