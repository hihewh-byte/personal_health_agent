# Stage 3C — 附件焦点 × 全库证据桥接规格书

> **版本**：v0.1（2026-05-26）  
> **状态**：📋 Spec（待编码）  
> **依赖**：3A 会话焦点、`session_turn_focus`、Harness Plan  
> **分析**：[`stage3c-attachment-evidence-bridge-analysis.md`](stage3c-attachment-evidence-bridge-analysis.md)

---

## 1. 问题

| 现象 | 根因 |
|------|------|
| R1 只谈补剂、不引 HRV/LDL | `attachment_asset_qa` **forbidden** Patient State / WEARABLE / CATALOG |
| R2「身体指标」称缺乏基线 | 跌落到 `lifestyle` + Patient State 未注入 / 空表 + 全量医学 Soul |

**目标**：  
- R1：在 **不展开大盘** 前提下，让 LLM **知道** 库内有哪些数据、可引用什么。  
- R2：在 **会话焦点仍 active** 时，用 **桥接 Profile** 注入与问句相关的化验/穿戴切片。

---

## 2. 证据范围枚举 `evidence_scope`

| 值 | R1 附件 initial | 说明 |
|----|-----------------|------|
| `focus_only` | 可选 | 仅 ATTACHMENT_LABEL + 窄 SUPPLEMENT_BG（现状） |
| `focus_plus_availability` | **推荐默认** | + `DATA_AVAILABILITY` 块（2–6 行） |
| `focus_plus_lipid` | 用户问血脂时 | + `LDL_AUTHORITY` 或血脂快照（已有 lipid_bridge 部分覆盖） |
| `focus_plus_wearable` | 用户问 HRV/运动时 | + `WEARABLE_90D_SUMMARY` 短摘要 |

**禁止**：在 `focus_only` 下偷偷塞全量 Patient State（破坏 3A 焦点）。

---

## 3. 新槽位 `DATA_AVAILABILITY`（C 层 · 0ms）

**生产者**：`build_data_availability_block(user_id, question_hint)` — 只读 SQLite 计数/最近日期，不调 LLM。

**示例输出**：

```text
【数据可用性 · 本轮只披露下列，勿声称「系统无任何数据」】
- 化验账本：有；最近报告日 2025-11-12；含 LDL/HDL/甘油三酯 等（未注入全表，点名可展开）
- 穿戴近90日：有；HRV 均值约 33 ms（n=12 天）；步数/睡眠 有摘要
- 本轮焦点：上传标签资产（磷脂酰丝氨酸类）；非化验单
```

**规则**：

- 库内 **无** 则写「无」，禁止 LLM 编造  
- 有但未注入 Tier0 时，写「有，本轮未展开；若需分析请明确指标」  
- 不得含具体品牌/成分硬编码

---

## 4. Profile：`attachment_episodic_bridge`

### 4.1 触发条件（同时满足）

1. `session_focus_active == true`（`chat_session_turn_focus`）  
2. 本条 **非** `initial`（当轮带新附件且命中双问句式）  
3. 本条 **非** `lipid_bridge`（血脂专问仍走 lipid profile + LDL 快照）  
4. **默认车道**：焦点内任意非空短句（≤320 字）→ `episodic_bridge`（**已废止** followup 短语表路由）  

**C 层 TASK**：`build_episodic_bridge_task(msg)` — 统一 `ATTACHMENT_EPISODIC_BRIDGE_TASK`；仅当 `len(msg)≤120` 且非 lipid 时追加结构型 `EPISODIC_BRIDGE_NARROW_ADDENDUM`（非 L0 正则）。

### 4.2 槽位

**Tier0**：

- `MASTER_ANCHOR`  
- `ATTACHMENT_LABEL`（会话焦点定账摘要，来自 `session_turn_focus`）  
- `DATA_AVAILABILITY`  
- `TASK`（桥接 TASK，见 §5）  
- `NUMERICS_MANIFEST`（紧凑）  
- `WEARABLE_90D_SUMMARY`（仅当问句含 HRV/睡眠/活动或 COMBINED 意图）

**Tier1**：

- `PATIENT_STATE_LAB` 或 **证据切片**（`build_patient_state_evidence_slice`，按问句裁剪）  
- `SUPPLEMENT_BG`（**窄**，禁止整段方案复述）

**Forbidden**：

- 全量 `DOSSIER`（除非用户 explicit 跨年对比）  
- `GET_HEALTH_DATA` 工具（首版仍 C 层预取，防 7B 工具循环）

**Soul**：`PHA_ATTACHMENT_SOUL_MINIMAL` + 短桥接 addendum，**禁止**三步看诊法标题。

### 4.3 与 `attachment_asset_qa` 关系

| 轮次 | Profile |
|------|---------|
| R1「是什么+帮助」+ 新附件 | `attachment_asset_qa` + `evidence_scope=focus_plus_availability` |
| R2「能提高哪些指标」+ 焦点 active | `attachment_episodic_bridge` |
| R2 焦点过期 | `combined_review` 或 `wearable_only` / `lab_cross_year` 按 Schema |

---

## 5. TASK 宪法（桥接轮）

```text
【本轮任务 · 焦点资产 × 指标桥接】
1) 用 1 句确认仍在讨论「会话焦点资产」（来自 ATTACHMENT_LABEL）。
2) 回答用户关于「身体指标/改善」的问题：
   - 仅引用 DATA_AVAILABILITY、Patient State、Manifest、穿戴摘要中已出现的数据；
   - 每条数字须对应可见行；无则写「库内暂无该指标」而非「缺乏基线」套话；
   - 说明指标与「焦点补剂」的关联强度（有证据/证据弱/无关）— 允许结论「无关可不讨论」。
3) 禁止：三步看诊法标题；复述完整补剂时间表；将历史 LDL 改善归功于焦点补剂。
```

---

## 6. 会话焦点 TTL

| 参数 | 默认 | 说明 |
|------|------|------|
| `focus_turns_remaining` | 3 | 含 initial 后 2 轮 follow-up/bridge |
| 续期 | 用户命中 focus_tokens | 同 3A.2 |

焦点定账存 `focus_summary`（`label_ledger` 截断），**非** 每轮重跑 Vision。

---

## 7. Telemetry

| 字段 | 说明 |
|------|------|
| `evidence_scope` | focus_plus_* |
| `profile` | attachment_episodic_bridge |
| `data_availability_nonempty` | bool |
| `patient_state_rows` | int |
| `bridge_reason` | focus_active \| intent_metric |

---

## 8. 验收

- [ ] R1：Harness 含 `DATA_AVAILABILITY`；无 PATIENT_STATE 全表  
- [ ] R2：profile=`attachment_episodic_bridge`；无「纵向趋势对账」标题  
- [ ] R2：若 DB 有 LDL/HRV，回答须引用或明确「库内暂无」  
- [ ] 日志 `forbidden` 不 block PATIENT_STATE on bridge profile  
- [ ] R3（Active Recall）：见 [`stage3c-active-recall-bridge.md`](stage3c-active-recall-bridge.md) §8 — `RECALL_FOCUS` 含定账资产；交互问句不漂移品牌/成分  

---

## 9. Active Recall（L2.5）

焦点 TTL 解决 **车道**；**咬合力** 由 Active Recall 解决：[`stage3c-active-recall-bridge.md`](stage3c-active-recall-bridge.md)。

---

## 9. 非目标

- 不替代 3B-β Vision  
- 不在中台写 `if statin` / `if soy`（K 层 Catalog）
