# Harness Core Evolution Blueprint — PHA ↔ tax_agent

> **Status**: Phase A working doc (2026-07-09) · **No code extraction yet**  
> **Repos**: [harness-builder-overview.md](harness-builder-overview.md) · [harness-consensus-opus48-2026-06-08.md](harness-consensus-opus48-2026-06-08.md)  
> **Second domain**: `../tax_agent/` (sibling repo under `myAgents/`)

---

## 0. Purpose

Define the **minimum “framework complete”** bar before any `agent-harness-core` package:

1. Two real domains (health + tax) share the **same control-plane philosophy**
2. Both can demonstrate Plan → Tier0 → Audit **without an LLM**
3. A written map of what belongs in **core** vs **domain plugin**

This document is the Phase A deliverable. It does **not** authorize PyPI extraction.

---

## 1. Control-plane isomorphism

```text
User message
    → Turn plan (profile / slots / forbidden / tools)
    → Tier0 assembly (protected budget)
    → (optional) LLM compose
    → Numerics / citation audit
    → Build report (+ warnings)
```

| Layer | PHA | tax_agent | Shared idea? |
|-------|-----|-----------|--------------|
| Turn plan | `TurnEvidencePlan` · `pha/harness_plan.py` | `FilingTurnPlan` · `tax_agent/harness_plan.py` | ✅ same shape |
| Intent → profile | `health_intent_catalog` + resolver | `tax_intent_catalog.yaml` + router | ✅ declarative catalog |
| Tier0 budget | `harness_tier0_assembly.py` (~474 LOC) | `harness_tier0_assembly.py` (~98 LOC) | ✅ protected SLA |
| Session ledger | Patient State | `FilingSessionState` | ✅ domain state blob |
| Numerics audit | `numerics_manifest.py` | `numerics_audit.py` | ✅ whitelist ⊆ evidence |
| Domain-extra audit | CompareTable (wearable) | `citation_audit` (policy) | ⚠️ both “post-gates”, different ops |
| Build report | `harness_report` v1.2 rich | `tax.harness_report/v2` slim | ⚠️ same intent, tax thinner |
| Turn FSM | `chat_turn_fsm.py` | `tax_agent/chat_turn_fsm.py` + wired in `chat_turn_service` | ✅ Phase A P1 |
| plan_vs_actual | `compute_plan_vs_actual()` | `planVsActual` on `tax.harness_report/v2` | ✅ |
| Profile registry CI | `harness_profile_registry.py` | `tax_agent/harness_profile_registry.py` | ✅ Phase A P1 |
| No-LLM golden run | `scripts/pha_harness_golden_run.py` | `scripts/run_tax_harness_golden_run.py` | ✅ Phase A |
| Code import | — | only `pha.llm_provider` / ollama bridge | ❌ harness is twin, not library |

**Reuse score today**: philosophy **~8/10** · shared harness code **~2/10**.

---

## 2. Field-level plan comparison

| Field | PHA `TurnEvidencePlan` | tax `FilingTurnPlan` | Core candidate? |
|-------|------------------------|----------------------|-----------------|
| `profile` | ✅ | ✅ | **Yes** |
| `slots_tier0` / `slots_tier1` | ✅ | ✅ | **Yes** |
| `forbidden` | ✅ | ✅ | **Yes** |
| `tools_allowed` | ✅ | ✅ | **Yes** |
| `task_text` | ✅ | ✅ | **Yes** (string; content is domain) |
| `legacy_question_type` | PHA-only | — | No (PHA plugin) |
| `tax_year` / `journey_phase` / `focus` | — | tax-only | No (tax plugin) |
| `fast_lane` | via runtime | ✅ on plan | **Yes** (optional flag) |
| `preserve_raw_user` | — | ✅ | **Yes** (optional) |

---

## 3. What should enter future Core vs stay plugin

### Core (domain-agnostic)

| Module idea | Rationale |
|-------------|-----------|
| `TurnPlan` protocol / dataclass | Frozen evidence boundary before LLM |
| Tier0 assembler + protected SLA | Budget without dropping critical slots |
| `BuildReport` minimal schema + `plan_vs_actual` | Observability / regression |
| Turn phase guard (plan before compose) | Enforceable invariant |
| Numerics audit **interface** | `allowed_values` + scan reply + fail → weak lane |
| Sub-agent / tool allowlist veto | Optional but portable |

### Domain plugin (must NOT enter Core)

| Domain | Keep in plugin |
|--------|----------------|
| **PHA** | Wearable CompareTable, LDL authority, health intent catalog, patient_state SQL, attachment lanes |
| **tax** | filing_table, FX provenance, classified income, policy citation KB, journey_phase |
| **Enterprise toB (PHA RFC)** | Gateway JWT, RBAC, `tenant:patient` user_id, device ingest adapters — **outside** harness core |

### Explicit non-goals for Core

- Multi-tenant RBAC / care_relationships  
- Device MQTT/BLE transport parsers  
- CRM / ERP connectors  
- “Doctor multi-patient UI”

Those belong to **Gateway / Ingest** layers (see §5). Putting them in Core would create the “四不像” Gemini correctly warned about.

---

## 4. tax gaps vs PHA (construction backlog)

| Gap | Priority | Notes |
|-----|----------|-------|
| Structured `plan_vs_actual[]` (or equivalent machine-diff) | **P0** | ✅ `planVsActual` on `tax.harness_report/v2` (2026-07-09) |
| No-LLM golden run with human-readable card | **P0** | ✅ `tax_agent/scripts/run_tax_harness_golden_run.py` |
| Align `docs/tax-harness-build-report-schema.md` to **v2** | **P0** | ✅ local tax_agent docs (not published) |
| Turn FSM / phase telemetry | **P1** | ✅ `chat_turn_fsm.py` + `resolve_chat_turn` phases (2026-07-09) |
| Profile registry generate + CI check | **P1** | ✅ `harness_profile_registry.py` + selfcheck `--generate/--check` |
| Richer tier0_integrity slot rows in report | **P1** | ✅ `tier0Integrity` + tax compliance `assertions[]` |
| English dry-run cases in golden run | **P2** | Builder onboarding |
| Extract shared package | **P2+** | Only after adapters proven |

---

## 5. PHA “toB” in design docs (not harness-core)

Personal OSS (`v0.4.0-beta.1`) is **single-user local**. Industry / clinical toB is **Future Work, DOC-only**:

| RFC | Intent | Relation to Harness |
|-----|--------|---------------------|
| [`rfcs/rfc-device-ingestion-adapter.md`](rfcs/rfc-device-ingestion-adapter.md) | Any wearable/IoT → L1 daily rows; dual-layer `source_vendor` | **Ingest L0**; CompareTable/FSM **unchanged** |
| [`rfcs/rfc-enterprise-multi-tenant.md`](rfcs/rfc-enterprise-multi-tenant.md) | Hospital → doctor → many patients; Gateway RBAC; `effective_user_id = tenant:patient` | **HTTP Gateway**; Core still sees one `user_id` |

Wave 4a explicitly **excludes** multi-tenant SaaS and vendor device integrations from the open-source personal edition ([`wave4a-open-source-readiness-spec.md`](wave4a-open-source-readiness-spec.md) §1).

**Implication for roadmap**: PHA industry toB is a **product/platform** track (Gateway + Device Adapter). It should **consume** a stable harness, not redefine it. Phase A (PHA↔tax alignment) remains the right basement before coding those RFCs.

---

## 6. ASI fitness (sales intelligence)

ASI (`agentic_sales_intelligence`) is a **pipeline / evidence-tier / delivery** system. It does **not** currently implement PHA’s Plan → Tier0 → Numerics hard gate.

| Question | Verdict |
|----------|---------|
| Should ASI be rewritten onto PHA harness wholesale? | **No** — wrong shape (multi-module M1/M3/M5, cloud/local mix) |
| Can ASI benefit from harness philosophy on a **narrow slice**? | **Yes** — e.g. finance metrics / quote numbers / training scorecard where invented digits are unacceptable |
| Is ASI the same as PHA enterprise toB RFCs? | **No** — ASI = sales intel product; PHA toB RFCs = clinical multi-patient + device ingest |

Recommended Phase B (later): pick **one** ASI numeric-honesty slice; do **not** “port ASI to PHA framework” as a big-bang.

---

## 7. Phase A exit criteria

- [x] This blueprint exists  
- [x] `tax_agent` no-LLM golden run script exists and prints PASS  
- [x] tax `planVsActual` structured field + schema doc v2 (local tax_agent only; **not** published to GitHub)  
- [x] No core package extraction; PHA `main` 5-minute path untouched  
- [x] **Policy**: do not upload tax_agent personal data or tax repo contents to public remotes without explicit necessity review

---

## 8. Next after Phase A

1. Close tax P0 gaps (`plan_vs_actual`, schema doc)  
2. Narrow toB: either ASI numeric slice **or** start Device/Gateway spike **only** as DOC→thin prototype — not Core  
3. Extract `harness-core` only when two adapters (PHA + tax) can call the same interface without twins
