# Lich integration references

Lich owns the game's scripting runtime and proxy stream. LAB integrates with it
rather than reimplementing its state or depending on a specific frontend.

- [Authoring references](Lich-Authoring-References.md): source order and change gates.
- [Container contract](Lich-5.20-Container-Compatibility.md): observed state versus forced refresh.
- [Community script corpus](Community-Script-Corpus.md): local static-analysis reference data.
- [Script reference index](scripts/README.md): integration seams and upstream documentation.

Before changing XML, GameObj, script lifecycle, or command waiting, verify the
exact Lich revision and source implementation. A plain-Ruby test may differ
from the extensions loaded during Lich boot.
