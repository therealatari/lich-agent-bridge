# Release checklist

This checklist describes verification gates; it does not assert that a
particular release has passed them.

## Publication privacy

- Keep personal character notes, equipment, builds, routines, raw logs,
  databases, credentials, and private instructions out of the candidate.
- Replace personal fixtures with independent synthetic cases, not merely
  renamed versions of real loadouts or routines.
- Inspect reachable history, renamed paths, branches, tags, commit metadata,
  release artifacts, and caches. Deleting at HEAD does not remove history.
- Obtain explicit authority and a verified private recovery copy before any
  history rewrite or visibility change.
- Use secret scanning, but review privacy and redistribution separately:
  recognized-secret detectors do not identify all personal data.
- Verify licensing and attribution for borrowed code and external-script patches.

## Reproducibility

Run Python, Ruby, MCP, packaging, documentation-link, and privacy checks against
the exact candidate. Confirm source installation with portable configuration.
External-script harnesses must identify the upstream revision they tested.

Observe hosted CI separately from local results. Record skipped, blocked,
external, and live tests explicitly; none can be inferred from another suite's
success.

## Repository protections

After publication is explicitly authorized, configure branch protection or a
ruleset, required CI, resolved review conversations, and restricted force-push
and deletion. Keep Actions permissions minimal and credentials out of
pull-request jobs. Enable supported vulnerability reporting and secret/push
protection without claiming unavailable features are active.

See [Contributing](../../CONTRIBUTING.md) and [Security](../../SECURITY.md).
