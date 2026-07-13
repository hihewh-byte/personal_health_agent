# Harness Core Protocol v0 — Interface Design (Week 2)

> **Status**: Phase A complete · Core vendored in-repo (2026-07-10) · **No PyPI yet**  
> **Parent**: [harness-core-evolution-blueprint.md](harness-core-evolution-blueprint.md)  
> **In-repo package**: [`packages/harness_core/`](../packages/harness_core/)  
> **Out of scope**: ASI, clinical multi-tenant Gateway, publishing tax_agent

---

## 0. Goal

Define the **thinnest domain-agnostic control plane** that both PHA and tax already implement as twins:

```text
Plan (freeze evidence boundary)
  → (optional) Compose / Fast-lane
  → Post-Audit (integrity + plan_vs_actual)
```

**Framework-complete (fact) when**:

1. This protocol is written and frozen as v0  
2. A local `harness_core` package exposes only Protocol / dataclass / FSM guards  
3. Week 3: PHA + tax each have a thin Adapter; both no-LLM golden runs stay green  

v0 does **not** require deleting `pha/harness_*.py` or `tax_agent/harness_*.py`.

---

## 1. Layering

```text
┌─────────────────────────────────────────────────────────┐
│  Product family                                          │
│  harness-core (thin online)                              │
│  TurnPlan · CoreTurnPhase · PhaseRecorder               │
│  IntegrityResult · plan_vs_actual · (optional) Numerics │
│                                                          │
│  Official Loop Suite (offline — not vendored in Core)    │
│  proposal / verdict / failure_event contracts (§11)      │
│  → packages/harness_loop (skeleton) + domain plugins     │
└───────────────────────────┬─────────────────────────────┘
                            │ Adapter
           ┌────────────────┼────────────────┐
           ▼                                 ▼
   PHA plugin (reference)             tax / HIO / …
   CompareTable, catalog,             domain tables,
   T0 + CHB, loop scripts …           domain Loop Adapter …
```

| Layer | Owns | Must not own |
|-------|------|--------------|
| **Core** | Plan shape, phase order invariant, integrity codes, plan↔runtime diff, **evolution protocol registration** | Slot names, domain audits, catalogs, SQL, FX, Harvest/Distill **implementation** |
| **Official Loop Suite** | Offline orchestration skeleton, veto gates, promote CLI (Stage B) | Domain catalogs, T0 schemas |
| **Adapter** | Map domain plan ↔ `TurnPlan`; map domain phases ↔ core ranks | Business rules |
| **Plugin** | Everything domain-specific (PHA = reference Loop plugin) | Re-implementing plan-before-compose |

---

## 2. Core modules (v0 surface)

| Module | Responsibility | PHA twin today | tax twin today |
|--------|----------------|----------------|----------------|
| `turn_plan` | Frozen pre-LLM contract | `TurnEvidencePlan` | `FilingTurnPlan` |
| `turn_fsm` | Phase recorder + plan-before-compose | `ChatTurnPhase` | `TaxTurnPhase` |
| `integrity` | Tier0 integrity result shape + diff codes | `tier0_integrity` dict | `tier0Integrity` + assertions |
| `plan_vs_actual` | Machine-diff plan vs runtime | `compute_plan_vs_actual` | same name on tax report |
| `numerics` (optional v0.1) | Protocol only: `allowed_values` + scan | `numerics_manifest` | `numerics_audit` |

**Explicitly deferred out of Core v0**:

- Full Tier0 assembler (budgets + protected SLA stay in plugins; Core only types the integrity **result**)  
- Profile registry CI (plugins keep generate/check; Core may later add a generic “contract snapshot” helper)  
- Build-report JSONL writers (domain schemas differ)

---

## 3. `TurnPlan` — universal fields

### 3.1 Required (both domains)

| Field | Type | Meaning |
|-------|------|---------|
| `profile` | `str` | Routing / assembly key |
| `slots_tier0` | `Sequence[str]` | Must-try evidence slots |
| `slots_tier1` | `Sequence[str]` | Soft / overflow slots |
| `forbidden` | `Sequence[str]` | Hard veto codes (tools or behaviors) |
| `tools_allowed` | `Sequence[str]` | Tool allowlist |
| `task_text` | `str` | Operator instruction (domain language OK) |

### 3.2 Optional (Core-aware, domain may set)

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `fast_lane` | `bool` | `False` | Compose may be skipped for deterministic reply |
| `preserve_raw_user` | `bool` | `True` | Do not rewrite user utterance in plan |

### 3.3 Plugin-only (never on Core dataclass)

| Field | Owner |
|-------|--------|
| `legacy_question_type` | PHA |
| `tax_year`, `journey_phase`, `focus`, `inject_insight`, `intent_score` | tax |

Adapters expose these via `domain_meta: Mapping[str, Any]` if Core telemetry needs a bag — **not** as first-class Core fields.

### 3.4 Protocol sketch

```python
class TurnPlan(Protocol):
    @property
    def profile(self) -> str: ...
    @property
    def slots_tier0(self) -> Sequence[str]: ...
    @property
    def slots_tier1(self) -> Sequence[str]: ...
    @property
    def forbidden(self) -> Sequence[str]: ...
    @property
    def tools_allowed(self) -> Sequence[str]: ...
    @property
    def task_text(self) -> str: ...
```

Frozen dataclass `TurnPlanData` implements the same shape for dry-runs and adapters.

---

## 4. FSM — core phases vs domain phases

### 4.1 Design choice: **ranked core spine + domain aliases**

Domains keep rich phase names (PHA has `SLOT_ASSEMBLY`; tax has `SCOPE` / `FAST_LANE`).  
Core only enforces a **spine** and the hard invariant.

**Core spine (ordered):**

| CoreTurnPhase | Meaning |
|---------------|---------|
| `INIT` | Turn starts |
| `SESSION` | Session / prefs loaded |
| `PLAN` | Evidence boundary frozen (`TurnPlan` exists) |
| `COMPOSE` | LLM or rules produce user-visible reply |
| `POST_AUDIT` | Integrity / numerics / plan_vs_actual |
| `DONE` | Success terminal |
| `ERROR` | Failure terminal |

**Invariant (iron):** any path that enters `COMPOSE` (or domain alias classified as compose) **must** have entered `PLAN` earlier. Early exits (`CLARIFY` → `DONE`) need not plan.

### 4.2 Domain phase → core rank (Adapter table)

| Core | PHA examples | tax examples |
|------|--------------|--------------|
| INIT | `init` | `init` |
| SESSION | `session`, `perception`, … | `session`, `scope` |
| PLAN | `plan`, `slot_assembly`, `tier0_assemble`, `plan_pre_llm`, `skip_llm_eval` | `plan` |
| COMPOSE | `compose` | `compose`, `fast_lane` |
| POST_AUDIT | `post_audit` | `post_audit` |
| DONE / ERROR | same | same |

Core `PhaseRecorder` stores **core** phases (or `(core, domain_alias)` pairs). Plugins may keep full domain telemetry in parallel.

### 4.3 Env kill-switch

| Domain today | Core v0 |
|--------------|---------|
| `PHA_CHAT_TURN_FSM` | Adapter maps to `HARNESS_TURN_FSM` **or** keeps domain env |
| `TAX_CHAT_TURN_FSM` | same |

Week 2 skeleton uses `HARNESS_TURN_FSM` only inside `harness_core`; adapters decide bridging later.

---

## 5. Integrity + `plan_vs_actual`

### 5.1 `IntegrityResult` (minimal)

```text
budget_limit: int
used_chars: int
slots: list[{slot_id, present, protected?, level?, chars?, materialized?}]
errors: list[str]      # hard codes
warnings: list[str]    # soft codes
assertions: list[str]  # optional compliance labels (tax-style)
```

Core does **not** know what `FILING_TABLE_AUTHORITY` means — only that codes are strings.

### 5.2 `plan_vs_actual` codes (portable patterns)

| Pattern | Example | Meaning |
|---------|---------|---------|
| `tool_not_allowed:{name}` | `tool_not_allowed:invent_fx` | Executed tool ∉ allowlist |
| `missing_tier0_slot:{id}` | `missing_tier0_slot:NUMERICS_MANIFEST` | Planned slot empty when tracked |
| `tier0_not_materialized:{id}` | … | Slot content not in ledger text |
| `protected_slot_empty:{id}` | … | Protected slot missing |
| domain codes | `assert:no_llm_compute` | Plugin-specific; Core treats as opaque |

Function signature:

```python
def compute_plan_vs_actual(
    plan: TurnPlan,
    *,
    tools_executed: Sequence[str] = (),
    slot_contents: Mapping[str, str] | None = None,
    tool_error: str | None = None,
    integrity: IntegrityResult | Mapping[str, Any] | None = None,
) -> list[str]:
    ...
```

---

## 6. Numerics audit (Protocol only in v0)

```python
class NumericsAuditor(Protocol):
    def allowed_values(self) -> Sequence[str]: ...
    def audit_reply(self, reply: str) -> Mapping[str, Any]:
        """Return at least {ok: bool, warnings: list[str]}."""
```

Implementations stay in PHA / tax. Core may later ship a trivial “substring allowlist” helper — **not** required for Week 2 Done.

---

## 7. Field mapping cheat-sheet (Adapter prep)

| Core `TurnPlan` | PHA `TurnEvidencePlan` | tax `FilingTurnPlan` |
|-----------------|------------------------|----------------------|
| `profile` | `profile` | `profile` |
| `slots_tier0` | `slots_tier0` | `slots_tier0` |
| `slots_tier1` | `slots_tier1` | `slots_tier1` |
| `forbidden` | `forbidden` | `forbidden` |
| `tools_allowed` | `tools_allowed` | `tools_allowed` |
| `task_text` | `task_text` | `task_text` |
| `fast_lane` | (runtime) | `fast_lane` |
| `preserve_raw_user` | `preserve_raw_user` | `preserve_raw_user` |
| — | `legacy_question_type` → `domain_meta` | `tax_year`, `journey_phase`, … → `domain_meta` |

---

## 8. Package layout

**Public (this repo):**

```text
personal_health_agent/packages/harness_core/
  README.md
  pyproject.toml
  src/harness_core/
    turn_plan.py · turn_fsm.py · integrity.py · plan_vs_actual.py
  tests/
```

**Local twin (not published):** `myAgents/harness_core/` may still exist as a working copy; PHA prefers the vendored tree above.

**Week 2 Done criteria (this doc + skeleton):**

- [x] Protocol doc in PHA `docs/harness-core-protocol-v0.md`  
- [x] Local `myAgents/harness_core/` skeleton (TurnPlan / FSM / Integrity / plan_vs_actual)  
- [x] Unit tests for FSM + plan_vs_actual  
- [x] Protocol doc on public `main` (`77cde06`)  
- [x] Both domain golden runs green **without** requiring Core for public PHA clone (soft skip)

**Week 3 Done criteria (adapter integration — 2026-07-10):**

- [x] `pha/harness_core_adapter.py` + `tax_agent/harness_core_adapter.py` (tax local-only)  
- [x] Golden runs assert adapter smoke  
- [x] Soft tax runtime telemetry: `corePhases` when Core present (local)  
- [x] **Vendored Core in public PHA:** `packages/harness_core/` (clone-and-run; not PyPI)  
- [ ] Optional later: domain FSM **delegates** `assert_plan_before_compose` to Core  
- [x] `pha_harness_golden_run` PASS with in-repo Core

---

## 9. Non-goals (repeat)

- Do not rewrite ASI onto this Core  
- Do not put Gateway / RBAC / device ingest in Core  
- Do not move CompareTable or filing_table into Core  
- Do not publish to PyPI until Week 3 adapters proven  
- Do not break PHA 5-minute UI path or tax 30s golden run while designing

---

## 10. Decision log

| Date | Decision |
|------|----------|
| 2026-07-10 | Skip ASI Phase B1; mainline = Core protocol isolation |
| 2026-07-10 | Core FSM = spine + adapter alias table (not union of all domain phases) |
| 2026-07-10 | Tier0 **assembler** stays plugin; Core owns integrity **result** + plan_vs_actual |
| 2026-07-10 | Local package path: `myAgents/harness_core/` (sibling), not inside tax_agent |
| 2026-07-13 | Offline evolution = **Official Loop Suite** (product family), not Core source tree; register proposal/verdict schemas in this protocol; PHA = reference plugin |

---

## 11. Offline Evolution contracts (Official Loop Suite)

> **Status:** schemas registered as **official control-plane I/O**.  
> **Implementation today:** PHA scripts (`pha_loop_*`, `pha_t0_*`, `pha_reflection_*`).  
> **Target home:** [`packages/harness_loop/`](../packages/harness_loop/) (skeleton README only as of 2026-07-13).  
> **Attach guide:** [`examples/loop_reference_pha.md`](../examples/loop_reference_pha.md).

Online Core stays fail-closed and does **not** self-heal mid-turn. Evolution is offline:

```text
Telemetry / E2E JSONL
  → Ring R Reflection Critic (read-only attribution)
  → Loop A proposal (global recognition, e.g. catalog aliases)
  → promote_verdict (static + regression veto)
  → human PR (no auto-merge)

  → Loop B T0 ingest proposal (per-user facts)
  → gated apply (--confirm) → domain brief recompile
```

### 11.1 `failure_event/v1` (shape guidance)

Minimum fields for suite harvest (JSONL object per event):

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `schema` | `str` | recommended | e.g. `harness.failure_event/v1` |
| `session_id` | `str` | yes | |
| `turn` | `int` | yes | |
| `check_id` / `error_code` | `str` | yes | Domain check or integrity code |
| `user_message` | `str` | yes | |
| `answer_head` | `str` | no | Truncated reply |
| `harness_profile` | `str` | no | |
| `signal` | `str` | no | Filled by taxonomy after harvest |

PHA E2E / harness JSONL lines are accepted as a **superset** of this shape.

### 11.2 `loop_proposal/v2` (alias / config propose)

Canonical `schema` string today: **`pha.loop_proposal/v2`**  
(rename to `harness.loop_proposal/v2` when suite extraction lands; both MUST be accepted during migration.)

| Field | Type | Meaning |
|-------|------|---------|
| `schema` | `str` | Must be `pha.loop_proposal/v2` |
| `generated_at` | `str` | ISO timestamp |
| `stage` | `str` | Pipeline stage id |
| `source` | `str` | Harvest / human_curated / … |
| `accepted_catalog` | `list[object]` | Tier-A catalog rows |
| `accepted_schema` | `list[object]` | Schema triggers (optional) |
| `slot_candidates` | `list[object]` | Must **not** promote Tier-C to catalog without human review |
| `rejected` | `list[object]` | Explicit rejects |
| `patch_ops` | `list[object]` | JSON-patch-like ops; paths restricted by static veto |
| `counts` | `object` | Summary counts |
| `suggested_regression` | `list[str]` | e.g. `EN07`, `EN08` |
| `notes` | `str` | Human / machine notes |

**Static veto (normative):**

- Reject if `schema` ≠ registered proposal schema  
- Reject if `code_review_items` present (needs human code review, not auto-promote)  
- Reject `patch_ops` whose `path` is outside the domain allowlist (PHA: `/metric_aliases/…` only)  
- Reject Tier-C `slot_candidates` promoted as catalog

Reference emitter: `scripts/pha_loop_alias_distiller.py` · curated fixture: `scripts/fixtures/loop_alias_proposal_curated.json`.

### 11.3 `promote_verdict/v1` (gate result)

Canonical `schema` string today: **`pha.loop_promote_verdict/v1`**

| Field | Type | Meaning |
|-------|------|---------|
| `schema` | `str` | `pha.loop_promote_verdict/v1` |
| `generated_at` | `str` | ISO timestamp |
| `proposal_path` | `str` | Input proposal |
| `proposal` | `object` | Summary counts / suggested_regression |
| `static_veto` | `list[str]` | Empty ⇒ static pass |
| `checks` | `list[object]` | Each: `cmd`, `exit_code`, `passed`, `timed_out`, `output_tail` |
| `passed` | `bool` | `all(checks.passed) and not static_veto` |
| `notes` | `str` | Must state dry-run / no auto-merge |

**Normative:** `passed: true` permits a **human PR**, never an automatic merge or T0 write.

Reference writer: `scripts/pha_loop_promote_candidate.py`.

### 11.4 `eval_set/v1` (regression goldens)

Canonical `schema` string: **`harness.eval_set/v1`**

Portable case list for offline + future live runners. Spec:
[`docs/harness-eval-set-v1.md`](harness-eval-set-v1.md).

| Field | Type | Meaning |
|-------|------|---------|
| `schema` | `str` | `harness.eval_set/v1` |
| `id` | `str` | Set id, e.g. `pha.smoke.v0` |
| `domain` | `str` | Plugin domain |
| `version` | `str` | Semver of the set |
| `cases` | `list[object]` | Each: `id`, `turns[]`, `expects[]`, optional `tags`/`locale`/`source` |

**Offline expects (normative for CI selfcheck):** `non_empty_turn_text`, `min_turns`,
`tag_required`, `catalog_alias`, `alias_must_reject`.
**Reserved:** `live_non_empty_answer`, `live_locale` (ignored offline).

Reference: `pha/harness_eval_set.py` · goldens `evals/goldens/pha_smoke_v0.json` ·
`pha_alias_fuzz_v0.json` · `scripts/pha_eval_set_selfcheck.py` ·
`scripts/pha_eval_set_alias_fuzz_selfcheck.py`.

### 11.5 Non-goals for §11

- Do not run Reflection inside the user-visible chat turn  
- Do not allow Loop suite patches to modify `harness_core` assertion modules  
- Do not require PyPI `harness-loop` until Stage B extraction is tested  
- Do not replace full PHA E2E banks with eval_set (eval_set is the exported subset)
