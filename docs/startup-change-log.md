# Startup Change Log

> Purpose: mandatory shared context log for startup/availability related changes.  
> Rule: when changing startup-critical files, update this log in the same PR.

---

## 2026-07-13

- **CI installs Official Loop Suite α**:
  - `.github/workflows/ci.yml`: add `pip install -e packages/harness_loop` after `harness_core`.
  - Reason: suite selfcheck (`pha_harness_loop_suite_selfcheck`) and `harness-loop` CLI require the package on PATH.
  - No `pha/main.py` startup sequence change.

- **CI checkout depth for consensus gates**:
  - `.github/workflows/ci.yml`: `actions/checkout@v4` now uses `fetch-depth: 0`.
  - Reason: default depth=1 made `check_startup_consensus.py` / `check_harness_consensus.py`
    crash (`merge-base` + `HEAD~1` both unavailable), turning green selfchecks into red CI.
  - Scripts hardened: fall back to `GITHUB_BASE_SHA`, then soft-empty instead of traceback.
  - No `pha/main.py` startup sequence change.

---

## 2026-06-24

- **Stage 3F-γ / 3F-δ flags 接入**（无 `pha/main.py` 启动序列变更）:
  - `PHA_CLARIFY_INTENT_SCOPE=1` — holistic 单域/缺域 clarify（依赖 `PHA_GOAL_CLASSIFIER=1`）。
  - `PHA_SHADOW_ROUTING=1` — Shadow `goal_class` / `suggested_domains` telemetry（zero-adopt）。
  - 建议写入 `env-8788.sh` 与 E2E 脚本；默认仍为 `0`。
  - 自检: `pha_clarify_turns_selfcheck.py` H-δ8/δ9 · `pha_stage3f_delta_shadow_selfcheck.py`。

---

## 2026-06-17

- **Stage 3F-α 编码**（GoalClassifier + Harness Arbiter）:
  - Flag: `PHA_GOAL_CLASSIFIER=1`（默认 `0`）。
  - 模块: `pha/goal_classifier.py`, `pha/harness_arbiter.py`。
  - 自检: `scripts/pha_goal_arbiter_selfcheck.py`（H5–H8）。
  - 无 `pha/main.py` 启动序列变更。
- **Stage 3F 意图解析完整性 RFC 锁定**（文档-only）：
  - 新增 [`docs/stage3f-intent-resolution-completeness-rfc.md`](stage3f-intent-resolution-completeness-rfc.md)。
  - 规划 flag（默认均为 `0`，编码阶段接入）：`PHA_GOAL_CLASSIFIER` · `PHA_GOAL_SESSION_ANCHOR` · `PHA_CLARIFY_INTENT_SCOPE`。
  - 与 Stage 3C-α～ε 并存；不修改 `pha/main.py` 启动序列。

---

## 2026-06-08

- Established cross-agent consensus guardrails:
  - Added Cursor always-apply rule: `.cursor/rules/startup-consensus.mdc`
  - Added PR template: `.github/PULL_REQUEST_TEMPLATE/startup-consensus.md`
  - Added CI gate script: `scripts/ci/check_startup_consensus.py`
  - Wired CI to enforce startup changelog updates for startup-critical file changes
- Baseline references:
  - `docs/startup-availability-remediation-plan-2026-06-08.md`
  - `docs/startup-stability-2026-06-07.md`
- Implemented startup/availability fixes:
  - Startup slimming: moved heavy maintenance (`run_startup_data_audit`, `backfill_wearable_data_from_daily`) off critical startup path by default (async background thread in `pha/main.py`).
  - Removed duplicate startup backfill call from `store.hydrate_from_sqlite` (kept single maintenance entrypoint).
  - Replaced hardcoded hydrate reference date with `effective_query_reference_date()` in `pha/store.py`.
  - Added optional keepalive watchdog in `scripts/pha_restart_accept.sh` (default on; set `PHA_ENABLE_KEEPALIVE=0` to disable).
  - Added startup mode/env docs in `.env.example` (`PHA_RUN_MODE`, `PHA_STARTUP_MAINTENANCE_SYNC`, `PHA_ENABLE_KEEPALIVE`).
  - Replaced unstable shell watchdog with Python supervisor `scripts/pha_keepalive.py` for durable keepalive.
  - Removed deprecated macOS restart/stop launchers to enforce single startup path:
    - deleted `scripts/macos/PHA-Restart.command`
    - deleted `scripts/macos/PHA-Stop.command`
    - deleted `macos-apps/PHA-Restart.app/*` and `macos-apps/PHA-Stop.app/*`
  - Startup consensus gate updated to remove deleted launcher paths.

## 2026-06-09

- Fixed keepalive supervisor `scripts/pha_keepalive.py`:
  - **Bug**: `_spawn_app` used `Path(py).parents[1]` (`.venv`) as cwd — app could not restart reliably.
  - **Fix**: pass explicit project `ROOT` as first argument; spawn with `cwd=ROOT`.
  - Added heartbeat logging on spawn/restart.
- Unified stop path: new `scripts/pha_stop.sh` (replaces deleted PHA-Stop.command).
- `scripts/pha_restart_accept.sh`:
  - Calls `pha_stop.sh` before start (clean port/pid/watchdog).
  - Default `PHA_ENABLE_KEEPALIVE=1`; spawn via `scripts/pha_detach_spawn.py` (`start_new_session`) so parent shell exit does not kill PHA.
  - Long-lived foreground alternative: `scripts/macos/PHA-Serve.command`.
  - Post-acceptance verify app pid still alive.
- Removed obsolete `scripts/macos/create-pha-launcher-apps.sh` (Restart/Stop apps deleted; rebuild deferred until stable).
- Verified on :8788 (2026-06-09): `pha_restart_accept.sh` acceptance pass + 60s `/health` probe (app + watchdog alive throughout).

## 2026-06-10

- **Stage 3C 多轮连贯性优化 RFC 正式评审通过**：
  - `docs/stage3c-multi-turn-episodic-focus-rfc.md` → **Approved · 架构师锁定版（2026-06-10）**。
  - 范围：**仅单会话内 episodic**；跨 Session 长期记忆明确放入远期 Backlog，本波次禁止混入。
  - 分期路线：3C-α `HealthTurnResolver` + 黄金自检 → 3C-β 全 profile episodic → 3C-γ catalog → 3C-δ clarify → 3C-ε Composer。
  - 开工分支：`stage3c-alpha-health-turn-resolver`；flag `PHA_HEALTH_TURN_RESOLVER=1`。
- **Stage 3C-α implemented (HealthTurnResolver skeleton)**:
  - New: `pha/health_turn_resolver.py`, `pha/health_episodic_focus.py`, `pha/health_intent_catalog.py`, `pha/turn_scope_report.py`, `rules/health_intent_catalog.json`.
  - Selfcheck: `scripts/pha_health_turn_resolver_selfcheck.py` (H1–H4 + H-A1–A3 + turnScope report).
  - Not wired to `chat_service` yet (flag-gated integration in 3C-β).
  - Acceptance: `bash scripts/run_selfchecks.sh` → **29/29 PASS**.
- **Stage 3C-β implemented (episodic write-back + chat harness turnScope)**:
  - Extended `chat_session_turn_focus` schema (profile/metric/lab_years/wearable window/last turn digest).
  - New: `pha/health_session_focus_store.py` (`record_health_turn_focus`, `revive_health_session_focus`, `EPISODIC_BRIDGE`).
  - `chat_service.py`: gated by `PHA_EPISODIC_ALL_PROFILES=1`; `turnScope` via `PHA_HEALTH_TURN_RESOLVER=1` or episodic flag.
  - `harness_report` schema **v1.2** + `turnScope` / `episodic` nodes; Tier0 `EPISODIC_BRIDGE` slot.
  - Selfcheck: `scripts/pha_health_episodic_selfcheck.py`.
  - Rollback: unset flags; revert schema migration columns optional (old rows still readable).
  - Acceptance: `bash scripts/run_selfchecks.sh` → **30/30 PASS**.
- **Stage 3C-γ implemented (catalog episodic profile inheritance + supplement R1 routing)**:
  - Flag: `PHA_HEALTH_INTENT_CATALOG=1` (requires `PHA_HEALTH_TURN_RESOLVER=1` / episodic for full effect).
  - Extended `rules/health_intent_catalog.json` v1.1 (`weak_followup`, `supplement_families`).
  - `pha/health_intent_catalog.py`: `resolve_inherited_focus_profile`, `should_prefer_attachment_qa_over_wearable`, `explicit_profile_shift`.
  - `wearable_harness.py`: supplement R1 no longer loses to `wearable_screenshot_review` when catalog on.
  - `health_turn_resolver.py`: catalog-aware `_topic_continues` (weak follow-up inherit; block cross-profile revive).
  - `chat_service.py`: apply inherited `focus_profile` to `turnScope`; attachment episodic bridge when focus active.
  - Selfcheck: `scripts/pha_health_intent_catalog_selfcheck.py` (H-γ1–γ4).
  - Rollback: unset `PHA_HEALTH_INTENT_CATALOG`; prior 3C-β behavior unchanged.
- **Stage 3C-δ implemented (clarify SSE short-circuit + frontend chips)**:
  - Flag: `PHA_CLARIFY_TURNS=1` (requires `PHA_HEALTH_TURN_RESOLVER=1` for `needs_clarification` scope).
  - New: `pha/clarify_turns.py` (`build_clarify_sse_payload`, `resolve_scope_from_clarify_choice`, harness emit).
  - `harness_plan.py`: `build_clarify_turn_plan()` — profile `clarify`, slots `MASTER_ANCHOR`+`TASK`, Patient State forbidden.
  - `chat_service.py`: resolver 后 `needs_clarification` 短路 LLM，yield `clarify` + `done`; chip 回传 `clarify_choice_id` 覆盖 episodic。
  - `main.py` `ChatRequest.clarify_choice_id`; `app.js` clarify chips UI。
  - Selfcheck: `scripts/pha_clarify_turns_selfcheck.py` (H-δ1–δ6，对齐 RFC §6.4/§7/§8 H4)。
  - E2E: `scripts/pha_e2e_clarify_multiturn_report.py` + 浏览器 chips 真机验收（API + Console PASS 2026-06-10）。
  - Rollback: unset `PHA_CLARIFY_TURNS`; clarify 轮恢复为普通 LLM 路径（仍可能有 resolver 歧义标记但不短路）。
- **Stage 3C-ε implemented (GroundedAnswerComposer SSE v2)**:
  - Flag: `PHA_GROUNDED_COMPOSER=1`（非 clarify 短路轮；不改变 Harness forbidden）。
  - New: `pha/grounded_answer_composer.py` — `meta` / `fact_card` / `follow_ups`（数字 ⊆ Manifest）。
  - `chat_service.py`: LLM 前 yield meta+fact_card；done 前 yield follow_ups；catalog 二轮刷新 fact_card。
  - `app.js` + `index.html`: 数字卡 + 追问 chips UI。
  - Selfcheck: `scripts/pha_grounded_composer_selfcheck.py` (H-ε1–ε4)。
  - Rollback: unset `PHA_GROUNDED_COMPOSER`。
- **Stage 3C P0 E2E fixes (wearable fact_card + clarify chip routing)**:
  - P0-1: `chat_service.py` — `wearable_only` composer 轮单独 `build_numerics_manifest` 构建 `fact_card`（RFC §6.6 红线）。
  - P0-2: `harness_plan.py` — `build_turn_evidence_plan(..., turn_scope=...)` + `_plan_from_turn_scope`；clarify chip 后续强制 `lab_cross_year`（不再落 `lifestyle`）。
  - Selfcheck: H-δ7（chip→plan）、H-ε5（wearable manifest fact_card）；E2E clarify R2 profile 断言。
  - Acceptance (2026-06-10): API clarify PASS `lab_cross_year`；HRV API/浏览器 `fact_card` PASS；`run_selfchecks.sh` **33/33 PASS**。
  - Report: `docs/stage3c-composer-e2e-report-2026-06-10.md`。
- **P2-4 implemented (structured logging + narrower except on stability paths)**:
  - New: `pha/structured_log.py` (`format_context`, `log_warning`, `log_exception` with `event=` prefix).
  - Startup/import/keepalive: `main._run_startup_maintenance`, `_run_import_background`, Ollama probes → `httpx.HTTPError`/`OSError`/`TimeoutError`; `data_importer.run_import_from_path`; `store` SQLite persist/wipe; `chat_service` top-level SSE catch; `pha_keepalive._read_pid` → `(OSError, ValueError)`.
  - New selfcheck: `scripts/pha_structured_log_selfcheck.py` (manifest id `structured_log`).
  - Rollback: revert `structured_log.py` + call sites above; remove manifest entry.
  - Acceptance: `create_app()` OK; `bash scripts/run_selfchecks.sh` → **28/28 PASS**.
- **P2-1 / P2-2 implemented (dead code + version/port alignment)**:
  - P2-1: removed `main.py` delta/workout background helpers (`_run_delta_sync_background`, `_run_workout_backfill_background`, `_enqueue_*`); 410 endpoints unchanged.
  - P2-2: default `PHA_PORT` **8788** in `pha/main.py`, `pha_process_lib.sh`, `docker-compose.yml`, `docker/entrypoint.sh`; README/INSTALL build `pha-v2.3.32-full-import-only`; E2E scripts read `PHA_PORT`.
  - P2-3: already delivered in P0-4 (logs under `~/Library/Logs/pha`).
  - Rollback: restore deleted `main.py` helpers; revert port defaults to 8787.
  - Acceptance (2026-06-10): `create_app()` OK; `POST /data/sync-module/*` + `/data/backfill-workouts` → **410**; service on :8788 unchanged.
- **P1-4 implemented (selfcheck unified entry)**:
  - New: `scripts/selfcheck_manifest.json` (27 checks), `scripts/pha_selfcheck_runner.py` (summary table + `--list`/`--only`/`--json`).
  - `scripts/run_selfchecks.sh` delegates to runner; `tests/test_selfcheck_suite.py` pytest parametrization; `pyproject.toml` pytest config.
  - Added to manifest: `sqlite_connection`, `wearable_daily_aggregator`, `wearable_p15`, `harness_golden_run`, `wearable_golden_fixture`.
  - Fix: `pha_wearable_compare_table_selfcheck` May-30 workout row accepts `comparable_90d` when warehouse populated.
  - Rollback: restore old `run_selfchecks.sh` hardcoded list; remove manifest/runner/pytest test.
  - Acceptance (2026-06-10): `bash scripts/run_selfchecks.sh` → **27/27 PASS** with summary table.
- **P1-3 implemented (SQLite connection management)**:
  - New: `pha/sqlite_connection.py` — thread-local `connect_pooled`, dedicated `open_connection` for BatchWriters, `ensure_schema` one-shot guard.
  - `WearableDataBatchWriter` / `SleepSegmentBatchWriter` / `WorkoutSessionBatchWriter` no longer call `init_schema()` per instance; migrations run once per process.
  - Rollback: revert `sqlite_connection.py` + `sqlite_storage.py` + `workout_storage.py` connection changes.
  - Acceptance (2026-06-10): `pha_sqlite_connection_selfcheck.py` PASS (schema×1, 10-worker concurrent read/write/batch, no `database is locked`); `pha_restart_accept.sh` PASS.
- **P1-2 implemented (wearable daily rollup unification)**:
  - New: `pha/wearable_daily_aggregator.py` — shared metric accumulators, sleep segment rollup, `build_wearable_daily_summary`.
  - `data_importer._build_summaries`, `rebuild_wearable_daily_for_days`, `rebuild_daily_sleep_from_segments` delegate to aggregator (behavior preserved).
  - New selfcheck: `scripts/pha_wearable_daily_aggregator_selfcheck.py`.
  - Rollback: revert `wearable_daily_aggregator.py` + three call sites in `data_importer.py` / `sqlite_storage.py`.
  - Acceptance (2026-06-10): aggregator selfcheck PASS; `pha_sleep_stage_rollup_selfcheck.py` PASS.
- **P1-1 implemented (chat_service.py split)**:
  - New modules: `pha/chat_message_stack.py` (229 lines), `pha/chat_attachments.py` (621 lines), `pha/chat_agent_runtime.py` (325 lines).
  - `pha/chat_service.py` slimmed to SSE orchestration + backward-compat re-exports (1487 lines, was 2589).
  - Public API unchanged: `main.py` / `harness_report.py` / `perception_worker.py` still import from `pha.chat_service`.
  - Rollback: revert the four files above to pre-split versions.
  - Acceptance (2026-06-10): import smoke PASS; `pha_harness_report_v11_selfcheck.py` + `pha_stage3a_vision_selfcheck.py` PASS; `pha_restart_accept.sh` PASS; SSE `POST /api/chat` (`你好`, `qwen2.5:7b-instruct`) → `event: done` PASS.
- **P0-4 / P0-5 implemented (launchd + unified ops)**:
  - New: `scripts/pha_install_launchd.sh` (install|uninstall|status|verify), `scripts/macos/pha-launchd-wrapper.template.sh`.
  - Wrapper + env mirror under `~/Library/Application Support/pha/` (TCC-safe; WorkingDirectory not in Documents).
  - `pha_process_lib.sh`: launchd bootout/kickstart helpers; `pha_restart_accept.sh` uses `kickstart -k` when plist present; `pha_stop.sh` uses bootout.
  - `.env.example` default port 8788; docs unified in `docs/macos-pha-launcher.md`.
  - Rollback: `bash scripts/pha_install_launchd.sh uninstall` then `PHA_USE_LAUNCHD=0 bash scripts/pha_restart_accept.sh`.
  - Acceptance (2026-06-10): TCC verify PASS; `kill -9` → `/health` in 10s; restart ×3 PASS; stop → no resurrect.
- **P0-2 implemented (rebuild chain refactor)**:
  - `sync_wearable_data_from_daily`: delete only exact noon daily-mirror rows `(user_id, metric_type, timestamp)`; granular `heart_rate` etc. preserved.
  - `rebuild_daily_sleep_from_segments`: single-connection batch; `upsert_wearable_daily_batch` + safe sync (no full-table reload).
  - `rebuild_wearable_daily_for_days`: batch sleep segments via `query_sleep_segments_in_range`; shared `_sleep_metrics_from_segment_rows`.
  - `rebuild_workout_daily_rollup`: single-connection batch; upsert only affected days.
  - `compute_sleep_hours_union`: sweep-line O(n log n) (legacy kept as `_compute_sleep_hours_union_legacy` for regression).
  - Rollback: revert `pha/sqlite_storage.py`, `pha/sleep_aggregator.py`, `pha/workout_storage.py`.
  - Acceptance (`export 3.zip`, 2026-06-10): full import ~107s; `wearable_data` **2,839,227** (HR granular **976,700**); `wearable_daily` 3500; sweep vs legacy sleep union PASS.
- **P0-1 implemented (import GC/memory fix)**:
  - Removed in-memory `_seen_samples` dedup (`data_importer.py`); dedup relies on `INSERT OR IGNORE` + unique index.
  - Removed periodic `gc.collect()` from `WearableDataBatchWriter`, `SleepSegmentBatchWriter`, `WorkoutSessionBatchWriter`, `upsert_wearable_daily_batch`.
  - Non-whitelist `Record` types skipped before `_consume_record`; dropped `_count_records_in_zip` pre-scan; progress uses ZIP XML byte budget.
  - Rollback: revert `pha/data_importer.py`, `pha/sqlite_storage.py`, `pha/workout_storage.py`.
  - Acceptance (`export 3.zip`, 2026-06-10): 90s probe t1/t2/t3 = 929,947 → 1,979,942 → 2,829,915 rows (monotonic); RSS peak 472 MB; full import wall ~4 min exit 0. Post-rebuild `wearable_data` shrinks to ~14k (known P0-2 `sync_index_from_daily` issue — not P0-1).
- **P0-0 implemented (phase B — suicide-restart fix)**:
  - New `scripts/pha_process_lib.sh` (sourced helper, not a user entrypoint): pre-flight before kill, LISTEN-only port identity check, restart mutex lock, identity-verified stop, failure recovery trap.
  - `scripts/pha_restart_accept.sh`: pre-flight → lock → stop → spawn → health → acceptance; `trap` recovery (exit 70) if stop succeeded but health/acceptance failed; recovery reuses live keepalive when possible (no duplicate supervisors).
  - `scripts/pha_stop.sh`: delegates to identity-verified stop; orphan keepalive/app sweep for stale pidfiles.
  - Rollback: revert the three scripts above to pre-2026-06-10 versions; no DB/schema changes.
  - Fault-injection drills (2026-06-10): (1) bad PY preflight → old `/health` unchanged PASS; (2) `PHA_RESTART_WAIT_SECS=0` → recovery via existing keepalive, rc=70 PASS; (3) non-PHA LISTEN refused PASS; (4) concurrent restart → one lock-reject PASS; (5) 10× restart → all acceptance PASS (wall 8–12s incl. curls; stop→health gap ~3s).
- Audit + consensus (earlier same day, no code):
  - Killed stuck full-import process (pid 82831, 17h, GC-thrash deadlock; SQLite kept: 2.83M samples, `wearable_daily`=0 pending re-import).
  - Root-caused import hang: in-memory `_seen_samples` dedup set + periodic `gc.collect()` in batch writers (runtime stack sampling evidence).
  - Identified "suicide restart" defect: `pha_restart_accept.sh:34` unconditionally runs `pha_stop.sh` before any pre-flight check; startup failure leaves a dead window with no recovery. Port cleanup `lsof -ti | xargs kill -9` is identity-blind.
  - New execution source of truth: `docs/stability-remediation-plan-2026-06-10.md` (P0-0..P0-5 / P1 / P2 tasks, acceptance criteria, hard rules R1-R12, mandatory agent prompt).
  - Updated `.cursor/rules/startup-consensus.mdc`: ACK token bumped to `stability-plan-v2026-06-10`; task-ID claiming + fault-injection drill evidence now required for restart/stop changes.

## 2026-06-15 (skip_llm 架构扩展 · 真机回归)

- **Harness P1**（详见 `docs/harness-change-log.md` 2026-06-15）:
  - 纯数仓单指标：`try_warehouse_metric_focus_skip` → manifest 聚焦 skip_llm（~1–11s）。
  - 截图首轮：`build_compare_first_upload_answer` → CompareTable SSO + 运动建议模板，跳过 LLM 整段分析（OCR 仍 ~150–210s）。
  - 截图会话短追问：`build_catalog_followup_focus_answer` + `_EPISODIC_SHORT_METRIC_RE`。
- **E2E 验收**:
  - `scripts/pha_e2e_jun11_realdevice_multiturn.py` **PASS 7/7**（P2 并行 OCR：T1 **55.3s**，较 136s 降 ~60%）
  - `scripts/pha_e2e_browser_battery_20x.py` 精简 6 会话 **32/32 PASS**；完整 20× 复跑中
  - Report: `docs/stage3c-browser-e2e-report-2026-06-15.md`
- **P2 感知并行**：`PHA_PERCEPTION_PARALLEL=1`（默认）；`perceive_chat_attachment_paths`；`wearable_only` + `NUMERICS_MANIFEST` 槽位。
- **无启动路径变更**；`pha_restart_accept.sh` 行为不变。

## 2026-06-10 (wearable OCR / multi-turn)

- **Wearable screenshot OCR fixes** (`wearable_snapshot_v1.py`, `wearable_metric_candidates.py`):
  - 新增共享 **`normalize_wearable_ocr_text()`**（真机 Tesseract：`nr→hr`、`ins→ms`、`sem→bpm`、紧凑时长规范化）。
  - `TIME ASLEEP` 宽松窗口匹配；不再误读 **Awake 1 hr 55 min**（真值 **6 hr 32 min**）。
  - Workouts 页优先解析 **「You worked out on N days in the last 4 weeks」**（真值 **20 天**）。
  - 支持 **During your last workout, heart rate was 68–116** 文案。
- **多轮纠正** (`chat_service.py`, `wearable_compare_table_v1.py`, `chat_storage.py`):
  - 用户说「重新分析/核实/不对」时 **无需重传图**：从会话 OCR 重新 `remerge` 并写回 `parsed_json`。
  - 纠正轮 fallback 改为 **聚焦摘要**，避免每轮重复整段「根据您上传的 Apple Watch 截图…」。
- **单指标追问聚焦** (`wearable_compare_table_v1.py`, `grounded_answer_composer.py`, `chat_service.py`):
  - `infer_single_metric_focus_ids()`：窄意图推断（不做 broad wearable 扩展）。
  - 截图会话 follow-up（如「HRV 怎么样」）**skip_llm** 返回 CompareTable 单行摘要；数仓指标（如「最近步数」）走 Manifest 聚焦。
  - 纠正轮同样 skip_llm；`skip_llm` 后跳过 compare 审计覆写。
- Acceptance: `scripts/pha_stage3c_wearable_selfcheck.py` PASS；`scripts/run_selfchecks.sh` **33/33 PASS**；`scripts/pha_e2e_jun11_realdevice_multiturn.py` 6 轮真图 API E2E PASS；`pha_restart_accept.sh` PASS。

## 2026-06-09 (ingest)

- **取消增量同步产品入口**（Apple Health 无官方增量 export；全量 zip 扫描+水位线伪增量性价比差）：
  - `ingest_modules` 置空；`POST /data/sync-module/*` 与 `POST /data/backfill-workouts` 返回 410。
  - Dashboard 移除增量模块下拉，仅保留「开始导入」全量路径。
  - CLI：`scripts/pha_full_import_from_zip.py`；删除 `pha_delta_sync_from_zip.py`。
  - 后端 `delta_sync_from_zip` 代码保留未接线，供日后如需内部实验。
