# Community script corpus

`lab-lich-corpus` creates a local static-analysis corpus from Lich repository
metadata. It does not install or execute downloaded scripts.

From the source checkout:

```sh
PYTHONPATH=src python3 -m lich_agent_bridge.lich_corpus --help
```

Selection filters include game, extension, ratings, and popularity. Inspect the
configured filters and resulting manifest rather than assuming a large or
representative corpus. Sparse ratings can legitimately select very few scripts.

The ignored cache records repository metadata, relative paths, revisions,
checksums, and failures. A manifest marked incomplete is not a successful full
sync. Cached files remain reference data, not trusted plugins.

Before borrowing code, inspect authorship and licensing, check the current
upstream version, and follow the
[authoring gate](Lich-Authoring-References.md). Prefer supported configuration
or a narrow patch over a private reimplementation of mature script behavior.
