# Setup and operations

LAB is installed from source alongside an existing Lich 5 installation. It does
not replace Lich login, stored accounts, or frontend configuration.

## Install the Python service

From the cloned repository:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
labctl setup
labctl config show
labctl doctor
./scripts/run-sidecar.sh
```

Set up the selected model backend independently. The default Codex CLI backend
uses the existing CLI login. API backends read credentials from the configured
environment-variable name. Local compatible servers require their own running
model endpoint.

The default settings file is
`~/.config/lich-agent-bridge/config.toml`; runtime state is under
`~/.local/state/lich-agent-bridge/`. Use `labctl config path` to inspect the
resolved location. A `--config PATH` or supported environment override can select
a different installation. Keep private data outside the public source checkout.

## Install Lich dependencies

Copy or symlink each file into the active Lich scripts directory:

- `lich/lab.lic`
- `lich/lab-bridge.lic`
- `lich/lab-inventory.lic`
- `lich/lich-state-core.rb`
- `lich/lab-controller-registry.rb`
- `lich/lab-controllers.json`

Lich resolves these dependencies in its scripts directory even when the
dispatcher itself is symlinked. Install a compatible Ruby SQLite dependency
for inventory tracking.

The public controller manifest is empty. Personal combat scripts, hunt profiles,
and character policy are neither bundled nor required for the bridge.

## Start deliberately

Starting the bridge is a live-game action. In an authorized session:

```text
;lab
;lab status
;lab actions off
, what information is available about this room?
```

Action execution and allowlisted auto-approval currently start enabled.
`;lab actions off` prevents command execution while retaining conversation;
`;lab stop` exits the bridge. Review [Safety](Safety.md) before enabling actions.

## Optional services and MCP

The user-service installer renders templates using the current clone and
configuration rather than a maintainer's paths. Inspect its `--help` and the
rendered units before starting them.

For MCP, from the source checkout:

```sh
cd mcp
npm ci
npm run build
cd ..
./scripts/run-mcp.sh
```

SessionHub defaults to loopback port 18765 and MCP to port 18766.
Do not expose these services to a network as an incidental troubleshooting step.
The optional frontend-state adapter is separate from agent startup.

## Knowledge and storage

Use setup to select an optional private Markdown root and GSWiki mirror.
`labctl wiki status` diagnoses the mirror; `labctl wiki refresh` refreshes it.
General-web fallback is separately opt-in. Downloaded references and script
corpora remain local data subject to their own licenses.

Configure `LAB_INVENTORY_DB` or the supported Lich-data settings to read the
same private inventory ledger used by the bridge. Different data paths can make
the service appear to have no inventory even when the Lich script has recorded
it. Verify resolved paths with doctor rather than copying another user's path.

## Diagnose without changing the game

Check service health, resolved configuration, selected backend, local files,
and existing logs first. Status/source/timing queries do not require new game
commands. Logins, script reloads, snapshots that issue commands, and live
operations require the user's authorization. Keep raw diagnostic data private.
