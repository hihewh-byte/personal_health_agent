-- =============================================================================
-- PHA SQLite Schema Reference
-- Database file: personal_health_agent/data/pha_storage.db
-- Generated from: pha/sqlite_storage.py, pha/medical_storage.py,
--                  pha/chat_storage.py, pha/medical_metric_catalog.py
--                  + live .schema dump (2026-05)
-- =============================================================================
-- PRAGMA foreign_keys = ON;  -- chat_messages declares FK; enforcement optional

-- -----------------------------------------------------------------------------
-- A. 可穿戴时序（Apple Health export.zip 导入管线）
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS wearable_daily (
    user_id                 TEXT NOT NULL,
    day                     TEXT NOT NULL,          -- YYYY-MM-DD
    steps                   INTEGER,
    resting_heart_rate_bpm  REAL,
    hrv_rmssd_ms            REAL,
    sleep_hours             REAL,
    awake_duration_hours    REAL,                 -- WASO 代理（日级）
    sleep_start_time        TEXT,                   -- ISO datetime
    sleep_deep_hours        REAL,                   -- 3d-δ-a
    sleep_rem_hours         REAL,
    workout_session_count   INTEGER,                -- 3d-δ-b
    workout_hr_min_bpm      REAL,
    workout_hr_max_bpm      REAL,
    updated_at              TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, day)
);

CREATE TABLE IF NOT EXISTS wearable_workout_sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL,
    day             TEXT NOT NULL,
    start_time      TEXT NOT NULL,
    end_time        TEXT NOT NULL,
    activity_type   TEXT,
    duration_sec    REAL,
    hr_min_bpm      REAL,
    hr_max_bpm      REAL,
    energy_kcal     REAL,
    sample_id       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wearable_user_day
    ON wearable_daily (user_id, day);

-- 原始指标样本（metric_type: steps | hrv | sleep | rhr | heart_rate）
CREATE TABLE IF NOT EXISTS wearable_data (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT NOT NULL,
    metric_type  TEXT NOT NULL,
    timestamp    TEXT NOT NULL,                     -- ISO / day-level noon
    value        REAL,
    sample_id    TEXT                               -- migration: 去重键
);
CREATE INDEX IF NOT EXISTS idx_user_metric_time
    ON wearable_data (user_id, metric_type, timestamp);
CREATE UNIQUE INDEX IF NOT EXISTS idx_wearable_data_sample
    ON wearable_data (user_id, sample_id);

-- Apple Health 睡眠分段（深睡/REM/清醒）
CREATE TABLE IF NOT EXISTS wearable_sleep_segments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    day         TEXT NOT NULL,
    start_time  TEXT NOT NULL,
    end_time    TEXT NOT NULL,
    source_name TEXT,
    sample_id   TEXT NOT NULL,
    is_awake    INTEGER NOT NULL DEFAULT 0          -- 0=sleep stage, 1=awake
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sleep_segment_sample
    ON wearable_sleep_segments (user_id, sample_id);
CREATE INDEX IF NOT EXISTS idx_sleep_segment_user_day
    ON wearable_sleep_segments (user_id, day);

-- 导入/sync 状态（每用户一行）
CREATE TABLE IF NOT EXISTS import_sync_state (
    user_id                    TEXT PRIMARY KEY,
    status                     TEXT NOT NULL DEFAULT 'never',
    last_sync_at               TEXT,
    last_record_time           TEXT,
    records_seen               INTEGER DEFAULT 0,
    days_written               INTEGER DEFAULT 0,
    wearable_samples_written   INTEGER DEFAULT 0,
    sleep_segments             INTEGER DEFAULT 0,
    steps_samples              INTEGER DEFAULT 0,
    message                    TEXT,
    updated_at                 TEXT NOT NULL DEFAULT (datetime('now'))
);

-- -----------------------------------------------------------------------------
-- B. 临床体检大账本（数字轨 + 叙事轨 + 资产元数据）
-- -----------------------------------------------------------------------------

-- 主表：化验数字指标（一行 = 一个 metric × 一次 report_date）
CREATE TABLE IF NOT EXISTS medical_reports (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          TEXT NOT NULL,
    report_date      TEXT NOT NULL,                 -- YYYY-MM-DD 或带 T 时间后缀
    metric_name      TEXT NOT NULL,
    value            REAL,
    unit             TEXT,
    reference_range  TEXT,
    is_abnormal      INTEGER NOT NULL DEFAULT 0,
    source_filename  TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    -- v1.6+ migration columns:
    metric_code      TEXT,
    name_en          TEXT,
    name_zh          TEXT
);
CREATE INDEX IF NOT EXISTS idx_medical_user_date
    ON medical_reports (user_id, report_date);
CREATE INDEX IF NOT EXISTS idx_medical_user_metric
    ON medical_reports (user_id, metric_name);
CREATE INDEX IF NOT EXISTS idx_medical_user_code
    ON medical_reports (user_id, metric_code);

-- 指标标准名目录（种子数据，非用户化验值）
CREATE TABLE IF NOT EXISTS medical_metrics (
    metric_code   TEXT PRIMARY KEY,
    name_en       TEXT NOT NULL,
    name_zh       TEXT NOT NULL,
    aliases_json  TEXT NOT NULL DEFAULT '[]'
);

-- 文字叙事轨（超声结论、诊断描述等非纯数字行）
CREATE TABLE IF NOT EXISTS health_narratives (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          TEXT NOT NULL,
    date             TEXT NOT NULL,                 -- YYYY-MM-DD
    hospital         TEXT,
    category         TEXT,
    content          TEXT NOT NULL,
    summary          TEXT,
    source_filename  TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_health_narratives_user_date
    ON health_narratives (user_id, date);

-- Vision/PDF 解析资产元数据（原始 JSON 预览）
CREATE TABLE IF NOT EXISTS health_report_assets (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          TEXT NOT NULL,
    report_date      TEXT NOT NULL,
    source_filename  TEXT,
    source_kind      TEXT NOT NULL DEFAULT 'pdf',   -- pdf | event_drawer | chat_ingest
    vision_model     TEXT,
    vision_raw_json    TEXT,
    metrics_preview  TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_health_assets_user
    ON health_report_assets (user_id, report_date DESC);

-- -----------------------------------------------------------------------------
-- C. 聊天会话（v1.7+ / v1.8.5 附件扩展）
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS chat_sessions (
    id          TEXT PRIMARY KEY,                   -- UUID
    user_id     TEXT NOT NULL,
    title       TEXT NOT NULL DEFAULT '新会话',
    created_at  TEXT NOT NULL,                      -- ISO UTC + Z
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user
    ON chat_sessions (user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS chat_messages (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       TEXT NOT NULL,
    role             TEXT NOT NULL,                 -- user | assistant
    content          TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    -- v1.8.5 migration (ALTER TABLE if missing):
    attachment_path  TEXT,                          -- 服务器绝对路径
    attachment_name  TEXT,                          -- 原始文件名
    parsed_json      TEXT,                          -- Vision 结构化 JSON
    ingested_at      TEXT,                          -- 归仓完成时间
    FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session
    ON chat_messages (session_id, id);

-- -----------------------------------------------------------------------------
-- D. 逻辑实体 ↔ 物理表映射（查询用）
-- -----------------------------------------------------------------------------

-- | 逻辑名              | 物理表              | 典型查询函数                          |
-- |---------------------|---------------------|---------------------------------------|
-- | health_metrics      | medical_reports     | query_metrics_in_range, insert_*      |
-- | health_narratives   | health_narratives   | query_narratives_in_range             |
-- | wearable 日聚合     | wearable_daily      | query_wearable_daily_range            |
-- | wearable 原始样本   | wearable_data       | query_wearable_hr_samples_in_range    |
-- | 睡眠分段            | wearable_sleep_segments | query_sleep_segments_in_range   |
-- | 聊天历史            | chat_messages       | list_messages, search_messages_*      |
-- | 指标目录            | medical_metrics     | seed_medical_metrics_table            |

-- -----------------------------------------------------------------------------
-- E. 不在本库中的 PHA 状态
-- -----------------------------------------------------------------------------

-- HealthEvent（手术/诊断/化验事件时间线）→ store.HealthStore 进程内存
-- ImportJobState（zip 导入进度）           → import_jobs 进程内存
-- 聊天附件二进制                          → storage/attachments/{user_id}/
