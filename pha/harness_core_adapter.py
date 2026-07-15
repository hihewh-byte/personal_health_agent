"""Thin bridge: PHA plans/phases → in-repo / sibling ``harness_core``.

Does not replace ``pha.harness_plan`` / ``pha.chat_turn_fsm``.

Resolution order:
1. Already importable ``harness_core``
2. In-repo vendored package: ``packages/harness_core/src`` (public clone)
3. Optional sibling / ``HARNESS_CORE_SRC`` override (local monorepo)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


class HarnessCoreUnavailable(ImportError):
    """``harness_core`` not on PYTHONPATH and not found under packages/."""


def _candidate_src_dirs() -> list[Path]:
    here = Path(__file__).resolve()
    # pha/harness_core_adapter.py → personal_health_agent/packages/harness_core/src
    pha_root = here.parents[1]
    roots = [
        pha_root / "packages" / "harness_core" / "src",
        # Legacy local sibling (myAgents/harness_core)
        here.parents[2] / "harness_core" / "src",
        here.parents[1].parent / "harness_core" / "src",
    ]
    env = (os.environ.get("HARNESS_CORE_SRC") or "").strip()
    if env:
        roots.insert(0, Path(env))
    return roots


def ensure_harness_core() -> None:
    """Insert vendored or sibling harness_core/src onto sys.path if needed."""
    try:
        import harness_core  # noqa: F401

        return
    except ImportError:
        pass
    for src in _candidate_src_dirs():
        if (src / "harness_core").is_dir():
            p = str(src)
            if p not in sys.path:
                sys.path.insert(0, p)
            try:
                import harness_core  # noqa: F401

                return
            except ImportError:
                continue
    raise HarnessCoreUnavailable(
        "harness_core not found; expected packages/harness_core/src in this repo "
        "(or set HARNESS_CORE_SRC)"
    )


def harness_core_available() -> bool:
    try:
        ensure_harness_core()
        return True
    except HarnessCoreUnavailable:
        return False


def to_core_plan(plan: Any, *, fast_lane: bool | None = None) -> Any:
    """Map ``TurnEvidencePlan`` → ``TurnPlanData``."""
    ensure_harness_core()
    from harness_core.turn_plan import as_turn_plan_data

    meta: dict[str, Any] = {}
    lqt = getattr(plan, "legacy_question_type", None)
    if lqt is not None:
        meta["legacy_question_type"] = getattr(lqt, "value", str(lqt))
    data = as_turn_plan_data(plan, domain_meta=meta)
    if fast_lane is not None and data.fast_lane != bool(fast_lane):
        from harness_core.turn_plan import TurnPlanData

        data = TurnPlanData(
            profile=data.profile,
            slots_tier0=data.slots_tier0,
            slots_tier1=data.slots_tier1,
            forbidden=data.forbidden,
            tools_allowed=data.tools_allowed,
            task_text=data.task_text,
            fast_lane=bool(fast_lane),
            preserve_raw_user=data.preserve_raw_user,
            domain_meta=data.domain_meta,
        )
    return data


def record_domain_phases(domain_phase_names: Sequence[str]) -> Any:
    """Map PHA phase name strings onto Core ``PhaseRecorder``."""
    ensure_harness_core()
    from harness_core.turn_fsm import PhaseRecorder, map_domain_phase

    rec = PhaseRecorder()
    for name in domain_phase_names:
        core = map_domain_phase(str(name))
        rec.enter(core, domain_alias=str(name))
    return rec


def assert_plan_before_compose_domain(domain_phase_names: Sequence[str]) -> None:
    rec = record_domain_phases(domain_phase_names)
    rec.assert_plan_before_compose()


def integrity_from_mapping(data: Mapping[str, Any] | None) -> Any:
    ensure_harness_core()
    from harness_core.integrity import IntegrityResult

    return IntegrityResult.from_mapping(data)


def plan_vs_actual_via_core(
    plan: Any,
    *,
    tools_executed: Sequence[str] = (),
    slot_contents: Mapping[str, str] | None = None,
    tool_error: str | None = None,
    integrity: Mapping[str, Any] | None = None,
) -> list[str]:
    ensure_harness_core()
    from harness_core.plan_vs_actual import compute_plan_vs_actual

    core_plan = to_core_plan(plan)
    return compute_plan_vs_actual(
        core_plan,
        tools_executed=tools_executed,
        slot_contents=slot_contents,
        tool_error=tool_error,
        integrity=integrity,
    )


class PHANumericsAdapter:
    """PHA as *reference implementation* of ``harness_core.interfaces.DomainAdapter``.

    Thin wrapper only — delegates to existing PHA plan building and the
    numerics-manifest value/date sets. Does not touch chat/routing paths.

    ``manifest`` supplies the turn's allowlist (values + report dates).
    Callers that already hold a built ``NumericsManifest`` inject it here;
    selfchecks may inject a synthetic one.
    """

    def __init__(self, manifest: Any = None) -> None:
        self._manifest = manifest

    def build_plan(self, user_message: str) -> Any:
        from pha.harness_plan import build_turn_evidence_plan

        return to_core_plan(build_turn_evidence_plan(user_message))

    def extract_atoms(self, text: str) -> list[str]:
        # Same normalization the C-layer numerics audit uses.
        from pha.numerics_manifest import (
            _extract_decimal_tokens,
            _extract_normalized_dates,
        )

        atoms: list[str] = []
        for tok in _extract_normalized_dates(text or "") + _extract_decimal_tokens(text or ""):
            if tok and tok not in atoms:
                atoms.append(tok)
        return atoms

    def allowed_atoms(self, plan: Any) -> set[str]:
        if self._manifest is None:
            return set()
        return set(self._manifest.allowed_values) | set(self._manifest.allowed_dates)


def selfcheck_domain_adapter_conformance() -> dict[str, Any]:
    """Runtime proof that PHA conforms to the frozen v1 adapter contract."""
    ensure_harness_core()
    from harness_core.interfaces import is_domain_adapter

    adapter = PHANumericsAdapter()
    if not is_domain_adapter(adapter):
        raise AssertionError("PHANumericsAdapter does not satisfy DomainAdapter")
    return {
        "conforms": True,
        "adapter": type(adapter).__name__,
        "contract": "harness_core.interfaces.DomainAdapter/v1",
    }


def smoke_adapter_roundtrip(plan: Any) -> dict[str, Any]:
    """Dry-run proof used by golden / selfcheck. Raises if core missing."""
    core_plan = to_core_plan(plan)
    # Canonical PHA plan→compose spine (aliases collapse to core ranks)
    phases = [
        "init",
        "session",
        "plan",
        "slot_assembly",
        "compose",
        "post_audit",
        "done",
    ]
    rec = record_domain_phases(phases)
    rec.assert_plan_before_compose()
    return {
        "core_profile": core_plan.profile,
        "core_slots_tier0": list(core_plan.slots_tier0),
        "core_phases": rec.as_names(),
        "domain_aliases": list(rec.domain_aliases),
        "domain_meta_keys": sorted(core_plan.domain_meta.keys()),
    }


__all__ = [
    "HarnessCoreUnavailable",
    "PHANumericsAdapter",
    "assert_plan_before_compose_domain",
    "ensure_harness_core",
    "harness_core_available",
    "integrity_from_mapping",
    "plan_vs_actual_via_core",
    "record_domain_phases",
    "selfcheck_domain_adapter_conformance",
    "smoke_adapter_roundtrip",
    "to_core_plan",
]
