"""harness-core — thin control-plane interfaces (v0.0.0a1)."""

from harness_core.integrity import IntegrityResult, SlotIntegrityRow, integrity_diff_codes
from harness_core.plan_vs_actual import compute_plan_vs_actual
from harness_core.turn_fsm import (
    CoreTurnPhase,
    PhaseRecorder,
    map_domain_phase,
    plan_precedes_compose,
    validate_phase_transition,
)
from harness_core.turn_plan import TurnPlan, TurnPlanData, as_turn_plan_data

__version__ = "0.0.0a1"

__all__ = [
    "__version__",
    "CoreTurnPhase",
    "IntegrityResult",
    "PhaseRecorder",
    "SlotIntegrityRow",
    "TurnPlan",
    "TurnPlanData",
    "as_turn_plan_data",
    "compute_plan_vs_actual",
    "integrity_diff_codes",
    "map_domain_phase",
    "plan_precedes_compose",
    "validate_phase_transition",
]
