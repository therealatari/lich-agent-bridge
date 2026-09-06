# Developer reliability requirements

LAB's developer interfaces should make evidence-backed testing possible without
turning a model response into unrestricted game control.

## Required invariants

- One question per character and a bounded global worker count.
- One end-to-end deadline across assembly, model calls, and evidence work.
- Forget/session fences prevent old answers or temporary dialogue from being
  committed after invalidation.
- Cancelled work retains its capacity slot until its worker exits.
- Model child-process and transport resources close on success, failure,
  timeout, and cancellation.
- Live, historical, unavailable, inactive, and budget-omitted facts remain distinct.
- Reported sources match evidence actually delivered to the model.
- Canonical mechanics outrank incidental development text for gameplay questions.
- Character questions use current observed data when available; verified recon
  can supply missing categories behind existing execution gates.

## Test evidence

Use deterministic source, adapter, broker, and lifecycle tests. Include
interleavings that pause publication, model completion, operation admission,
and approval waiting; happy-path tests alone do not establish cancellation
or identity safety.

Measure context, model, evidence, and end-to-end latency separately. Optimize
a measured bottleneck without adding speculative caches or duplicate state.
A test proving a new mechanism executes is insufficient unless it also
reproduces the original failure.

Live verification is a distinct, authorized phase. Record the tested version,
sanitized conditions, observed result, and limitations. Private session history
does not belong in this public contract.
