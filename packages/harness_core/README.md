# harness-core (vendored in PHA)

Thin **domain-agnostic** control-plane interfaces used by PHA’s optional adapter.

This tree is a **vendored copy** of the local `myAgents/harness_core` skeleton so a
public `git clone` of PHA can import Core **without** a sibling checkout or PyPI.

| Module | Purpose |
|--------|---------|
| `turn_plan` | `TurnPlan` Protocol + `TurnPlanData` |
| `turn_fsm` | `CoreTurnPhase` + `PhaseRecorder` + plan-before-compose |
| `integrity` | `IntegrityResult` |
| `plan_vs_actual` | Portable diff codes |

**Not included:** Tier0 assemblers, health/tax plugins, CompareTable, filing_table.

Docs: [`docs/harness-core-protocol-v0.md`](../../docs/harness-core-protocol-v0.md)

```bash
# From PHA repo root
PYTHONPATH=packages/harness_core/src:. python -c "import harness_core; print(harness_core.__version__)"
PYTHONPATH=. python scripts/pha_harness_core_adapter_selfcheck.py
```
