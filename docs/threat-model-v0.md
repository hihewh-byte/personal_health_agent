# Threat Model v0 — Harness Core + Loop

> Scope: the harness control plane (online `harness_core` + offline Harness Loop) as vendored in this repo.
> Non-scope: PHA application security (web UI, storage encryption, macOS packaging) — tracked separately.
> Status: v0 (audit plan P1-4). One page by design; expand only when a real integration demands it.

---

## 1. Trust boundaries

```text
                 ┌──────────────────────────────────────────────┐
   user turn ───▶│  ONLINE — user's agent + Domain Adapter       │
                 │  LLM output = UNTRUSTED input                 │
                 │  harness_core: Plan → Compose → Post-Audit    │
                 │  fail-closed; no runtime self-healing         │
                 └───────────────┬──────────────────────────────┘
                                 │ failure events (JSONL, append-only)
                                 ▼
                 ┌──────────────────────────────────────────────┐
   offline ─────▶│  OFFLINE — Harness Loop (harvest → distill    │
   (cron/manual) │  → 1E gates → static veto → proposal)         │
                 │  proposal-only; never writes catalogs         │
                 └───────────────┬──────────────────────────────┘
                                 │ loop_proposal / promote_verdict (JSON)
                                 ▼
                 ┌──────────────────────────────────────────────┐
                 │  HUMAN — PR review + CI gates + merge         │
                 │  the only write path into main / catalogs     │
                 └──────────────────────────────────────────────┘
```

Three trust levels, strictly ordered:

| Zone | Trusts | Never trusts |
|------|--------|--------------|
| Online Core | its own frozen plan (allowlist, row keys, FSM) | LLM prose, OCR text, user attachments |
| Offline Loop | filesystem inputs it is pointed at (see §3) | candidate phrases, harvested messages |
| Human PR | CI-green diffs it has reviewed | any auto-generated patch, however green |

**Design invariant:** data only moves *down* the trust gradient via narrow artifacts
(failure JSONL → proposal JSON → PR diff). Nothing offline can reach back into a live turn.

## 2. Online attack surface (harness_core)

**Threat O1 — number/ID swap in composition.** The LLM substitutes or invents a metric value,
date, or row key not present in injected evidence.
*Defense:* post-audit membership check — every numeric atom in the reply must belong to the value/date
sets frozen at plan time (in the PHA reference implementation: the numerics manifest). Violations become
machine diff codes (`compute_plan_vs_actual` frame) and the reply is blocked or downgraded.
Fail-closed: no "ask the model to fix it" retry loop.
*Extraction note:* the diff-code frame is portable (`harness_core.plan_vs_actual`); the value-membership
audit itself still lives in the PHA reference implementation — its contract shape is part of P1.5-1.

**Threat O2 — phase confusion.** A caller invokes Compose before Plan, or double-audits.
*Defense:* turn FSM (`validate_phase_transition`, `plan_precedes_compose`); violations are hard errors, not warnings.

**Threat O3 — adapter smuggling.** A buggy/hostile Domain Adapter widens the allowlist after planning.
*Defense (partial):* `plan_vs_actual` diff codes surface drift; the plan is frozen data (`TurnPlanData`).
*Residual risk:* the adapter is inside the trust boundary — a malicious adapter can lie in both plan and actual.
Core defends against a *confused* adapter, not a *hostile* one. Deployers own adapter code review.

## 3. Offline attack surface (Harness Loop)

Primary threat: **recognition poisoning** — attacker-influenced text (chat messages, OCR chrome,
crafted E2E JSONL) becoming a catalog alias, so future turns misroute.

**Threat L1 — malicious/garbage JSONL fed to `harvest --e2e-jsonl`.**
Harvest is deliberately dumb: it only extracts `passed:false` rows into candidates; it writes no catalogs.
Poisoned rows become *candidates*, nothing more.

**Threat L2 — junk promotion through distill.** Three ordered defenses before anything reaches a PR:

1. **1E gates** (a: time/aggregation/affective denylist · b: substring inheritance · c: narrow-domain
   pollution probes · d: OCR/UI chrome words like "Query"/"Cancel"). Domain word lists live in the
   domain plugin; the gate frame (`harness_loop.gates`) is ordered and first-failure-decides.
2. **Static veto** (`promote --static-only`): rejects proposals with `code_review_items`, patch ops
   outside `/metric_aliases/`, or Tier-C slots promoted to catalog. Never applies patches.
3. **Human PR + CI**: the only write path. Regression goldens (`harness.eval_set/v1`, incl. alias-fuzz)
   must stay green; consensus gates force changelog updates.

**Threat L3 — gated adopt bypass (Loop B / T0 per-user facts).**
`harness-loop adopt` refuses without a literal `--confirm YES`; it delegates to the T0 gated adopter,
which is the only Loop path that writes user-visible facts. No cron should ever pass `--confirm YES`.

**Threat L4 — proposal artifact tampering** (editing a `loop_proposal` JSON after distill, before promote).
*Defense:* static veto re-validates shape and patch paths at promote time; human diff review sees the
final artifact. *Residual risk:* no cryptographic signing of artifacts — acceptable at current scale
(single maintainer); revisit if proposals ever cross a machine/trust boundary.

## 4. Explicit non-goals (v0)

- **No runtime input filtering / jailbreak detection.** Core audits *outputs* against a frozen plan;
  it is not a semantic guardrail (see Guardrails/NeMo comparisons in the docs). Deployers wanting
  input-side filtering should compose an external tool in front.
- **No multi-tenant isolation.** Single-user local-first deployment assumed; multitenancy is an RFC.
- **No artifact signing / supply-chain attestation** (see L4 residual).
- **No protection against a hostile Domain Adapter or hostile local user** — both are inside the
  trust boundary of a local-first install.

## 5. Operator checklist

- Never run `adopt --confirm YES` from automation.
- Treat any `promote` verdict with a non-empty `static_veto` as a hard stop, not a warning.
- Keep `reports/loop/` (harvest/proposal artifacts) out of git — it may embed user text (already gitignored).
- When attaching a new domain: your junk-word lists (1E-d equivalent) are *your* responsibility;
  the portable gate frame ships empty.

---

### Revision history

| Date | Change |
|------|--------|
| 2026-07-15 | v0 — initial threat model (audit plan P1-4) |
