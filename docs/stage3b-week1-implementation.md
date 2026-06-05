# Stage 3B · Week 1 实施清单（P 层 · 无 β Worker）

> **状态**：🚧 编码中（2026-05-26）  
> **Spec**：[`stage3b-beta-vision-worker-spec.md`](stage3b-beta-vision-worker-spec.md) v0.1  
> **测试策略**：架构完善前 **暂停** Fixture/真机 blocking 测试；代码合入后以本清单勾选回归。

---

## Week 1 目标

将生产路径收敛到 **P 层 G1–G6**，剥离产品向 `reject_reasons`；引入 **layout 权重 merge** + `merge_trace`；Fixture 断言迁至 `tests/fixtures/`。

---

## 文档（已完成 / 进行中）

| 项 | 状态 |
|----|------|
| `stage3b-beta-vision-worker-spec.md` v0.1 | ✅ |
| `tests/fixtures/supplement/README.md` | ✅ |
| RFC §4.2 废止说明 → β Spec §5 | ✅ |
| `pha-architecture-evolution-v2.3.md` Fixture 措辞 | ✅ |
| 本清单 | ✅ |

---

## 代码（Week 1）

| 项 | 模块 | 状态 |
|----|------|------|
| G1–G6 `assess_confidence` | `label_ledger_v1.py` | ✅ |
| 移除 `missing_choline_row` / `missing_inositol_row` | `label_ledger_v1.py` | ✅ |
| 权重 merge + `merge_trace` | `perception_merge.py` | ✅ |
| `layout_hints_per_image` 输出 | `label_ledger_v1.py` | ✅ |
| Fixture 金标迁出 | `tests/fixtures/supplement/golden_now_ps.py` | ✅ |
| 拒答文案泛化 | `attachment_asset_qa.py` | ✅ |
| Telemetry `gate_triggered` / `merge_trace` | `telemetry_attachment.py` | ✅ |

---

## 回归结果（2026-05-26 · 已授权）

| 项 | 结果 |
|----|------|
| `scripts/pha_perception_golden_6800_6801.py` | ✅ OK（F 层 Fixture） |
| P 层 unit smoke（G 门禁 · 权重 merge） | ✅ |
| `scripts/pha_stage3a22_selfcheck.py` | ✅ |
| `scripts/pha_stage3a1_attachment_qa_selfcheck.py` | ✅ |
| `scripts/pha_stage3a2_selfcheck.py` | ✅ |
| `scripts/pha_restart_accept.sh` | ✅ build `week1-p-gate-merge-trace` |

**仍待**：真机 IMG_6800+6801 双图对话 E2E（需你本地 UI）。

---

## 暂停项

- ❌ 3B-β VLM Worker 编码（Week 3）

---

## Week 2+（未开始）

- 双图发送契约加固（前端 + `PHA_PERCEPTION_FORCE_SERVER_PARSE`）  
- 3B-β Vision Worker JSON  
- 泛化 Benchmark 集（附录 Spec §11.3）

---

## 回归闸门（架构完善后一次性打开）

1. `python scripts/pha_perception_golden_6800_6801.py`  
2. 真机 IMG_6800+6801 + Harness excerpt 审计  
3. Telemetry：`L0_L3_Alignment_Rate`、`gate_triggered` 分布
