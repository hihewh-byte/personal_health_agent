# Loop Engineering & Reflection — Architecture

> **Language / 语言**：English (this document) · [中文](harness-loop-reflection-architecture.zh.md)  
> **Version**: v1.0 · 2026-07-12  
> **Scope**: harness-core control plane + PHA product plugin + offline evolution loops  
> **Upstream**: [`harness-core-protocol-v0.md`](harness-core-protocol-v0.md) · [`rfc-stage4-offline-loop-engineering.md`](rfcs/rfc-stage4-offline-loop-engineering.md) · [`rfc-loop-reflection-auto-evolution.md`](rfcs/rfc-loop-reflection-auto-evolution.md) · [`rfc-stage4b-personalization-flywheel.md`](rfcs/rfc-stage4b-personalization-flywheel.md)

---

## 1. Design goals

Split “gets smarter with use” into two **auditable, reversible, bounded** evolution paths:

1. **Smarter for all users** (Loop A + Ring R): broaden recognition — catalog aliases, English templates, schema triggers.  
2. **Smarter for each user** (Loop B): thicken the user fact ledger (T0) + Chronic Health Brief (L1.5) — more personalized answers with refs.

**Never evolved**: Python routing state machines, harness profile topology, per-user routing weights, online LLM weight tuning.

---

## 2. Layered architecture

```text
┌─────────────────────────────────────────────────────────────────────┐
│  harness-core (thin control plane · packages/harness_core)           │
│  TurnPlan · CoreTurnPhase · PhaseRecorder · IntegrityResult          │
│  plan_precedes_compose · plan_vs_actual diff codes                   │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ Adapter (pha/harness_core_adapter.py)
┌───────────────────────────────▼─────────────────────────────────────┐
│  PHA Plugin (domain assets + audit)                                  │
│  CompareTable · health_intent_catalog · numerics_manifest · CHB      │
│  INIT → SESSION → PLAN → COMPOSE → POST_AUDIT → DONE                 │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ Telemetry / E2E JSONL (offline)
        ┌───────────────────────▼───────────────────────┐
        │  Ring R · Reflection Critic (read-only critique)   │
        │  failure taxonomy → code_review vs auto_promote    │
        └───────────────────────┬───────────────────────────┘
                                │
        ┌───────────────────────▼───────────────────────────┐
        │  Loop A · Global recognition (Harvest→Distill→1E→PR) │
        │  Evolve: catalog / EN templates / schema triggers    │
        └───────────────────────┬───────────────────────────┘
                                │
        ┌───────────────────────▼───────────────────────────┐
        │  Loop B · User value (Ingest → Compile CHB → Eval)    │
        │  Evolve: T0 Facts + USER_CONTEXT_BRIEF (no global route)│
        └───────────────────────┬───────────────────────────┘
                                │
                    Layer 2 immunity gates (auto veto)
              selfcheck · EN10 · Nightly 148/164 · Bank 164
```

---

## 3. Three loops

### 3.1 Ring R — Reflection (v0 shipped)

| Component | Path | Role |
|-----------|------|------|
| Failure taxonomy | `pha/loop_failure_taxonomy.py` | E2E check → signal; signal → allowed proposal layers |
| Reflection Critic | `scripts/pha_reflection_critic.py` | Aggregate failures → `reflection_{ts}.md` + proposal JSON |
| Pipeline entry | `scripts/pha_loop_run_from_e2e.sh` | One-shot Harvest → Critic → Distiller |

**Principle**: Critic is **deterministic by default** (rule engine). LLM assist is reserved for explanation only — **no** direct patch or routing edits.

### 3.2 Loop A — Global recognition (Stage 4-α, partial)

| Step | Script | Output |
|------|--------|--------|
| Harvest | `scripts/pha_telemetry_harvest.py` | `slow_round_candidates.jsonl` |
| Distill | `scripts/pha_loop_alias_distiller.py` | `pha.loop_proposal/v2` |
| 1E Veto | `pha/loop_keyword_conflicts.py` | Drop conflicting proposals |
| Adopt | Human PR | catalog / schema JSON only |

**New (R0/P4)**: `--e2e-jsonl` / `PHA_E2E_JSONL` ingests English 50×8 and daily stress JSONL.

### 3.3 Loop B — Personalization (Stage 4-β, skeleton)

| Step | Component | Notes |
|------|-----------|-------|
| L0 Ingest | 3H attachment → T0 proposal | `pha/t0_ingest_proposal.py` + `scripts/pha_t0_ingest_proposal.py` (**proposal-only**, no DB writes) |
| L1 Compile | `pha/chb_compiler.py` + `scripts/pha_chb_daily_recompile.py` | Recompile CHB when T0 hash is stale |
| L2 Inject | `USER_CONTEXT_BRIEF` Tier1 slot | Read-only on lifestyle/combined |
| L2 Eval | `scripts/pha_persona_personalization_battery.py` | Offline CHB fixture battery (not live E2E) |

**Online flag**: `PHA_USER_CONTEXT_BRIEF=1` (default on) reads compiled artifacts; **no** blocking compile inside a turn (cron offline refresh).

---

## 4. Daily usage data flow

```text
User chat (each turn)
  ├─ Episodic focus (in-session, shipped)
  ├─ Background note capture (supplements/symptoms, shipped)
  ├─ T0 ledger queries (labs/wearables, shipped)
  └─ Harness telemetry → JSONL

Daily cron (Loop B)
  └─ pha_chb_daily_recompile.py → reports/chb/{user}/brief_{hash}.json

Weekly / post-stress (Loop A + R)
  └─ pha_loop_run_from_e2e.sh
       → slow_round_candidates.jsonl
       → reflection + alias proposal
       → human PR → EN10 + 148/164 veto → merge
```

**User experience curve**:

| Depth | Behavior |
|-------|----------|
| First screenshot upload | CompareTable deterministic SSO + episodic anchor |
| Nth follow-up in session | Single-metric focus, no full-table re-dump (P2 hardened) |
| Lab/wearable import | T0 thickens; cron refreshes CHB |
| ~20th lifestyle question | `USER_CONTEXT_BRIEF` injects §Facts (with ref_id) |
| Fleet-wide colloquial evolution | Loop A alias PR (benefits all users) |

---

## 5. Test-driven auto-iteration loop

```text
Observe   stress/telemetry JSONL
    ↓
Critique  taxonomy (rlp_locale_leak / full_table_repeat / alias_miss …)
    ↓
Propose   pha.loop_proposal/v2 (Layer 1 assets only)
    ↓
Verify    EN subset + selfcheck + 148/164 nightly
    ↓
Adopt     human PR merge (no auto-merge to main)
    ↓
Measure   next Weekly EN50 pass rate / persona battery delta
```

**Automation boundaries**:

- ✅ Automated: collect, classify, propose, veto, delta reports  
- ❌ Automated: merge main, edit Python state machines, per-user routes, fake DB for pass-rate gaming

---

## 6. Comparison with alternatives

| Dimension | **PHA + harness-core Loop** | OpenAI Evals / generic eval | LangSmith / Langfuse | Pure RAG memory | Self-editing prompt/weights |
|-----------|----------------------------|------------------------------|----------------------|-----------------|------------------------------|
| **What evolves** | Layer 1 JSON + T0 facts | datasets + prompt versions | trace analysis | document chunks | prompts / weights |
| **Control plane** | frozen Plan→Compose→Audit | no built-in harness | no built-in harness | none | easily drifts |
| **Numeric sovereignty** | numerics_manifest + CompareTable SSO | eval assertions | manual review | hallucination-prone | hallucination-prone |
| **Personalization** | T0 + CHB §Facts (ref_id) | weak | weak | medium (no provenance) | medium (not auditable) |
| **Failure attribution** | taxonomy + proposal whitelist | pass/fail | manual traces | none | none |
| **Safety gates** | 1E + 148/164 + no auto-merge | CI gate | none | none | high risk |
| **Cross-product reuse** | harness-core skeleton + domain plugin | generic | generic | generic | generic |

### 6.1 Unique value

1. **Harness-first evolution**: evolve recognition assets and user facts while **evidence freeze + post-audit** stay fixed.  
2. **Proposal layer whitelist**: taxonomy separates “catalog alias OK” from “code review required” (e.g. warehouse LLM locale leaks).  
3. **Dual-loop decoupling**: Loop A (global) vs Loop B (user) — no per-user pollution of 148/164 baselines.  
4. **Deterministic SSO vs LLM**: CompareTable / skip_llm own numbers; LLM is advisory only; Loop never crosses that line.  
5. **Vendored harness-core**: public clones run Core adapter selfchecks; tax/HIO reuse loop skeleton with their own catalogs.

### 6.2 Extensibility (“playfulness”)

| Play | How |
|------|-----|
| **Swap domain plugin** | Keep Core phase order; replace catalog + CompareTable → tax filing_table / HIO runbook |
| **Custom failure taxonomy** | Extend `pha/loop_failure_taxonomy.py` + new E2E checks → new signals |
| **Weekly evolution game** | EN50 full run → reflection report → merge 1–2 aliases → watch pass rate climb |
| **Persona sandbox** | fixture DB + persona battery; no real-user JSONL in repo |
| **CHB interpretation experiments** | `PHA_CHB_COMPILER=1` for LLM §Interpretation (advisory only, not a numeric source) |
| **Loop one-liner** | `PHA_E2E_JSONL=... bash scripts/pha_loop_run_from_e2e.sh` |

---

## 7. Shipped status (2026-07-13)

| Capability | Status |
|------------|--------|
| harness-core v0 skeleton | ✅ `packages/harness_core` |
| Loop A Harvest/Distill/1E | ✅ |
| Harvest ← E2E JSONL | ✅ R0/P4 |
| Ring R Reflection Critic v0 | ✅ R1 |
| Loop one-shot pipeline | ✅ `pha_loop_run_from_e2e.sh` |
| CHB compile + stale detection | ✅ |
| CHB daily cron script | ✅ P3 |
| USER_CONTEXT_BRIEF injection | ✅ P1 (`PHA_USER_CONTEXT_BRIEF=1`) |
| R2 promote dry-run/veto | ✅ `scripts/pha_loop_promote_candidate.py` (no auto-merge) |
| R2 first human-reviewed alias | ✅ `steps←多少步` (`promote_verdict_20260713T045002Z` full-veto passed; catalog merge) |
| R3 EN10 Nightly opt-in | ✅ `PHA_NIGHTLY_EN10=1` in `nightly_harness_regression.sh` |
| 3H → T0 ingest proposals | ✅ P2 proposal-only (`pha_t0_ingest_proposal.py`) |
| T0 gated adopter | ✅ `scripts/pha_t0_gated_adopter.py` (`--apply --confirm`) |
| Loop B L2 CHB gap harvest | ✅ `pha_chb_gap_harvest.py` + compile merge |
| Persona battery (offline + live opt-in) | ✅ offline + `pha_persona_live_e2e_battery.py` |
| English warehouse CJK guard | ✅ orchestrator `apply_english_locale_leak_guard` |
| Nightly baseline 148+164 | ✅ seed=20260626 local green (`c8add1f`) |
| harness_trace UI / session MVCC | 📋 official ecosystem Phase 1 (see §10) |
| HIO-A third-domain closure | 📋 Phase 3 |

---

## 8. Operator commands

```bash
# Loop pipeline (stress/telemetry → proposal)
PHA_E2E_JSONL=/tmp/pha-e2e-en-50x-post-p1/en_stress_50x_*.jsonl \
  bash scripts/pha_loop_run_from_e2e.sh

# CHB daily refresh (cron)
python3 scripts/pha_chb_daily_recompile.py

# Selfchecks
python3 scripts/pha_loop_failure_taxonomy_selfcheck.py
python3 scripts/pha_chb_compiler_selfcheck.py
python3 scripts/pha_t0_ingest_proposal_selfcheck.py
python3 scripts/pha_persona_personalization_battery.py

# R2 promote dry-run (does not apply patches)
python3 scripts/pha_loop_promote_candidate.py --proposal reports/loop/proposals/alias_proposal_*.json

# T0 gated adopt (writes DB; requires --confirm)
python3 scripts/pha_t0_gated_adopter.py --proposal reports/loop/t0_ingest_proposals/*.json --apply --confirm YES --recompile-chb

# CHB gap harvest (Loop B L2)
python3 scripts/pha_chb_gap_harvest.py --candidates reports/loop/slow_round_candidates.jsonl

# Persona live (requires running PHA)
python3 scripts/pha_persona_live_e2e_battery.py
```

---

## 10. Competitor learnings & official ecosystem (Core spine + ecosystem muscle)

**Principle**: `packages/harness_core` stays thin — contracts, phase FSM, integrity/trace **schemas** only. Runbook prose, work orders, and UI stay out of the kernel but ship as **official ecosystem** (`tools/` + plugin slots) in-repo.

| Source | Learn | Where | Phase |
|--------|-------|-------|-------|
| LangSmith / Langfuse | Assertion diff UX | `harness_turn_trace/v1` + static Trust Trace Viewer | Phase 1 |
| OpenAI Evals | Dataset spec + synthetic fuzz | `harness_eval_set/v1` + Loop A alias fuzzer | Phase 1–2 |
| RAG / GraphRAG | Soft entity linking (not routing) | CHB §SoftContext (T2 advisory) | Phase 2 |
| Datomic / MVCC | Evidence snapshots + revision chain | `turn_evidence_snapshot/v1` + T0 revision ledger | Phase 2–3 |

**PM vs “minimal safety shell” compromise**:

1. **Runbook ≠ catalog aliases**: Core adds **Flow-based Evidence Slot** contracts; plugins compile runbook steps into Tier1 flow evidence; POST_AUDIT diffs planned vs claimed steps.  
2. **Loop B ≠ static CMDB**: evolve `chb_compiler` into a **dynamic artifact compiler** — quantitative device/lifecycle profile from dirty history, not raw ticket dumps.  
3. **Trace UI + session MVCC as official kit**: kernel emits `trace.json`; `tools/harness_trace_viewer` + **session turn snapshots** (evidence rollback, not LLM replay) ship by default.

**Spine unchanged**: Plan-before-Compose · numerics ⊆ manifest/CompareTable · no Loop auto-merge · no routing/registry evolution.

---

## 9. Revision history

| Date | Notes |
|------|-------|
| 2026-07-12 | v1.0: R0/P4 Harvest+E2E, R1 Reflection v0, P1/P3 CHB daily loop, this doc |
| 2026-07-12 | v1.0.1: split into `.zh.md` / `.en.md`; removed LinkedIn appendix from architecture docs |
| 2026-07-12 | v1.0.3: T0 gated adopter, CHB L2 gap, persona live; §10 ecosystem roadmap |
| 2026-07-13 | v1.0.4: Nightly 148+164 baseline fixes; first human-reviewed alias `steps←多少步` full-veto passed and merged into catalog |
