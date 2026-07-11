# Issue #1 — Phase A closeout comment (paste into GitHub)

> Paste as a comment on https://github.com/hihewh-byte/personal_health_agent/issues/1  
> Keep engineering honesty; do not claim PyPI or a public tax domain.

---

## Phase A closeout (2026-07-10)

Thanks to everyone watching this thread. Short status update:

### What we completed

- **Dual-domain basement (local sandbox):** PHA (public) and a second **tax/filing** domain (local-only) both run the same control-plane philosophy: Plan → Tier0 → post-audit, with no-LLM golden runs.
- **Protocol v0:** [`docs/harness-core-protocol-v0.md`](https://github.com/hihewh-byte/personal_health_agent/blob/main/docs/harness-core-protocol-v0.md) freezes the thin spine (`INIT → SESSION → PLAN → COMPOSE → POST_AUDIT → DONE`) and Core ← Adapter ← Plugin layering.
- **Blueprint checklist:** [`docs/harness-core-evolution-blueprint.md`](https://github.com/hihewh-byte/personal_health_agent/blob/main/docs/harness-core-evolution-blueprint.md) — tax P0/P1 gaps marked done **in the local twin**; public repo documents the map without shipping tax sources.
- **Thin PHA adapter + vendored Core:** `pha/harness_core_adapter.py` + in-repo [`packages/harness_core/`](https://github.com/hihewh-byte/personal_health_agent/tree/main/packages/harness_core). Public golden run should print `PASS harness_core adapter` with Core spine phases.

### Honest boundaries (please read)

| Claim | Reality |
|-------|---------|
| “Framework complete” as **philosophy + dual-domain proof** | ✅ Local sandbox (PHA public + tax local) |
| `harness_core` **source in this GitHub repo** | ✅ Vendored under `packages/harness_core/` |
| `harness_core` on **PyPI** | ❌ Not published as a standalone package |
| Second domain (**tax**) on GitHub | ❌ **Never** — PII / financial privacy; local isolation is P0 |
| Public clone sees Core FSM via adapter | ✅ Golden run should print `PASS harness_core adapter` |
| PHA as a **usable local health app** from this repo | ✅ Clone → deps → UI / 30s golden |

### What we are *not* doing next by default

- No mock public tax specimen and **no** publishing of the real tax agent.
- Dual-domain proof for Core stays: **protocol docs + vendored Core + PHA adapter/golden**; tax remains a private twin.
- No ASI rewrite / clinical multi-tenant Gateway in this phase.
- No PyPI until there is real external demand (Stars / concrete Issues on portable modules).

### Still useful feedback

If you ran `scripts/pha_harness_golden_run.py`, comment with: which modules feel portable, and what blocked reuse. That still decides whether a published `agent-harness-core` is worth it.

Phase A exploration is **closed** on our side. Further Core packaging is demand-driven.
