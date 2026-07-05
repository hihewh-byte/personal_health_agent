# Stage 3C-ε Composer + 3C-δ 浏览器 E2E Report (2026-06-10)

- **Build**: `pha-v2.3.32-full-import-only`
- **Endpoint**: `http://127.0.0.1:8788`
- **Model**: `qwen2.5:7b-instruct`
- **Flags**: `PHA_CLARIFY_TURNS=1`, `PHA_GROUNDED_COMPOSER=1`, `PHA_HEALTH_TURN_RESOLVER=1`, `PHA_HEALTH_INTENT_CATALOG=1`, `PHA_EPISODIC_ALL_PROFILES=1`

## Summary

| 场景 | 通道 | 结果 | 备注 |
|------|------|------|------|
| Cδ R1 血脂澄清 chips | 浏览器 CDP | **PASS** | chips=`2023年`/`2025年` |
| Cδ R2 chip→续答 | API | **PASS** | `harness profile=lab_cross_year`（P0-2 修复后） |
| Cε HRV fact_card | API SSE | **PASS** | `HRV均值 33.03ms`（P0-1 修复后） |
| Cε HRV follow_ups | 浏览器 CDP | **PASS** | 3 chips + 1 fact_card line |
| 自检 33/33 | `run_selfchecks.sh` | **PASS** | H-δ7 + H-ε5 新增 |

## P0 修复验证

### P0-1 wearable fact_card

- **问题**：`wearable_only` 快车道无 `NUMERICS_MANIFEST` slot → composer 不出数字卡
- **修复**：`chat_service.py` 在 composer 阶段为 `wearable_only` 单独构建 manifest 并 emit `fact_card`
- **API**：`meta` + `fact_card`（1 item）+ `follow_ups×3`
- **浏览器**：`.pha-fact-card-line` = `HRV均值 33.03ms · 2026-03-14~2026-06-11`

### P0-2 clarify chip harness profile

- **问题**：R2 消息「2023年」被路由为 `lifestyle`
- **修复**：`build_turn_evidence_plan(..., turn_scope=...)` + `_plan_from_turn_scope` 强制 `lab_cross_year`
- **API E2E**：`OK R2 harness profile=lab_cross_year`

## 3C-ε 浏览器（Cε-A）

**输入**: `我最近的 HRV 怎么样？`

```json
{
  "factCard": ["HRV均值 33.03ms · 2026-03-14~2026-06-11"],
  "followUps": ["近90天 HRV 趋势如何？", "睡眠怎么样？", "步数呢？"]
}
```

## 自检

- `pha_clarify_turns_selfcheck.py` — H-δ1–δ7 **ALL PASS**
- `pha_grounded_composer_selfcheck.py` — H-ε1–ε5 **ALL PASS**
- `pha_e2e_clarify_multiturn_report.py` — **PASS**
- `run_selfchecks.sh` — **33/33 PASS**
