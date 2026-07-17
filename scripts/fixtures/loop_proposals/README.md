# Loop proposal inbox

Staging area for **Draft PR** notify (channel A).

- `inbox/alias_proposal_*.json` + `REVIEW_*.md` are created by
  `scripts/pha_loop_notify_proposal.py` when `--apply` / `PHA_LOOP_NOTIFY_APPLY=1`.
- These files are **proposal-only** (aliases). Catalog edits still require a
  separate human PR after `pha_loop_promote_candidate.py --full-veto`.
