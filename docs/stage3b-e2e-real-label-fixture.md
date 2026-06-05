# Stage 3B — 真机脱敏标签 E2E（F 层）

> **版本**：v0.1（2026-05-26）  
> **脚本**：`scripts/pha_e2e_attachment_label_real.py`  
> **关联**：[`tests/fixtures/supplement/README.md`](../tests/fixtures/supplement/README.md) · [`stage3b-beta-vision-worker-spec.md`](stage3b-beta-vision-worker-spec.md)

---

## 1. 目的

在解除 `len(ocr)>=25` 补剂 OCR-only 短路后，用 **真实（脱敏）双面图** 验证：

- 每张图走 **Vision 主路径**（或显式 `ocr_only` 降级 + Telemetry）
- 双图 **服务端 merge** 与 `merge_trace`
- F 层金标：`golden_now_ps.py`（**非**生产 P 层门禁）

---

## 2. 脱敏与入库规范

| 规则 | 说明 |
|------|------|
| 路径 | `tests/fixtures/supplement/now_ps_6800_6801/IMG_6800.jpg` · `IMG_6801.jpg` |
| 禁止 | 未脱敏原图、含地址/电话/订单号的电商截图进 git |
| 允许 | 裁掉 UI 条、模糊订单区；保留 NOW + Supplement Facts 可读 |
| CI | 无图时脚本 **exit 2 SKIP**（不红）；有图时 **exit 0/1** |

环境变量：

- `PHA_E2E_LABEL_FRONT` — 正面图绝对路径  
- `PHA_E2E_LABEL_FACTS` — 成分表背面绝对路径  

---

## 3. Wave 1 门禁（阻塞 Active Recall AR-1）

| 级别 | 条件 | 对 AR 的影响 |
|------|------|----------------|
| **Green** | R1 真图/合成：`parse_confidence=high` + golden 成分通过 | 允许启动 AR-1 编码 |
| **Yellow** | `high` 未达但 `reject_reasons` 可解释 | AR-1 仅骨架；不断言伪造 |
| **Red** | 无图且合成金标也失败 | 先修 L0，不开 AR |

---

## 4. 通过线（F 层）

| 断言 | 来源 |
|------|------|
| `golden_match_now_ps_choline_inositol` | `tests/fixtures/supplement/golden_now_ps.py` |
| `LabelLedgerV1` 可解析 | Pydantic |
| Telemetry 打印 | `perception_channel`, `reject_reasons`, `attachment_count` |
| 目标 Telemetry（3B-β 后） | `media_route`, `document_family`, `family_confidence`（见 Spec §7.8） |

**说明**：真机图在 VLM 不稳定时可能 `parse_confidence=low`；脚本 **WARN 但 exit 0**，直至 3B-β 适配器落地后再改为 hard fail。

---

## 5. 运行

```bash
cd personal_health_agent
export PHA_E2E_LABEL_FRONT=/path/to/desensitized_front.jpg
export PHA_E2E_LABEL_FACTS=/path/to/desensitized_facts.jpg
python3 scripts/pha_e2e_attachment_label_real.py --json-out /tmp/pha_e2e_label.json
```

合成 OCR 回归（不依赖真图）：

```bash
python3 scripts/pha_perception_golden_6800_6801.py
```

---

## 6. 多轮验收（规划 · Active Recall · Wave 4）

| 轮次 | 用户意图 | 断言（F 层 / Harness DEBUG） |
|------|----------|------------------------------|
| R1 | 双图 + 是什么/帮助 | 定账 ≥3 成分；`parse_confidence` |
| R2 | 身体指标 / 改善 | `profile=attachment_episodic_bridge` |
| R3 | 药物交互（如与他汀同服） | `RECALL_FOCUS` 含 R1 资产；`l0_l3_asset_drift=false` |

详见 [`stage3c-active-recall-bridge.md`](stage3c-active-recall-bridge.md) §8。脚本 `pha_e2e_attachment_multiturn.py` **待 AR-5 实现**。

## 7. 与 3C 路由关系

附件焦点多轮路由见 [`stage3c-episodic-evidence-bridge.md`](stage3c-episodic-evidence-bridge.md)：`followup` 已并入 `episodic_bridge` 默认车道。
