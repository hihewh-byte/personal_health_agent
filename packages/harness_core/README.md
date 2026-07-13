# harness-core (vendored in PHA)

Thin **domain-agnostic** online control plane. Part of the **Harness product family**:

```text
┌─────────────────────────────────────────────────────────────────┐
│  Product family                                                  │
│                                                                  │
│  harness-core          Online thin core (this package)           │
│    Plan → Compose → Post-Audit · fail-closed                     │
│                                                                  │
│  Official Loop Suite   Offline evolution (not in this package)   │
│    Reflection Critic · Loop A (global) · Loop B (per-user)       │
│    → packages/harness_loop (skeleton) · PHA = reference plugin   │
│                                                                  │
│  Your Agent            Domain Adapter + plugin assets only       │
└─────────────────────────────────────────────────────────────────┘
```

**Commercial / OSS pitch:** installing harness-core means you get a **deterministic online fence** plus a documented path to an **auditable offline evolution loop** (proposal → veto → human PR). Evolution code stays out of the thin core so Core remains domain-agnostic; the suite is the official companion, not an afterthought.

| Layer | Owns | Must not own |
|-------|------|--------------|
| **harness-core** | TurnPlan, phase order, integrity codes, plan↔actual | Catalogs, SQL, domain audits, Loop harvest/distill |
| **Official Loop Suite** | Offline harvest/critic/propose/promote/gated-adopt skeleton | Health metrics, device IDs, tax rules |
| **Domain plugin (e.g. PHA)** | Catalog, T0 facts, CHB, regression banks | Re-implementing plan-before-compose |

## Online modules (this package)

| Module | Purpose |
|--------|---------|
| `turn_plan` | `TurnPlan` Protocol + `TurnPlanData` |
| `turn_fsm` | `CoreTurnPhase` + `PhaseRecorder` + plan-before-compose |
| `integrity` | `IntegrityResult` |
| `plan_vs_actual` | Portable diff codes |

**Not included here:** Tier0 assemblers, health/tax plugins, CompareTable, filing_table, Loop scripts.

## Offline Evolution (Official Loop Suite)

| Artifact | Status | Where |
|----------|--------|--------|
| Protocol: `loop_proposal/v2`, `promote_verdict/v1`, `failure_event/v1` | ✅ registered | [`docs/harness-core-protocol-v0.md`](../../docs/harness-core-protocol-v0.md) §11 |
| Suite package skeleton | 📋 placeholder | [`packages/harness_loop/`](../harness_loop/) |
| Reference plugin (PHA) | ✅ shipped | scripts `pha_loop_*`, `pha_t0_*`, `pha_reflection_*` |
| Human-in-the-loop SOP | ✅ | [`docs/loop-evolution-human-in-the-loop-sop.en.md`](../../docs/loop-evolution-human-in-the-loop-sop.en.md) |
| How other agents attach | ✅ | [`examples/loop_reference_pha.md`](../../examples/loop_reference_pha.md) |
| Eval set v1 thin slice | ✅ | [`docs/harness-eval-set-v1.md`](../../docs/harness-eval-set-v1.md) · [`evals/goldens/`](../../evals/goldens/) |

**Iron rules (suite + plugins):** no auto-merge · full-veto before catalog merge · `--confirm YES` before T0 write · Loop never edits Core assertion code or routing FSM.

## Docs

- Protocol: [`docs/harness-core-protocol-v0.md`](../../docs/harness-core-protocol-v0.md)
- Loop / Reflection architecture: [`docs/harness-loop-reflection-architecture.md`](../../docs/harness-loop-reflection-architecture.md)

```bash
# From PHA repo root
PYTHONPATH=packages/harness_core/src:. python -c "import harness_core; print(harness_core.__version__)"
PYTHONPATH=. python scripts/pha_harness_core_adapter_selfcheck.py
```
