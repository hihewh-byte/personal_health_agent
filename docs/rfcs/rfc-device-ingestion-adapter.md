# RFC · Universal Device Ingestion Adapter

> **文件名**：`docs/rfcs/rfc-device-ingestion-adapter.md`  
> **版本**：v0.1（2026-07-05）  
> **状态**：📋 **Ratified（法理设计 · Future Work · 零生产代码）**  
> **上位法**：[`pha-pm-constitution.md`](../pha-pm-constitution.md) 第三条 · [`wearable-metric-registry-v1.md`](../wearable-metric-registry-v1.md) · [`wave4b-chronic-health-brief-spec.md`](../wave4b-chronic-health-brief-spec.md)

---

## 0. 核心诉求

> 允许 **任意第三方** 穿戴/物联网设备（MQTT · BLE · HTTP Webhook · 私有云 API）将原始遥测洗净为 PHA 标准 L1 日聚合行，**不修改** CompareTable · Harness FSM · P1 金标签字链。

**本 RFC 不含任何厂商名、topic 名或私有 payload 字段硬编码。**

---

## 1. 非目标

- 不新增第五类 `prov_type`（见 §4 双层标签）
- 不改 `wearable_daily` 表结构（新列走 Registry + Wave 3d-δ 流程）
- 不在 Chat Turn 内同步 ingest（不阻塞 FSM）
- 不进 PR blocking CI

---

## 2. 三层并网（复用既有 L0→L1→L2）

```text
L0  DeviceIngestAdapter（每种 transport · 一次性编码）
      parse_envelope → NormalizedSample[]
         │
L1  sqlite_storage.upsert_*（现有 API · user_id 分区）
         │
L2  CompareTable / CHB §Facts（Registry 驱动 · 零改算法）
         │
L3  LLM 叙事 + Audit（不变）
```

与 Apple Health `export.zip` 导入 **共用 L1 出口**；差异仅在 L0 解析器。

---

## 3. 统一接口契约

### 3.1 `DeviceIngestAdapter`（抽象）

| 成员 | 类型 | 说明 |
|------|------|------|
| `adapter_id` | `str` | 全局唯一，如 `generic_mqtt_v1` |
| `supported_transports` | `set[str]` | `mqtt` · `ble` · `http_webhook` |
| `parse_envelope(raw: bytes \| dict) → list[NormalizedSample]` | | 原始包 → 归一化样本 |
| `normalize_units(sample) → NormalizedSample` | | SI / registry 标准单位 |
| `dedupe_key(sample) → str` | | → `wearable_data.sample_id` |

### 3.2 `NormalizedSample`（Schema）

```json
{
  "user_id": "default",
  "metric_type": "hrv",
  "timestamp": "2099-01-01T12:00:00+00:00",
  "value": 55.0,
  "sample_id": "ingest:{adapter_id}:{device_id}:{metric}:{ts}",
  "source_vendor": "vendor_slug",
  "device_id": "opaque_device_ref",
  "raw_payload_ref": "optional_audit_blob_id"
}
```

**硬性要求：**

- `sample_id` 全局唯一、幂等（重复投递 → `INSERT OR IGNORE`）
- `user_id` 由 Ingest Gateway 解析（见 Enterprise RFC），Adapter **不** 自行猜测用户

### 3.3 Registry 挂接

在 [`wearable_metric_registry.json`](../../storage/registry/wearable_metric_registry.json) 的 `ingest_modules[]` 声明：

```json
{
  "module_id": "generic_mqtt_v1",
  "adapter": "pha.device_adapters.generic_mqtt.GenericMqttAdapter",
  "transport": "mqtt",
  "source_vendor": "vendor_slug",
  "registry_metrics": ["hrv_rmssd_ms", "resting_heart_rate_bpm"]
}
```

新增指标：**优先映射已有 `l1.field`**；_registry 无列时走 Wave 3d-δ 编码 PR，不在 Adapter 内私改表。

---

## 4. 双层标签法理（P1/P2 零改动关键）

| 层 | 字段 | 值 | 消费者 |
|----|------|-----|--------|
| **T0 法理层** | `prov_type` | 仍为 `wearable_import` | CompareTable · CHB · numerics audit |
| **溯源层** | `source_vendor` | 任意 slug（如设备生态名） | 审计 · 运维 · 版本回溯 |
| **行级键** | `ref_id` | `{vendor}_{device_id}_{metric_id}_{day}` | CHB §Facts `[ref:…]` |

**禁止** 为特定硬件新增 `prov_type` 第五类 — 否则 P1 `expectations_v1.json` · N-CHB 用例须全量重签。

---

## 5. 异步 Ingest 拓扑

```text
Device Cloud / BLE Gateway
    → Ingest Worker（独立进程 / Cron · 非 HTTP Turn）
        → Adapter.parse + normalize
        → upsert_wearable_daily_batch / WearableDataBatchWriter
        → [optional] pha_chb_compile_all_users.py（P2 已有）
    → Harness 下轮读最新 brief（4-β-2a 已有）
```

与 P2 环 B 自然衔接：L1 变更 → `ledger_hash` 变 → 离线 stale 重编译。

---

## 6. 单位归一化

RFC 实现阶段须在 Registry 侧维护 **vendor_field → metric_id → SI unit** 映射表（JSON，非 Python 硬编码）：

| registry `metric_id` | L1 列 | 标准单位 |
|----------------------|-------|----------|
| `hrv_rmssd_ms` | `hrv_rmssd_ms` | ms |
| `resting_heart_rate_bpm` | `resting_heart_rate_bpm` | bpm |
| `sleep_time_asleep` | `sleep_hours` | h |

Adapter 仅负责换算；CompareTable **不** 感知 vendor。

---

## 7. §X. SOTA Benchmarking

| 标杆 | PHA 采纳 |
|------|----------|
| **FHIR Observation** | 归一化样本 + provenance ref；不做首发 FHIR Server |
| **Home Assistant entity → recorder** | 异步写入时序仓；对话层不阻塞 |
| **Timescale / IoT pipelines** | `sample_id` 幂等；乱序 tolerant |

---

## 8. 验收场景（Future 编码阶段）

| ID | 场景 | 期望 |
|----|------|------|
| D-ING-1 | Mock MQTT envelope → Adapter | L1 行写入 · 正确 `sample_id` |
| D-ING-2 | 重复 envelope | 零 duplicate 行 |
| D-ING-3 | L1 变更 | P2 stale → 新 `brief_{hash}.json` |
| D-ING-4 | CompareTable 追问 HRV | 与 P1 E2 一致 · audit 无 violations |

---

## 9. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-07-05 | v0.1 Universal 版；双层标签；零厂商硬编码 |
