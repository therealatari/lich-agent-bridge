# Contributing to Lich Agent Bridge

LAB helps Lich developers inspect game state, ask grounded questions, and run
explicitly authorized, registered operations. It is an alpha project, not a
promise of unattended character safety.

For substantial changes, open an issue first describing the problem, evidence,
and proposed scope. Keep fixes focused; AI-assisted contributions receive the
same review and testing requirements as other contributions. Do not include
speculative changes to unrelated scripts.

Read [AGENTS.md](AGENTS.md), [Architecture](wiki/project/Architecture.md), and
[Safety](wiki/project/Safety.md). For Ruby/Lich work, follow the
[Lich authoring references](wiki/lich/Lich-Authoring-References.md) and verify
behavior against the Lich version involved. Do not infer a framework regression
from a test double alone.

## Development and verification

Use Python 3.11 or newer in a virtual environment and `pip install -e .`.
The [README development section](README.md#development) lists the Python,
Ruby, MCP, and documentation checks. Ruby inventory tests need the `sqlite3`
gem. For MCP use `npm ci` in `mcp`; its native dependency requires a supported
Node runtime and build tools. CI tests Python 3.11/3.13, Ruby 3.4, and Node 22
on Linux. Passing CI does not establish compatibility with every Lich install.

Use sanitized fixtures and fake transports for tests. CI must never log into
GemStone, start a real character session, call a paid model, or require private
credentials. Live tests require the player's separate, explicit authorization;
report exactly what was observed and what remains unverified.

A pull request should state the defect or requested behavior, explain the
smallest relevant change, list actual tests run, and identify safety or protocol
impacts. Update relevant documentation and generated SDK declarations when
their source contract changes. Do not hand-edit generated declarations.

## Privacy and security

Never commit account credentials, bearer tokens, local settings, character builds,
equipment dossiers, personal hunting routines, raw chat/game logs, model
transcripts, private instructions, or inventory databases. Redact
reproductions before uploading them. Inspect staged files and older commits,
not only `.gitignore`, before publishing a branch.

Report vulnerabilities as described in [SECURITY.md](SECURITY.md), not in public
issues. Preserve the separation between model advice and independently checked
actions. Safety controls, stale-state handling, and permission changes need
explicit regression tests and maintainer review.

Contributions are made under the repository's [GPL-3.0-only license](LICENSE).
Only contribute material you have permission to share; link to upstream
documentation instead of copying entire third-party wikis or script corpora.

## Pull-request workflow

Fork the public repository, create a focused branch, and open a pull request
against `main`. Main requires passing CI and resolved review conversations;
direct pushes, force pushes, and branch deletion are blocked. External workflow
runs may wait for maintainer approval. Never work around a failing safety check
by disabling it.

Start from this public repository's history. Private development archives are
not contribution branches: merging their history could publish private data.
