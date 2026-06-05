"""Stage 3B Week 1 — layout-weighted multi-image merge (P-layer, product-agnostic)."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

# Spec: stage3b-beta-vision-worker-spec.md §5.2
_AUTHORITATIVE_INGREDIENT_HINTS = frozenset(
    {
        "supplement_facts_panel",
        "nutrition_facts_table",
        "tabular_block",
        "dense_text_block",
        "ingredient_list_text",
        "traditional_text",
        "single_panel_label",
    },
)

_INGREDIENT_WEIGHT: Dict[str, float] = {
    "supplement_facts_panel": 1.0,
    "nutrition_facts_table": 1.0,
    "tabular_block": 1.0,
    "dense_text_block": 0.95,
    "ingredient_list_text": 0.9,
    "traditional_text": 0.9,
    "single_panel_label": 0.85,
    "supplement_front": 0.2,
    "product_marketing": 0.2,
    "ecommerce_product_screenshot": 0.1,
    "supplement_label": 0.5,
    "unknown": 0.5,
}

_BRAND_WEIGHT: Dict[str, float] = {
    "supplement_front": 0.8,
    "product_marketing": 0.8,
    "single_panel_label": 0.7,
    "ecommerce_product_screenshot": 0.4,
    "supplement_facts_panel": 0.3,
    "nutrition_facts_table": 0.3,
    "ingredient_list_text": 0.5,
    "traditional_text": 0.5,
    "unknown": 0.5,
}


def _max_hint_weight(hints: List[str], table: Dict[str, float], *, default: float = 0.5) -> float:
    if not hints:
        return default
    return max((table.get(h, default) for h in hints), default=default)


def ingredient_weight_for_hints(hints: List[str]) -> float:
    return _max_hint_weight(hints, _INGREDIENT_WEIGHT)


def brand_weight_for_hints(hints: List[str]) -> float:
    return _max_hint_weight(hints, _BRAND_WEIGHT)


def has_authoritative_ingredient_panel(hints: List[str]) -> bool:
    return bool(_AUTHORITATIVE_INGREDIENT_HINTS.intersection(hints or []))


def pick_string_by_weight(
    candidates: List[Tuple[str, float, int]],
) -> Tuple[str, List[Dict[str, Any]]]:
    """Pick non-empty string with max weight; trace all considered."""
    trace: List[Dict[str, Any]] = []
    best = ""
    best_w = -1.0
    best_idx = 0
    for value, weight, image_index in candidates:
        trace.append(
            {
                "source_image_index": image_index,
                "weight": weight,
                "value_preview": (value or "")[:80],
            },
        )
        if (value or "").strip() and weight > best_w:
            best = value.strip()
            best_w = weight
            best_idx = image_index
    if best:
        trace.append({"rule": "max_weight", "winner_index": best_idx, "weight": best_w})
    return best, trace


def merge_ingredient_rows_weighted(
    row_batches: List[Tuple[List[Any], float, int, List[str]]],
) -> Tuple[List[Any], List[Dict[str, Any]]]:
    """
    Each batch: (rows, weight, image_index, hints).
    Dedupe by name|amount|unit; keep highest-weight source; conflicts → trace only.
    """
    best_by_key: Dict[str, Tuple[Any, float, int]] = {}
    trace: List[Dict[str, Any]] = []
    for rows, weight, image_index, hints in row_batches:
        for row in rows:
            name = getattr(row, "name", None) or (row.get("name") if isinstance(row, dict) else "")
            amount = getattr(row, "amount", None) or (row.get("amount") if isinstance(row, dict) else "")
            unit = getattr(row, "unit", None) or (row.get("unit") if isinstance(row, dict) else "")
            key = f"{str(name).lower()}|{amount}|{unit}"
            prev = best_by_key.get(key)
            if prev is None or weight > prev[1]:
                if prev is not None and prev[1] == weight and prev[0] != row:
                    trace.append(
                        {
                            "field": "ingredient_rows",
                            "rule": "ingredient_conflict",
                            "key": key,
                            "source_image_index": image_index,
                        },
                    )
                best_by_key[key] = (row, weight, image_index)
            elif prev is not None and weight == prev[1] and prev[0] != row:
                trace.append(
                    {
                        "field": "ingredient_rows",
                        "rule": "ingredient_conflict",
                        "key": key,
                        "source_image_index": image_index,
                    },
                )
        trace.append(
            {
                "field": "ingredient_rows",
                "source_image_index": image_index,
                "layout_hints": list(hints),
                "weight": weight,
                "row_count": len(rows),
            },
        )
    merged = [t[0] for t in best_by_key.values()]
    if merged:
        trace.append({"field": "ingredient_rows", "rule": "max_weight_merge", "count": len(merged)})
    return merged, trace


__all__ = [
    "brand_weight_for_hints",
    "has_authoritative_ingredient_panel",
    "ingredient_weight_for_hints",
    "merge_ingredient_rows_weighted",
    "pick_string_by_weight",
]
