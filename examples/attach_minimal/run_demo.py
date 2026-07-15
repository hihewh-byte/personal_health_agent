#!/usr/bin/env python3
"""Minimal attach demo: two turns, one PASS, one FAIL-CLOSED.

Run from the repo root:

    PYTHONPATH=packages/harness_core/src python examples/attach_minimal/run_demo.py

Round 1: the agent answers from the ticket table  -> PASS
Round 2: the agent invents a ticket + escalates a role -> FAIL-CLOSED,
         reply blocked, one failure row appended to failures.jsonl
         (directly consumable by `harness-loop harvest`).

Exit code 0 means the demo proved BOTH paths (pass and fail-closed).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # ticket_adapter / fake_agent
# Fallback so `python examples/attach_minimal/run_demo.py` also works bare.
_CORE_SRC = HERE.parents[1] / "packages" / "harness_core" / "src"
if _CORE_SRC.is_dir() and str(_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(_CORE_SRC))

from harness_core.interfaces import emit_failure_event, is_domain_adapter, run_post_audit

from fake_agent import compose_reply
from ticket_adapter import TicketAdapter

GREEN, RED, DIM, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[0m"
if not sys.stdout.isatty() and os.environ.get("FORCE_COLOR") != "1":
    GREEN = RED = DIM = RESET = ""

FAILURES_PATH = Path(os.environ.get("ATTACH_FAILURES_PATH") or HERE / "failures.jsonl")


def run_turn(adapter: TicketAdapter, turn: int, question: str, *, hallucinate: bool) -> bool:
    """Plan -> Compose -> Post-Audit for one turn. Returns verdict.ok."""
    plan = adapter.build_plan(question)                      # 1. freeze evidence
    draft = compose_reply(                                   # 2. your model composes
        question, adapter.render_evidence(), hallucinate=hallucinate
    )
    verdict = run_post_audit(adapter, plan, draft)           # 3. fail-closed audit

    print(f"\n── Turn {turn} ── {question}")
    print(f"{DIM}draft: {draft.splitlines()[0]}…{RESET}")
    if verdict.ok:
        print(f"{GREEN}PASS{RESET} verdict.ok=True atoms_checked={len(verdict.atoms_checked)}")
        print(draft)
    else:
        print(f"{RED}FAIL-CLOSED: verdict.ok=False{RESET}")
        for v in verdict.violations:
            print(f"{RED}  · {v}{RESET}")
        print(f"{DIM}reply blocked — no mid-turn healing, no retry{RESET}")
        row = emit_failure_event(
            FAILURES_PATH,
            user_message=question,
            verdict=verdict,
            session_name="attach_minimal_demo",
            turn=turn,
            lane="ticket",
        )
        print(f"{DIM}failure row → {FAILURES_PATH.name}: checks={row['checks']}{RESET}")
    return verdict.ok


def main() -> int:
    adapter = TicketAdapter()
    assert is_domain_adapter(adapter), "TicketAdapter must satisfy DomainAdapter"

    ok1 = run_turn(adapter, 1, "What access do the current tickets grant?", hallucinate=False)
    ok2 = run_turn(adapter, 2, "Can you confirm my admin access ticket?", hallucinate=True)

    demo_proved_both = ok1 and not ok2 and FAILURES_PATH.is_file()
    print(f"\n{'='*56}")
    print(f"demo: turn1={'PASS' if ok1 else 'FAIL'} turn2={'FAIL-CLOSED' if not ok2 else 'PASS?!'}")
    print("next: harness-loop harvest --e2e-jsonl "
          f"examples/attach_minimal/{FAILURES_PATH.name}")
    return 0 if demo_proved_both else 1


if __name__ == "__main__":
    raise SystemExit(main())
