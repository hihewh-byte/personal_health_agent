"""FSM spine selfcheck."""

from harness_core.turn_fsm import (
    CoreTurnPhase,
    PhaseRecorder,
    map_domain_phase,
    plan_precedes_compose,
    validate_phase_transition,
)


def test_phase_transitions() -> None:
    assert validate_phase_transition(None, CoreTurnPhase.INIT)
    assert validate_phase_transition(CoreTurnPhase.INIT, CoreTurnPhase.SESSION)
    assert validate_phase_transition(CoreTurnPhase.PLAN, CoreTurnPhase.COMPOSE)
    assert not validate_phase_transition(CoreTurnPhase.COMPOSE, CoreTurnPhase.PLAN)
    assert validate_phase_transition(CoreTurnPhase.SESSION, CoreTurnPhase.DONE)


def test_plan_before_compose_happy() -> None:
    rec = PhaseRecorder()
    for ph in (
        CoreTurnPhase.INIT,
        CoreTurnPhase.SESSION,
        CoreTurnPhase.PLAN,
        CoreTurnPhase.COMPOSE,
        CoreTurnPhase.POST_AUDIT,
        CoreTurnPhase.DONE,
    ):
        rec.enter(ph)
    rec.assert_plan_before_compose()
    assert plan_precedes_compose(rec.phases)


def test_compose_without_plan_fails() -> None:
    bad = [CoreTurnPhase.INIT, CoreTurnPhase.SESSION, CoreTurnPhase.COMPOSE]
    assert not plan_precedes_compose(bad)
    rec = PhaseRecorder()
    rec.phases = list(bad)
    try:
        rec.assert_plan_before_compose()
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass


def test_domain_alias_map() -> None:
    assert map_domain_phase("fast_lane") == CoreTurnPhase.COMPOSE
    assert map_domain_phase("slot_assembly") == CoreTurnPhase.PLAN
    assert map_domain_phase("scope") == CoreTurnPhase.SESSION
