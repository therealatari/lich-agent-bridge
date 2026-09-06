# Security policy

LAB is alpha software. Security fixes target the current `main` branch; there
is no supported long-term release line or guaranteed response time yet.

## Reporting a vulnerability

Do not post secrets, exploitable details, private game logs, or account data in
public issues. Use this repository's GitHub **Security → Report a vulnerability**
when private vulnerability reporting is enabled. If that option is unavailable,
contact maintainer **therealatari** privately before sharing the report. A public
issue may request a private contact channel, but must omit exploit details.

Include the affected commit/version, a sanitized reproduction, expected and
actual behavior, impact, and whether a real game action occurred. Do not test
against someone else's character, account, endpoint, or data without permission.

## Deployment expectations

- Keep SessionHub and MCP on loopback. Do not expose them through a public
  listener, port forwarding, or an unauthenticated proxy.
- Protect local bearer tokens and provider credentials. Store credentials only
  in the supported external credential mechanisms, never committed settings.
- A selected model/provider can receive the question, relevant game state,
  excerpts, and temporary conversation context. Use only providers you trust
  with that data, and review custom instructions and knowledge sources.
- Game text and retrieved pages are untrusted observations, not instructions.
  Model output is advice; action admission and Lich-side checks remain separate.
- Bridge startup currently enables the standing allowlisted action delegation.
  For read-only use, issue `;lab actions off` and verify `;lab status` before
  attaching an action-capable agent. `;lab stop` is the local emergency control.

If a secret is exposed, revoke or rotate it first. Removing it from a later
commit does not remove it from history, clones, or caches. No scanner proves
that a repository is free of secrets or personal information.
