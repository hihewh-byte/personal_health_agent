## Why this issue

PHA ships a **harness-first** control plane (Plan → Tier0 → LLM → Numerics/Compare audit), opposite of coding-agent style “LLM drives tools.”

Today that harness is **embedded in PHA** (not a pip package). Before we invest in extracting `agent-harness-core`, we want signal from builders who actually clone/read the code.

## 30s demo (no Ollama)

```bash
git clone https://github.com/hihewh-byte/personal_health_agent.git
cd personal_health_agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. python scripts/pha_harness_golden_run.py
```

You should see `RESULT: PASS` with profile / Tier0 slots / tools — no model call.

Docs: [docs/harness-builder-overview.md](../blob/main/docs/harness-builder-overview.md)

## Questions for you

Please comment with:

1. **Which modules feel portable** to a non-health domain? (vote / rank)
   - `TurnEvidencePlan` + profile registry
   - Tier0 protected budget assembly
   - Numerics / Compare-style post-audit
   - `HarnessBuildReport` / plan_vs_actual
   - Turn FSM / sub-agent veto protocol
2. **What blocked reuse?** (imports, health-specific slots, missing plugin API, docs, …)
3. Would you use a thin `agent-harness-core` if it shipped with a **non-health sample** (e.g. CSV finance Q&A + number audit)?

## Honest scope

- `v0.4.0-beta.1` — RLP / large English corpora not fully stress-tested
- We are **not** claiming a general agent framework yet — this issue is to decide whether extraction is worth it

Thanks — even a short “I ran golden run / I care about X” helps more than a silent Star.
