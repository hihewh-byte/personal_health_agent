# PHA Harness — builder overview (OSS)

> Status: descriptive overview for external readers · not a standalone SDK yet  
> Baseline: [harness-consensus-opus48-2026-06-08.md](harness-consensus-opus48-2026-06-08.md)

## What it is

PHA Harness is the **control plane** around a local LLM:

- The harness **plans** which evidence is allowed this turn (`TurnEvidencePlan`)
- The LLM **composes** prose from injected Tier0/Tier1 blocks
- A **C-layer audit** checks that user-visible numbers match the evidence (or downgrades the answer)

This is the opposite of “LLM-first tool loops” used by coding agents. Health data is an **unverifiable personal domain** — inventing an LDL or HRV is worse than refusing.

```text
message → plan (profile / slots / forbidden / tools)
        → assemble Tier0 under budget (protected slots)
        → LLM compose
        → numerics / compare-table audit
        → SSE reply + HarnessBuildReport
```

## Why it might matter to other agent builders

| Idea | Value |
|------|--------|
| Plan-before-LLM | Freezes the evidence boundary before generation |
| Tier0 protected budget | Critical facts cannot be truncated away by long context |
| Numerics / Compare audit | Machine-checkable honesty for personal numbers |
| plan_vs_actual report | Diff what was planned vs what was actually injected |
| Profile registry + CI | Live introspection prevents config drift |

## What it is *not* (today)

- Not a `pip install agent-harness` package
- Not domain-agnostic — slots and audits are health/wearable-specific
- Not a multi-agent swarm framework

Reusable **patterns** live under `pha/harness_*.py`, `pha/numerics_manifest.py`, `pha/chat_turn_fsm.py`. Extracting a core package is a Phase-2 engineering track, not part of `v0.4.0-beta.1`.

Dual-domain map (PHA ↔ tax_agent): [harness-core-evolution-blueprint.md](harness-core-evolution-blueprint.md).

## Key entry points

| Concern | Module |
|---------|--------|
| Turn plan | `pha/harness_plan.py` |
| Tier0 assembly | `pha/harness_tier0_assembly.py` |
| Build report | `pha/harness_report.py` |
| Numerics audit | `pha/numerics_manifest.py` |
| Wearable compare audit | `pha/wearable_compare_table_v1.py` |
| Turn FSM | `pha/chat_turn_fsm.py` |
| Orchestrator | `pha/chat_turn_orchestrator.py` |

Offline dry-run (no LLM) — ~1s after deps installed:

```bash
PYTHONPATH=. python scripts/pha_harness_golden_run.py
# → RESULT: PASS — harness planned and assembled evidence without calling an LLM.
```

## Call for feedback

If you clone PHA to study the harness:

1. Run `bash scripts/run_selfchecks.sh`
2. Skim this file + the consensus baseline
3. [Open an Issue](https://github.com/hihewh-byte/personal_health_agent/issues) with: what you tried to reuse, what blocked you, which module felt most portable

That feedback decides whether a future `agent-harness-core` extraction is worth the cost.
