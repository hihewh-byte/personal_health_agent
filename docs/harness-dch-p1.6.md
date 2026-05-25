# PHA P1.6 — DCH 动态目录诱饵

**Build**: `pha-v2.2.10-p1.6`

## 机制

- **L0 Catalog**：仍 ≤5 条资产 ID；`when_zh` 由 `catalog_dch.build_dynamic_when_zh()` 按用户句命中 `trigger_keywords` 生成（最多 4 个中文诱饵）。
- **Reduce**：`infer_wearable_metrics()` 读 `wearable_bundle.schema.json` 的 `trigger_keywords`，不再在 `intent_gates.py` 硬编码指标名。
- **未命中**：Catalog 回退 `core_hint_keywords`；Reduce 回退 `metrics.core`。

## 自测

```bash
PYTHONPATH=. ./.venv/bin/python scripts/pha_dch_selfcheck.py
```
