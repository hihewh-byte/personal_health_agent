"""F-layer fixture assertions for now_ps_6800_6801 (NOT production gates)."""

from __future__ import annotations

import re
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from pha.label_ledger_v1 import LabelLedgerV1

_NOW_TOKEN_RE = re.compile(r"\bNOW\b", re.I)
_PHOSPHATIDYL_RE = re.compile(r"phosphatidyl\s*serine|磷脂酰丝氨酸", re.I)
_CHOLINE_RE = re.compile(r"choline|胆碱", re.I)
_INOSITOL_RE = re.compile(r"inositol|肌醇", re.I)


def golden_match_now_ps_choline_inositol(ledger: "LabelLedgerV1") -> List[str]:
    """Return failure messages for CI fixture ``now_ps_6800_6801`` only."""
    fails: List[str] = []
    brand = (ledger.brand or "").upper()
    if "NOW" not in brand and not _NOW_TOKEN_RE.search(ledger.ledger_markdown or ""):
        fails.append(f"brand expected NOW, got {ledger.brand!r}")

    blob = " ".join(
        f"{r.name} {r.amount} {r.unit}" for r in ledger.ingredient_rows
    ).lower()
    if not _PHOSPHATIDYL_RE.search(blob):
        fails.append("missing phosphatidyl serine row")
    if not _CHOLINE_RE.search(blob):
        fails.append("missing choline row")
    if not _INOSITOL_RE.search(blob):
        fails.append("missing inositol row")
    inositol_50 = any(
        _INOSITOL_RE.search(r.name)
        and str(r.amount).strip() == "50"
        and (r.unit or "").lower() in ("mg", "mcg", "g")
        for r in ledger.ingredient_rows
    )
    if not inositol_50:
        fails.append("missing inositol 50 mg row")
    if ledger.attachment_count < 2:
        fails.append(f"attachment_count expected >=2, got {ledger.attachment_count}")
    if ledger.parse_confidence != "high":
        fails.append(
            f"parse_confidence expected high, got {ledger.parse_confidence} "
            f"reasons={ledger.reject_reasons}",
        )
    return fails


__all__ = ["golden_match_now_ps_choline_inositol"]
