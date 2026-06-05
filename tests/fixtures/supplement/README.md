# Supplement Label Fixtures（F 层 · CI / Benchmark）

> **非生产门禁**。本目录断言仅用于 `scripts/pha_perception_golden_*.py` 与未来 E2E。  
> 生产路径 `pha/label_ledger_v1.py` 的 `assess_confidence` **不得**引用具体品牌或成分名。  
> 规格：[`docs/stage3b-beta-vision-worker-spec.md`](../../../docs/stage3b-beta-vision-worker-spec.md) §1 · 附录 A

---

## 目录约定

| 路径 | 用途 |
|------|------|
| `now_ps_6800_6801/` | _blocking Fixture_：NOW 磷脂酰丝氨酸双面瓶（正面电商 + 背面 Supplement Facts） |
| `cgn_berberine_single/` | **P1** 单成分反例：不得因「缺 Choline/Inositol」拒答 |
| `synthetic_ocr/` | 纯 OCR 文本片段（无大图进 repo），供离线 merge 测试 |

图片：真机图 **脱敏后** 可放入对应子目录；默认 CI 使用 `scripts/` 内合成 OCR。

---

## Fixture：`now_ps_6800_6801`

**输入标识**：`IMG_6800`（正面）· `IMG_6801`（背面）

**CI 断言**（`tests/fixtures/supplement/golden_now_ps.py`）：

| 字段 | 期望 |
|------|------|
| `brand` | 含 `NOW` |
| `product_title` | 含 `Phosphatidyl Serine` |
| `ingredient_rows` | PS 100mg、Choline 100mg、Inositol **50** mg（名称允许 `from Choline Bitartrate`） |
| `attachment_count` | ≥ 2 |
| `parse_confidence` | `high`（在合成 OCR 金标管道上） |

**不应出现在生产代码**：上述字符串作为 `high` 的充分条件。

---

## Fixture：`cgn_berberine_single`（计划）

| 字段 | 期望 |
|------|------|
| `ingredient_rows.length` | 1 |
| `parse_confidence` | `high` |
| `reject_reasons` | **不得** 含 `missing_choline_row` / `missing_inositol_row` |

---

## 与 E2E 失败库关系

真机失败摘要：[`../e2e-failures-2026-05/README.md`](../e2e-failures-2026-05/README.md)  
修复验证：先 Fixture 绿，再真机复测（架构完善前 **不** 以真机为 blocking CI）。

---

## 运行

```bash
# 合成 OCR 金标（无真图）
python3 scripts/pha_perception_golden_6800_6801.py

# 真机脱敏图 E2E（无图 exit 2 SKIP）
python3 scripts/pha_e2e_attachment_label_real.py
# 见 docs/stage3b-e2e-real-label-fixture.md
```
