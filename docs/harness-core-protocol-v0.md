# Harness Core Protocol v0 — Interface Design (Week 2)

> **Status**: Design + local skeleton only (2026-07-10)  
> **Parent**: [harness-core-evolution-blueprint.md](harness-core-evolution-blueprint.md)  
> **Rule**: **Interfaces first, no big-bang move.** PHA / tax keep their twins until Week 3 adapters.  
> **Out of scope**: ASI, clinical multi-tenant Gateway, PyPI publish.

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
│  agent-harness-core (thin)                              │
│  TurnPlan · CoreTurnPhase · PhaseRecorder               │
│  IntegrityResult · plan_vs_actual · (optional) Numerics │
└───────────────────────────┬─────────────────────────────┘
                            │ Adapter (Week 3)
           ┌────────────────┼────────────────┐
           ▼                                 ▼
   PHA plugin                         tax plugin
   CompareTable, LDL,                 filing_table, FX,
   health catalog,                    journey_phase,
   patient_state …                    policy KB …
```

| Layer | Owns | Must not own |
|-------|------|--------------|
| **Core** | Plan shape, phase order invariant, integrity codes, plan↔runtime diff | Slot names, domain audits, catalogs, SQL, FX |
| **Adapter** | Map domain plan ↔ `TurnPlan`; map domain phases ↔ core ranks | Business rules |
| **Plugin** | Everything domain-specific | Re-implementing plan-before-compose |

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

## 8. Package layout (local skeleton)

Sibling under `myAgents/` (not inside tax; not published):

```text
myAgents/harness_core/
  README.md
  pyproject.toml          # name=harness-core, version=0.0.0a1
  src/harness_core/
    __init__.py
    turn_plan.py          # Protocol + TurnPlanData
    turn_fsm.py           # CoreTurnPhase + PhaseRecorder
    integrity.py          # IntegrityResult + helpers
    plan_vs_actual.py     # compute_plan_vs_actual
  tests/
    test_turn_fsm.py
    test_plan_vs_actual.py
```

**Week 2 Done criteria (this doc + skeleton):**

- [x] Protocol doc in PHA `docs/harness-core-protocol-v0.md`  
- [x] Local `myAgents/harness_core/` skeleton (TurnPlan / FSM / Integrity / plan_vs_actual)  
- [x] Unit tests for FSM + plan_vs_actual  
- [x] **No** change to PHA/tax runtime imports yet  
- [ ] Push protocol doc to public `main` when ready (Desktop / explicit ask)  
- [ ] Both domain golden runs remain green without depending on `harness_core` (smoke after any later adapter work)

**Week 3 Done criteria (later):**

- [ ] `pha.harness_core_adapter` / `tax_agent.harness_core_adapter` map plans + phases  
- [ ] Optional: domain FSM delegates `assert_plan_before_compose` to Core  
- [ ] `pha_harness_golden_run` + `run_tax_harness_golden_run` still PASS  

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
