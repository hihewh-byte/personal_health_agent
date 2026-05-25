# PHA P1.5 — 穿戴扩展指标

**Build**: `pha-v2.2.9-p1.5`

## 新增 canonical 指标（extension）

| ID | Apple Health | 日表列 | 单位 |
|----|--------------|--------|------|
| `spo2` | `OxygenSaturation` | `spo2_pct` | % |
| `respiratory_rate` | `RespiratoryRate` | `respiratory_rate_bpm` | breaths/min |
| `vo2max` | `VO2Max` | `vo2max_ml_kg_min` | mL/kg/min |
| `wrist_temp` | `AppleSleepingWristTemperature` / `BodyTemperature` | `wrist_temp_c` | °C |

## 热路径

1. `AppleHealthParser` 解析 → `wearable_daily` + `wearable_data`
2. `ALLOWED_METRICS` / `get_health_data` / `build_analytics_snapshot`
3. `infer_wearable_metrics` 中文/英文触发词
4. `Numerics Manifest` wearable 域均值条目
5. `wearable_bundle.schema.json` `extension_registry.enabled=true`

## 数据要求

**必须重新导入** `export.zip`，旧库仅有五件套列时新列为 NULL。

自测：

```bash
PYTHONPATH=. ./.venv/bin/python scripts/pha_wearable_p15_selfcheck.py
```
