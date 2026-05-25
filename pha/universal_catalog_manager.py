"""P1 Schema Registry — load evidence asset contracts and route Catalog fetch."""

from __future__ import annotations

import importlib
import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from pha.catalog_dch import build_dynamic_when_zh, infer_wearable_metrics_from_schema
from pha.schema_intent_router import (
    IntentRouteResult,
    resolve_intent_route,
    should_capture_background_from_schema,
)
from pha.chat_background import build_user_background_block, summarize_supplement_bg_for_tier0
from pha.chat_router import build_ldl_authority_system_block
from pha.intent_gates import resolve_ldl_authority_years
from pha.temporal_router import parse_temporal_intent

logger = logging.getLogger(__name__)

_SCHEMA_DIR = Path(__file__).resolve().parent.parent / "storage" / "schemas"
_MAX_CATALOG_ENTRIES = 5


def _load_json_schema(path: Path) -> Dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


class UniversalCatalogManager:
  """Hot-load ``storage/schemas/*.schema.json`` and dispatch fetch by strategy."""

  def __init__(self, schema_dir: Optional[Path] = None) -> None:
    self._schema_dir = schema_dir or _SCHEMA_DIR
    self._assets: Dict[str, Dict[str, Any]] = {}
    self._alias_to_canonical: Dict[str, str] = {}
    self._reload()

  def _reload(self) -> None:
    assets: Dict[str, Dict[str, Any]] = {}
    alias: Dict[str, str] = {}

    if self._schema_dir.is_dir():
      for path in sorted(self._schema_dir.glob("*.schema.json")):
        doc = _load_json_schema(path)
        aid = str(doc.get("asset_id") or "").strip()
        if not aid:
          logger.warning("skip schema without asset_id: %s", path.name)
          continue
        assets[aid] = doc
        alias[aid] = aid
        for leg in doc.get("legacy_ids") or []:
          alias[str(leg).strip()] = aid
        resolve_map = (doc.get("dual_track") or {}).get("resolve_map") or {}
        for old_id, new_id in resolve_map.items():
          alias[str(old_id).strip()] = str(new_id).strip()

    self._assets = assets
    self._alias_to_canonical = alias
    try:
      from pha.metadata_catalog import invalidate_metadata_catalog_cache

      invalidate_metadata_catalog_cache()
    except ImportError:
      pass

  def resolve_intent(self, user_message: str) -> IntentRouteResult:
    from pha.intent_gates import (
      user_message_has_clinical_lab_intent,
      user_message_is_casual,
      user_message_needs_lab_dossier,
      user_message_needs_wearable_query,
    )

    msg = (user_message or "").strip()
    return resolve_intent_route(
      msg,
      self._assets,
      is_casual=user_message_is_casual(msg),
      needs_lab_dossier=user_message_needs_lab_dossier(msg),
      has_clinical_lab=user_message_has_clinical_lab_intent(msg),
      has_wearable_query=user_message_needs_wearable_query(msg),
    )

  def should_include_supplement_catalog(self, user_message: str) -> bool:
    route = self.resolve_intent(user_message)
    if route.profile != "combined_review":
      return False
    return route.include_supplement_catalog

  def should_capture_background(self, user_message: str) -> bool:
    doc = self.get_asset("supplement_bg")
    return should_capture_background_from_schema(user_message, doc)

  def resolve_id(self, raw_id: str) -> Optional[str]:
    key = (raw_id or "").strip()
    if not key:
      return None
    return self._alias_to_canonical.get(key)

  def get_asset(self, asset_id: str) -> Optional[Dict[str, Any]]:
    canonical = self.resolve_id(asset_id)
    if not canonical:
      return None
    return self._assets.get(canonical)

  def default_combined_fetch_ids(self, user_message: str = "", *, user_id: str = "default") -> List[str]:
    ranked: List[tuple[int, str]] = []
    for aid, doc in self._assets.items():
      cat = doc.get("catalog") or {}
      if not cat.get("enabled"):
        continue
      if cat.get("conditional") and aid == "supplement_bg":
        if not self.should_include_supplement_catalog(user_message):
          continue
      if not cat.get("include_in_default_combined"):
        if aid == "lab_lipid_panel" or aid == "wearable_bundle":
          ranked.append((int(cat.get("default_combined_rank") or 99), aid))
        continue
      ranked.append((int(cat.get("default_combined_rank") or 99), aid))
    ranked.sort(key=lambda x: (x[0], x[1]))
    ids = [aid for _, aid in ranked]
    if not ids:
      return ["lab_lipid_panel", "wearable_bundle"]
    if "lab_lipid_panel" not in ids:
      ids.insert(0, "lab_lipid_panel")
    if "wearable_bundle" not in ids:
      ids.insert(1, "wearable_bundle")
    from pha.catalog_existence import catalog_existence_veto_enabled, existence_probe_for_asset

    if catalog_existence_veto_enabled():
      uid = (user_id or "default").strip() or "default"
      ids = [
        aid
        for aid in ids
        if existence_probe_for_asset(uid, aid, self.get_asset(aid))[0]
      ]
    return ids[:3]

  def catalog_asset_ids_for_profile(
    self,
    profile: str,
    user_message: str = "",
    *,
    user_id: str = "default",
  ) -> List[str]:
    out: List[str] = []
    for aid, doc in sorted(self._assets.items()):
      cat = doc.get("catalog") or {}
      if not cat.get("enabled"):
        continue
      profiles = cat.get("profiles") or []
      if profile and profiles and profile not in profiles:
        continue
      if cat.get("conditional") and aid == "supplement_bg":
        if not self.should_include_supplement_catalog(user_message):
          continue
      out.append(aid)
    if profile == "combined_review":
      order = ["lab_lipid_panel", "wearable_bundle", "supplement_bg"]
      out = [x for x in order if x in out] + [x for x in out if x not in order]
    from pha.catalog_existence import catalog_existence_veto_enabled, existence_probe_for_asset

    if catalog_existence_veto_enabled():
      uid = (user_id or "default").strip() or "default"
      filtered: List[str] = []
      for aid in out:
        ok, _ = existence_probe_for_asset(uid, aid, self.get_asset(aid))
        if ok:
          filtered.append(aid)
      out = filtered
    return out[:_MAX_CATALOG_ENTRIES]

  def infer_wearable_metrics(self, user_message: str) -> List[str]:
    doc = self.get_asset("wearable_bundle")
    if not doc:
      return []
    from pha.intent_gates import _LAB_MARKERS_RE, user_message_needs_wearable_query

    msg = user_message or ""
    has_lab = bool(_LAB_MARKERS_RE.search(msg))
    default_wearable = user_message_needs_wearable_query(msg)
    return infer_wearable_metrics_from_schema(
      msg,
      doc,
      default_if_wearable_query=default_wearable,
      has_lab_only=has_lab and not default_wearable,
    )

  def build_catalog_block(
    self,
    *,
    profile: str,
    user_message: str = "",
    user_id: str = "default",
  ) -> str:
    msg = (user_message or "").strip()
    uid = (user_id or "default").strip() or "default"
    lines = [
      "【Evidence Catalog · Schema Registry · DCH · fetch_evidence_by_id 点单】",
      "格式：id | 说明 | 适用问法 | 预估字数",
    ]
    ids = self.catalog_asset_ids_for_profile(profile, user_message=msg, user_id=uid)
    for aid in ids:
      doc = self._assets.get(aid) or {}
      disp = doc.get("display") or {}
      cat = doc.get("catalog") or {}
      instr = (cat.get("llm_instruction_zh") or "")[: int(cat.get("max_instruction_chars") or 120)]
      title = disp.get("title_zh") or aid
      if cat.get("trigger_keywords") or cat.get("core_hint_keywords"):
        when = build_dynamic_when_zh(msg, cat, static_when_zh=str(disp.get("when_zh") or ""))
      else:
        when = disp.get("when_zh") or ""
      est = disp.get("est_chars") or ""
      line = f"- {aid} | {title} | {when} | {est}"
      if len(line) > 280:
        line = line[:277] + "…"
      if instr:
        tail = f" | {instr}"
        if len(line) + len(tail) <= 320:
          line += tail
      lines.append(line)
    try:
      from pha.dynamic_slot_registry import list_promoted_slots, user_dynamic_slots_enabled

      if user_dynamic_slots_enabled() and profile == "combined_review":
        for sl in list_promoted_slots(uid, profile):
          sid = str(sl.get("slot_id") or "")
          title = str(sl.get("title_zh") or sid)
          maps_to = str(sl.get("maps_to_asset") or "supplement_bg")
          dyn_line = (
            f"- dyn:{sid} | {title} | 用户背景备忘 | ≤400 "
            f"| 点单请用 fetch ids=[\"{maps_to}\"]"
          )
          if len(dyn_line) > 320:
            dyn_line = dyn_line[:317] + "…"
          lines.append(dyn_line)
    except ImportError:
      pass
    default_ids = self.default_combined_fetch_ids(user_message=msg, user_id=uid)
    lines.append(
      '点单示例：fetch_evidence_by_id(ids=["'
      + '","'.join(default_ids)
      + '"])（旧 ID LDL_TABLE/WEARABLE_90D 仍可用）',
    )
    return "\n".join(lines)

  def manifest_domain_for_asset(self, asset_id: str) -> Optional[str]:
    doc = self.get_asset(asset_id)
    if not doc:
      return None
    domain = (doc.get("manifest") or {}).get("domain")
    return str(domain) if domain else None

  def fetched_includes_manifest_domain(
    self,
    fetched_ids: Sequence[str],
    domain: str,
  ) -> bool:
    want = (domain or "").strip().lower()
    if not want:
      return False
    for raw in fetched_ids:
      canonical = self.resolve_id(str(raw))
      if not canonical:
        continue
      got = self.manifest_domain_for_asset(canonical)
      if got and got.lower() == want:
        return True
      # Legacy supplement does not set lipid/wearable.
    return False

  def fetch_asset_text(
    self,
    user_id: str,
    asset_id: str,
    user_message: str = "",
  ) -> str:
    canonical = self.resolve_id(asset_id)
    if not canonical:
      return f"【{asset_id}】未知 Catalog 资产 ID。"
    doc = self._assets.get(canonical)
    if not doc:
      return f"【{asset_id}】未知 Catalog 资产 ID。"
    strategy = str(doc.get("strategy") or "").strip()
    handler = _STRATEGY_HANDLERS.get(strategy)
    if not handler:
      return f"【{canonical}】未注册 strategy：{strategy}。"
    return handler(doc, user_id, user_message).strip()


def _fetch_lab_panel(schema: Dict[str, Any], user_id: str, user_message: str) -> str:
  intent = parse_temporal_intent(user_message)
  years = resolve_ldl_authority_years(user_id, user_message, intent)
  empty = (schema.get("fetch") or {}).get("adapter", {}).get("empty_message_zh")
  aid = schema.get("asset_id") or "lab_lipid_panel"
  if not years:
    return empty or f"【{aid}】库内无匹配年份的血脂报告。"
  return build_ldl_authority_system_block(user_id, years)


def _fetch_wearable_ts(schema: Dict[str, Any], user_id: str, user_message: str) -> str:
  adapter = (schema.get("fetch") or {}).get("adapter") or {}
  mod_name = adapter.get("module") or "pha.harness_plan"
  callable_name = adapter.get("callable") or "build_wearable_90d_summary_block"
  fn = _import_callable(mod_name, callable_name)
  text = fn(user_id, user_message).strip()
  if text:
    return text
  empty = adapter.get("empty_message_zh")
  aid = schema.get("asset_id") or "wearable_bundle"
  return empty or f"【{aid}】近窗无穿戴数据。"


def _fetch_supplement_bg(
  _schema: Dict[str, Any],
  user_id: str,
  user_message: str,
) -> str:
  raw = build_user_background_block(user_id, user_message=user_message)
  if not raw.strip():
    return "【SUPPLEMENT_BG】库内无补剂/用药背景拷贝。"
  return summarize_supplement_bg_for_tier0(raw, max_chars=800)


def _import_callable(module_name: str, callable_name: str) -> Callable[..., str]:
  mod = importlib.import_module(module_name)
  fn = getattr(mod, callable_name)
  return fn  # type: ignore[no-any-return]


_STRATEGY_HANDLERS: Dict[str, Callable[[Dict[str, Any], str, str], str]] = {
  "lab_panel": _fetch_lab_panel,
  "wearable_ts": _fetch_wearable_ts,
  "supplement_bg": _fetch_supplement_bg,
}

_manager: Optional[UniversalCatalogManager] = None


def get_catalog_manager() -> UniversalCatalogManager:
  global _manager
  if _manager is None:
    _manager = UniversalCatalogManager()
  return _manager


def reload_catalog_manager() -> UniversalCatalogManager:
  global _manager
  _manager = UniversalCatalogManager()
  return _manager


__all__ = [
  "UniversalCatalogManager",
  "get_catalog_manager",
  "reload_catalog_manager",
]
