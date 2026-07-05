"""P2 — Harness profile / schema registry validation + generation (consensus tooling)."""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Set

from pha.evidence_catalog import catalog_mode_enabled
from pha.harness_plan import TurnEvidencePlan, build_turn_evidence_plan

REGISTRY_MANIFEST_SCHEMA = "pha.harness_profile_registry/v1"
DEFAULT_REGISTRY_MANIFEST_PATH = (
    Path(__file__).resolve().parents[1] / "rules" / "harness_profile_registry.generated.json"
)

# Profiles that must have explicit Tier0 assembly config (not lifestyle fallback).
_KNOWN_ASSEMBLY_PROFILES: Set[str] = {
    "combined_review",
    "combined_review_catalog",
    "supplement_manifest",
    "attachment_asset_qa",
    "attachment_episodic_bridge",
    "attachment_grounded_review",
    "lab_cross_year",
    "wearable_only",
    "wearable_screenshot_review",
    "casual",
    "lifestyle",
}

# Slot invariants: profile contract, not per-session hardcoding.
_PROFILE_SLOT_INVARIANTS: Dict[str, Dict[str, Set[str]]] = {
    "wearable_only": {
        "required_tier0": {"NUMERICS_MANIFEST", "WEARABLE_90D_SUMMARY", "TASK"},
        "required_tools": set(),
        "forbidden_tools": {"fetch_evidence_by_id"},
    },
    "combined_review": {
        "required_tier0": {"EVIDENCE_CATALOG", "NUMERICS_MANIFEST", "TASK"},
        "required_tools": {"fetch_evidence_by_id"},
        "forbidden_tools": set(),
    },
    "lab_cross_year": {
        "required_tier0": {"NUMERICS_MANIFEST", "LDL_AUTHORITY", "TASK"},
        "required_tools": set(),
        "forbidden_tools": set(),
    },
    "wearable_screenshot_review": {
        "required_tier0": {
            "WEARABLE_SNAPSHOT",
            "WEARABLE_COMPARE_TABLE",
            "WEARABLE_90D_SUMMARY",
            "TASK",
        },
        "required_tools": set(),
        "forbidden_tools": {"fetch_evidence_by_id"},
    },
    "attachment_grounded_review": {
        "required_tier0": {"ATTACHMENT_LABEL", "TASK"},
        "required_tools": set(),
        "forbidden_tools": {"fetch_evidence_by_id"},
    },
}

# Stage 3H-γ: explicit specialized → grounded fallback contract (never lifestyle).
_PROFILE_GROUNDED_FALLBACK: Dict[str, str] = {
    "wearable_screenshot_review": "attachment_grounded_review",
    "attachment_asset_qa": "attachment_grounded_review",
    "attachment_episodic_bridge": "attachment_grounded_review",
}


@dataclass
class RegistryValidationResult:
    errors: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, msg: str) -> None:
        self.errors.append(msg)


def _tier0_slots(plan: TurnEvidencePlan) -> Set[str]:
    return {s for s in (plan.slots_tier0 or []) if s != "MASTER_ANCHOR"}


def _tools(plan: TurnEvidencePlan) -> Set[str]:
    return set(plan.tools_allowed or [])


def _plan_snapshot(plan: TurnEvidencePlan) -> Dict[str, Any]:
    qtype = plan.legacy_question_type
    qname = getattr(qtype, "name", str(qtype))
    return {
        "slots_tier0": sorted(_tier0_slots(plan)),
        "slots_tier1": sorted(set(plan.slots_tier1 or [])),
        "forbidden": sorted(set(plan.forbidden or [])),
        "tools_allowed": sorted(set(plan.tools_allowed or [])),
        "legacy_question_type": qname,
    }


def _profile_build_probes() -> List[tuple[str, TurnEvidencePlan]]:
    """Deterministic plan probes — generic messages, not battery scene IDs."""
    probes: List[tuple[str, TurnEvidencePlan]] = [
        ("casual", build_turn_evidence_plan("你好")),
        ("lifestyle", build_turn_evidence_plan("最近饮食需要注意什么")),
        ("wearable_only", build_turn_evidence_plan("我最近的 HRV 怎么样？")),
        ("lab_cross_year", build_turn_evidence_plan("2023和2025年血脂对比")),
        (
            "wearable_screenshot_review",
            build_turn_evidence_plan("HRV 怎么样", wearable_screenshot_review=True),
        ),
        (
            "attachment_asset_qa",
            build_turn_evidence_plan(
                "这个标签上的成分是什么",
                attachment_asset_qa=True,
                attachment_qa_mode="initial",
            ),
        ),
        (
            "attachment_episodic_bridge",
            build_turn_evidence_plan(
                "HRV 怎么样",
                attachment_asset_qa=True,
                attachment_qa_mode="episodic_bridge",
            ),
        ),
        (
            "attachment_grounded_review",
            build_turn_evidence_plan(
                "分析检验结果",
                attachment_grounded_review=True,
            ),
        ),
        (
            "supplement_manifest",
            build_turn_evidence_plan("我每天早上吃这些补剂，帮我看看时间安排"),
        ),
        ("combined_review", build_turn_evidence_plan("根据血脂和穿戴数据综合看看")),
    ]
    if catalog_mode_enabled():
        probes.append(
            (
                "combined_review_catalog",
                build_turn_evidence_plan("根据血脂和HRV分析补剂方案"),
            ),
        )
    from pha.harness_plan import build_clarify_turn_plan

    probes.append(("clarify", build_clarify_turn_plan()))
    return probes


def introspect_harness_profile_plans() -> Dict[str, Dict[str, Any]]:
    """Live introspection of TurnEvidencePlan contracts (generation source)."""
    return {name: _plan_snapshot(plan) for name, plan in _profile_build_probes()}


def generate_profile_registry_manifest() -> Dict[str, Any]:
    """Build machine-readable registry manifest from runtime harness_plan."""
    from pha.harness_tier0_assembly import _PROFILE_CONFIG  # noqa: PLC2701

    profiles = introspect_harness_profile_plans()
    return {
        "schema": REGISTRY_MANIFEST_SCHEMA,
        "profiles": profiles,
        "tier0_assembly_profiles": sorted(_PROFILE_CONFIG.keys()),
        "profile_slot_invariants": {
            profile: {
                "required_tier0": sorted(inv.get("required_tier0") or []),
                "required_tools": sorted(inv.get("required_tools") or []),
                "forbidden_tools": sorted(inv.get("forbidden_tools") or []),
            }
            for profile, inv in _PROFILE_SLOT_INVARIANTS.items()
        },
    }


def write_profile_registry_manifest(path: Path | None = None) -> Path:
    target = path or DEFAULT_REGISTRY_MANIFEST_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = generate_profile_registry_manifest()
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def _manifest_profile_keys(manifest: Dict[str, Any]) -> Set[str]:
    profiles = manifest.get("profiles") or {}
    if not isinstance(profiles, dict):
        return set()
    return {str(k) for k in profiles.keys()}


def validate_generated_manifest(
    path: Path | None = None,
) -> RegistryValidationResult:
    """Ensure checked-in generated manifest matches live harness introspection."""
    target = path or DEFAULT_REGISTRY_MANIFEST_PATH
    out = RegistryValidationResult()
    if not target.is_file():
        out.add(f"generated manifest missing: {target}")
        return out
    try:
        on_disk = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        out.add(f"generated manifest invalid JSON: {exc}")
        return out
    if on_disk.get("schema") != REGISTRY_MANIFEST_SCHEMA:
        out.add(
            f"generated manifest schema {on_disk.get('schema')!r} != {REGISTRY_MANIFEST_SCHEMA!r}",
        )
    live = generate_profile_registry_manifest()
    for key in ("profiles", "tier0_assembly_profiles", "profile_slot_invariants"):
        if on_disk.get(key) != live.get(key):
            out.add(f"generated manifest drift: field {key!r} differs from live introspection")
    missing = set(live.get("profiles") or {}) - _manifest_profile_keys(on_disk)
    if missing:
        out.add(f"generated manifest missing profiles: {sorted(missing)}")
    return out


def validate_plan_invariants(plan: TurnEvidencePlan) -> List[str]:
    """Validate a single plan against profile slot/tool invariants."""
    errors: List[str] = []
    inv = _PROFILE_SLOT_INVARIANTS.get(plan.profile)
    if inv is None:
        return errors
    t0 = _tier0_slots(plan)
    tools = _tools(plan)
    for slot in inv.get("required_tier0") or set():
        if slot not in t0:
            errors.append(f"{plan.profile}: missing required tier0 slot {slot!r}")
    for tool in inv.get("required_tools") or set():
        if tool not in tools:
            errors.append(f"{plan.profile}: missing required tool {tool!r}")
    for tool in inv.get("forbidden_tools") or set():
        if tool in tools:
            errors.append(f"{plan.profile}: forbidden tool present {tool!r}")
    return errors


def validate_representative_routes() -> RegistryValidationResult:
    """Route probes via build_turn_evidence_plan — generic messages, not battery IDs."""
    out = RegistryValidationResult()
    probes: List[tuple[str, TurnEvidencePlan, str | None]] = []

    probes.append(("casual", build_turn_evidence_plan("你好"), "casual"))
    probes.append(
        (
            "wearable_only",
            build_turn_evidence_plan("我最近的 HRV 怎么样？"),
            "wearable_only",
        ),
    )
    probes.append(
        (
            "lab_cross_year",
            build_turn_evidence_plan("2023和2025年血脂对比"),
            "lab_cross_year",
        ),
    )
    probes.append(
        (
            "wearable_screenshot",
            build_turn_evidence_plan(
                "HRV 怎么样",
                wearable_screenshot_review=True,
            ),
            "wearable_screenshot_review",
        ),
    )
    if catalog_mode_enabled():
        probes.append(
            (
                "combined_review_catalog",
                build_turn_evidence_plan("根据血脂和HRV分析补剂方案"),
                "combined_review",
            ),
        )

    for label, plan, want_profile in probes:
        if want_profile and plan.profile != want_profile:
            out.add(f"route {label}: profile {plan.profile!r} != {want_profile!r}")
        out.errors.extend(validate_plan_invariants(plan))

    return out


def validate_tier0_assembly_coverage() -> RegistryValidationResult:
    from pha.harness_tier0_assembly import _PROFILE_CONFIG  # noqa: PLC2701

    out = RegistryValidationResult()
    missing = _KNOWN_ASSEMBLY_PROFILES - set(_PROFILE_CONFIG.keys())
    if missing:
        out.add(f"tier0 assembly missing profiles: {sorted(missing)}")
    if catalog_mode_enabled() and "combined_review_catalog" not in _PROFILE_CONFIG:
        out.add("combined_review_catalog assembly config missing while catalog mode on")
    return out


def validate_schema_assets() -> RegistryValidationResult:
    from pha.universal_catalog_manager import get_catalog_manager

    out = RegistryValidationResult()
    mgr = get_catalog_manager()
    known_profiles = _KNOWN_ASSEMBLY_PROFILES | {"clarify", "attachment_asset_qa", "attachment_episodic_bridge"}

    for asset_id, doc in (mgr._assets or {}).items():  # noqa: SLF001 — registry validator
        catalog = doc.get("catalog") or {}
        for prof in catalog.get("profiles") or []:
            p = str(prof).strip()
            if p and p not in known_profiles:
                out.add(f"schema {asset_id}: unknown catalog profile {p!r}")

        fetch = doc.get("fetch") or {}
        adapter = fetch.get("adapter") or {}
        module_name = str(adapter.get("module") or "").strip()
        callable_name = str(adapter.get("callable") or "").strip()
        if fetch.get("mode") == "adapter" and module_name and callable_name:
            try:
                mod = importlib.import_module(module_name)
                if not callable(getattr(mod, callable_name, None)):
                    out.add(
                        f"schema {asset_id}: adapter {module_name}.{callable_name} not callable",
                    )
            except ImportError as exc:
                out.add(f"schema {asset_id}: adapter import failed: {exc}")

        metrics = doc.get("metrics") or {}
        canonical = metrics.get("canonical") or []
        core = metrics.get("core") or []
        if core and not set(core) <= set(canonical):
            out.add(f"schema {asset_id}: metrics.core not subset of canonical")

    return out


def _iter_schema_keyword_rules(
    doc: Dict[str, Any],
    key: str,
) -> Iterable[tuple[str, float]]:
    intent = doc.get("intent") or {}
    catalog = doc.get("catalog") or {}
    raw = intent.get(key) or catalog.get(key) or []
    for item in raw:
        if isinstance(item, dict):
            token = str(item.get("token") or "").strip()
            if token:
                yield token, float(item.get("weight") or 1.0)
        elif isinstance(item, str) and item.strip():
            yield item.strip(), 1.0


def validate_schema_trigger_conflicts(
    *,
    min_token_len: int = 2,
) -> RegistryValidationResult:
    """Offline CI: detect shared trigger_keywords across schema assets (Stage 4 P2)."""
    from pha.universal_catalog_manager import get_catalog_manager

    out = RegistryValidationResult()
    mgr = get_catalog_manager()
    index: Dict[str, Set[str]] = {}
    for asset_id, doc in (mgr._assets or {}).items():  # noqa: SLF001
        if str(doc.get("status") or "active") != "active":
            continue
        for token, weight in _iter_schema_keyword_rules(doc, "trigger_keywords"):
            if weight <= 0 or len(token) < min_token_len:
                continue
            norm = token.lower()
            index.setdefault(norm, set()).add(str(asset_id))
    for token, assets in sorted(index.items()):
        if len(assets) > 1:
            out.add(
                f"schema trigger conflict: token {token!r} in assets {sorted(assets)}",
            )
    return out


def validate_health_intent_catalog_registry() -> RegistryValidationResult:
    """Ensure rules/health_intent_catalog.json aligns with harness profile registry."""
    import json

    out = RegistryValidationResult()
    catalog_path = Path(__file__).resolve().parents[1] / "rules" / "health_intent_catalog.json"
    if not catalog_path.is_file():
        out.add(f"health intent catalog missing: {catalog_path}")
        return out
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        out.add(f"health intent catalog invalid JSON: {exc}")
        return out

    profiles = catalog.get("profiles") or {}
    if not isinstance(profiles, dict):
        out.add("health intent catalog: profiles must be object")
        return out

    manifest_profiles = set(introspect_harness_profile_plans().keys())
    for name, cfg in profiles.items():
        if not isinstance(cfg, dict):
            out.add(f"health intent catalog: profile {name!r} config must be object")
            continue
        if name not in manifest_profiles and name not in _KNOWN_ASSEMBLY_PROFILES:
            out.add(f"health intent catalog: unknown profile {name!r}")

    anchor_labels = catalog.get("session_anchor_labels") or {}
    if isinstance(anchor_labels, dict):
        for label_key in anchor_labels:
            prof_cfg = profiles.get(label_key) or {}
            if not prof_cfg.get("episodic_continue"):
                out.add(
                    f"health intent catalog: session_anchor_labels[{label_key!r}] "
                    "missing episodic_continue in profiles",
                )
    return out


def validate_slot_invariants_vs_manifest() -> RegistryValidationResult:
    """Hand-maintained slot invariants must match generated profile introspection."""
    out = RegistryValidationResult()
    live_profiles = introspect_harness_profile_plans()
    for profile, inv in _PROFILE_SLOT_INVARIANTS.items():
        snap = live_profiles.get(profile)
        if snap is None:
            out.add(f"slot invariants: profile {profile!r} missing from introspection")
            continue
        t0 = set(snap.get("slots_tier0") or [])
        tools = set(snap.get("tools_allowed") or [])
        for slot in inv.get("required_tier0") or set():
            if slot not in t0:
                out.add(f"slot invariants: {profile} requires tier0 {slot!r} not in live plan")
        for tool in inv.get("required_tools") or set():
            if tool not in tools:
                out.add(f"slot invariants: {profile} requires tool {tool!r} not in live plan")
        for tool in inv.get("forbidden_tools") or set():
            if tool in tools:
                out.add(f"slot invariants: {profile} forbids tool {tool!r} but live plan allows it")
    return out


def validate_harness_profile_registry() -> RegistryValidationResult:
    """Run all registry validations."""
    merged = RegistryValidationResult()
    for part in (
        validate_representative_routes(),
        validate_tier0_assembly_coverage(),
        validate_schema_assets(),
        validate_schema_trigger_conflicts(),
        validate_health_intent_catalog_registry(),
        validate_slot_invariants_vs_manifest(),
        validate_generated_manifest(),
    ):
        merged.errors.extend(part.errors)
    return merged


__all__ = [
    "DEFAULT_REGISTRY_MANIFEST_PATH",
    "REGISTRY_MANIFEST_SCHEMA",
    "RegistryValidationResult",
    "generate_profile_registry_manifest",
    "introspect_harness_profile_plans",
    "validate_generated_manifest",
    "validate_harness_profile_registry",
    "validate_health_intent_catalog_registry",
    "validate_plan_invariants",
    "validate_representative_routes",
    "validate_schema_assets",
    "validate_schema_trigger_conflicts",
    "validate_slot_invariants_vs_manifest",
    "validate_tier0_assembly_coverage",
    "write_profile_registry_manifest",
]
