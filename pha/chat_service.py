"""PHA streaming chat orchestration (SSE) with session persistence."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from pha.structured_log import log_exception
from pha.agent import (
    AgentAnswer,
    EvidenceItem,
    _parse_cited_refs,
)
from pha.agent_tools import (
    FAST_PATH_SYSTEM_ADDENDUM,
    FAST_MODE_STATUS,
    PHA_AGENT_TOOLS,
    apply_health_heuristic_override,
    execute_tool_call,
    infer_auto_tool_fallback,
    message_has_health_snapshot,
    tool_status_message,
    SNAPSHOT_MARKER,
    MAX_TOOL_ROUNDS,
)
from pha.chat_background import (
    MAX_CHAT_BACKGROUND_CHARS,
    build_user_background_block,
    maybe_capture_chat_background,
)
from pha.intent_gates import (
    QuestionType,
    classify_question_type,
    resolve_ldl_authority_years,
    should_inject_wearable_snapshot,
    should_strip_polluted_assistant_history,
    user_message_is_casual,
    user_message_needs_attachment_recall,
    user_message_needs_lab_dossier,
    user_message_needs_wearable_query,
)
from pha.chat_context import build_chat_context_block, extract_health_keywords, recent_turns
from pha.chat_storage import list_messages, search_messages_by_keywords
from pha.chat_router import (
    build_chat_audit_payload,
    build_ldl_authority_system_block,
    log_harness_payload,
    prepare_chat_evidence_bundle,
    probe_temporal_route,
)
from pha.chat_storage import (
    append_message,
    create_session,
    get_session,
    maybe_set_title_from_first_message,
    update_message_parsed_json,
)
from pha.event_medical import metrics_preview_dicts, narratives_preview_dicts
from pha.health_data import (
    build_system_date_block,
    effective_query_reference_date,
)
from pha.llm_provider import OllamaProvider
from pha.chat_ingest import ingest_chat_message, ingest_parsed_payload
from pha.patient_state import build_patient_state_evidence_slice
from pha.harness_report import (
    HarnessTurnInputs,
    build_harness_report,
    build_harness_telemetry,
    emit_harness_build_report,
)
from pha.harness_plan import (
    TurnEvidencePlan,
    assemble_tiered_supplemental,
    build_turn_evidence_plan,
    build_wearable_90d_summary_block,
    compute_plan_vs_actual,
    plan_allows_heuristic_snapshot,
)
from pha.evidence_catalog import (
    build_evidence_catalog_block,
    catalog_mode_enabled,
    format_fetched_evidence_text,
)
from pha.grounded_answer_composer import grounded_composer_enabled
from pha.numerics_manifest import (
    NumericsManifest,
    apply_numerics_audit_to_answer,
    audit_response_numerics,
    build_numerics_manifest,
    format_manifest_tier0_block,
    numerics_audit_mode,
    numerics_require_citation,
)

logger = logging.getLogger(__name__)

from pha.chat_message_stack import (  # noqa: E402
    ATTACH_PARSE_FAILURE_ADDENDUM,
    CHAT_HISTORY_MAX_CHARS,
    CHAT_HISTORY_MAX_TURNS,
    PATIENT_STATE_USER_PREAMBLE,
    PHA_MEDICAL_SOUL_LITE_SYSTEM_PROMPT,
    PHA_MEDICAL_SOUL_SYSTEM_PROMPT,
    SLOW_PATH_CHAT_STAGES,
    SYSTEM_CONTENT_MAX_CHARS,
    _build_supplemental_system_layers,
    _cap_system_content,
    _cap_system_tiered,
    _format_recalled_snippets,
    _merge_user_message,
    _session_history_messages,
    build_pha_chat_message_stack,
)
from pha.chat_attachments import (  # noqa: E402
    _message_needs_lab_ledger,
    _vision_parse_attachment,
    compute_attachment_ingest_status,
    parse_chat_attachment_file,
    record_chat_attachment_parse_failure,
)
from pha.chat_agent_runtime import (  # noqa: E402
    _agent_tools_for_plan,
    _catalog_stream_messages,
    _resolve_runtime_mode,
    _run_catalog_fetch_phase,
    _run_tool_loop_then_stream,
    _runtime_status_message,
)


def stream_pha_chat_events(
    *,
    user_id: str,
    user_message: str,
    model: str,
    session_id: Optional[str] = None,
    extra_system_context: str = "",
    attachment_path: Optional[str] = None,
    attachment_name: Optional[str] = None,
    attachment_paths: Optional[List[str]] = None,
    attachment_names: Optional[List[str]] = None,
    attachment_parsed_parts: Optional[List[Dict[str, Any]]] = None,
    clarify_choice_id: Optional[str] = None,
    response_locale: Optional[str] = None,
) -> Iterator[str]:
    """Yield SSE payloads; delegates to P0 turn orchestrator state machine."""
    from pha.chat_turn_orchestrator import orchestrate_chat_turn_events

    yield from orchestrate_chat_turn_events(
        user_id=user_id,
        user_message=user_message,
        model=model,
        session_id=session_id,
        extra_system_context=extra_system_context,
        attachment_path=attachment_path,
        attachment_name=attachment_name,
        attachment_paths=attachment_paths,
        attachment_names=attachment_names,
        attachment_parsed_parts=attachment_parsed_parts,
        clarify_choice_id=clarify_choice_id,
        response_locale=response_locale,
    )
