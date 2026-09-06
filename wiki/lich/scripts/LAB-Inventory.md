# LAB Inventory

`lab-inventory.lic` maintains private character-scoped item dossiers from
attributed Lich observations. The ledger lives under the user's Lich data
directory unless configured otherwise; it is runtime data, not a repository
asset.

## Data ownership

A dossier records observed IDs, descriptive fingerprints, facts, provenance,
and locations. Live identity and historical knowledge remain distinct:
an old ID or remembered container relationship does not prove present access.

SQLite transactions are short and do not span a game wait. UTF-8 normalization
at the boundary prevents text and byte-string representations from producing
different identities. Script shutdown closes database resources.

Legacy records can be imported without destroying the recoverable input.
Repeated observations should reconcile rather than multiply unchanged facts.
Unknown quantities and charges remain unknown.

## Interface

The player interface is `;lab inventory ...`; use its help/status output for
current syntax. Read-only queries can inspect counts, item facts, recorded
scroll information, and provenance. Explicit refresh, learning, note, and
assessment commands have their own behavior and authority requirements.

Programmatic readers use the existing query interface and SessionHub inventory
search. An inventory search reads dossiers; it is not a hidden live container
scan. Configure the service to read the same ledger as the Lich script.

## Attribution

Match observations to exact current objects before recording item properties.
Repeated spell slots and identically named objects must stay distinct.
Body features or possessions omitted from ordinary output cannot be inferred
absent, and a frontend cannot invent information the data source never supplied.

Spell-bearing readable objects are identified by observed contents, not just
a noun. Preserve conservative unlock/charge state and source evidence.
Generic inventory knowledge is not an automatic sell list.

Character baseline imports and generated notes must use a private output
location. Public fixtures should use independent synthetic data.
