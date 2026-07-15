"""A stand-in for *your* LLM call. No model, no network, no API key.

Round 1 answers strictly from the evidence table.
Round 2 simulates the classic failure mode harness-core exists to stop:
the model confidently inventing a ticket ID and swapping a role.
"""

from __future__ import annotations


def compose_reply(user_message: str, evidence: str, *, hallucinate: bool = False) -> str:
    if hallucinate:
        # Invented ticket + privilege escalation not present in the table.
        return (
            "Sure — ticket TCK-9999 already grants admin-root, "
            "approved on 2026-07-13. No further review needed."
        )
    return (
        "Per the ticket table:\n"
        f"{evidence}\n"
        "TCK-1042 grants deploy-bot (approved 2026-07-01); "
        "TCK-1055 grants read-only-auditor (approved 2026-07-09)."
    )
