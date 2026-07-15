# Attach harness-core in 15 minutes

You have an agent. It occasionally invents an ID, swaps a number, or cites a
date that isn't in your data. harness-core is a fail-closed fence around that:
**Plan → Compose → Post-Audit**. If the draft cites anything outside the
evidence you froze before composing, the verdict is `ok=False` and you block
the reply. No mid-turn healing, no "ask the model to fix it".

You implement **one object with three methods**. That's the whole integration.

## 0. See it run first (60 seconds)

```bash
git clone https://github.com/hihewh-byte/personal_health_agent
cd personal_health_agent
PYTHONPATH=packages/harness_core/src python examples/attach_minimal/run_demo.py
```

Turn 1 prints `PASS`. Turn 2 (the agent invents ticket `TCK-9999` and an
`admin-root` role) prints `FAIL-CLOSED: verdict.ok=False` and appends one row
to `examples/attach_minimal/failures.jsonl`. The demo is an in-memory IT-ticket
assistant — three small files, no LLM, no API key, no other domain knowledge.

## 1. The contract (frozen, v1)

Everything you need is in one module:
[`packages/harness_core/src/harness_core/interfaces.py`](../packages/harness_core/src/harness_core/interfaces.py)
— ≤15 public symbols, zero third-party dependencies. The core of it:

```python
from harness_core.interfaces import DomainAdapter, run_post_audit, emit_failure_event

class MyAdapter:                                # structural typing — no subclassing
    def build_plan(self, user_message: str):    # freeze evidence BEFORE composing
        return TurnPlanData(profile="...", tools_allowed=("..."), task_text=user_message)

    def extract_atoms(self, text: str):         # pull auditable tokens out of any text
        return re.findall(r"...", text)         # IDs, dates, amounts — your regexes

    def allowed_atoms(self, plan):              # the closed set a reply may cite
        return {...}                            # from YOUR database / API, not the LLM
```

One invariant matters: `extract_atoms` must use the **same normalization** for
the allowlist and for the draft, because membership is exact string equality.
Keeping both methods on one object makes that hard to get wrong.

## 2. Wire it into your turn loop

```python
adapter = MyAdapter()

plan    = adapter.build_plan(user_message)          # 1. plan (freeze evidence)
draft   = your_llm_call(user_message, evidence)     # 2. compose (your code, any model)
verdict = run_post_audit(adapter, plan, draft)      # 3. post-audit (fail-closed)

if verdict.ok:
    return draft
emit_failure_event("failures.jsonl", user_message=user_message, verdict=verdict)
return "Blocked: reply cited data outside the evidence base."   # your fallback
```

Violation codes you'll see: `atom_not_allowed:{atom}` (invented/swapped
citation) and machine-diff codes like `tool_not_allowed:{tool}` (tool drift).
Empty allowlist + any extracted atom ⇒ blocked. When in doubt, it blocks.

## 3. Failures feed the offline loop for free

`emit_failure_event` rows are a superset of what `harness-loop harvest`
consumes. Once you have a few real failures:

```bash
pip install -e packages/harness_loop
harness-loop harvest --e2e-jsonl failures.jsonl --out reports/loop/candidates.jsonl
```

Harvest → distill → gated proposal → **human PR** — the loop never rewrites
your prompts or catalogs at runtime ([threat model](threat-model-v0.md)).

## What harness-core will never do

- It never edits the draft or retries the model (fail-closed, not self-healing).
- It never phones home, needs a network, or requires a specific LLM vendor.
- It never imports your domain code; the boundary is the three-method adapter.

Questions / feedback: [Issue #1 — call for builders](https://github.com/hihewh-byte/personal_health_agent/issues/1).
The health app in this repo (PHA) is just the reference implementation of the
same contract (`pha/harness_core_adapter.py::PHANumericsAdapter`).
