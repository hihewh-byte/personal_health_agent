# P1 Golden Gate Fixtures（Offline F 层 · Public Gate 签字链）

> **状态**：P1-a~f — offline + HTTP Public Gate 签字链 ✅  
> **上位法**：[`docs/rfcs/stage3d-wearable-e2e-checklist.md`](../../../docs/rfcs/stage3d-wearable-e2e-checklist.md)（D-3d-2）  
> **编排器**：`scripts/pha_p1_golden_gate_test.py --tier f`  
> **默认**：**不**进入 PR `selfcheck_manifest.json`（Stage 4-0 分层 · Weekly/发布前签字）

---

## 目的

把既有 F 层资产（γ-1.1~1.3 · Compare build · numerics audit）与 D-3d-2 场景 ID（E1/E2/E3 · G-Compare · N-CHB）串成**机器可读断言矩阵**，供 offline 签字链复用。

**不**重写 `wearable_snapshot_v1` / `wearable_compare_table_v1` / `numerics_manifest` 逻辑；**只**编排 + 期望落盘。

---

## 目录

| 文件 | 用途 |
|------|------|
| `expectations_v1.json` | E1/E2/E3 硬性断言矩阵 + 绑定 F 层 fixture ID |
| `numerics_cases_chb.json` | N-CHB-* / N-ADV-* C 层 audit 用例（4-β 读侧延伸） |

---

## 车道法理（纠偏锚点）

| 场景 | **正确** profile | **禁止**误判 |
|------|------------------|--------------|
| C-1 / E1 六图 CompareTable | `wearable_screenshot_review` | ~~`attachment_grounded_review`~~ |
| C-2 / E2–E3 无图追问 | 同 session 复用 / 空 session 弱答 | 与 numerics C 层混为一谈 |

真机像素 **不进 repo**（宪法第四条）。HTTP 层（`--tier h`）使用环境变量指向本地资产目录。

---

## 断言 ID 约定

```text
E1-profile          profile == wearable_screenshot_review
E1-metrics          |wearable_metrics| >= 4
G-Compare-1         CompareTable 行数 >= compare_min_rows
G-Compare-2         对比数字 SSO 或 fallback_applied
E2-c                追问 KPI 不与 E1 矛盾
E3-a                空 session 禁止编造具体 HR/HRV
N-CHB-*             Interpretation 编造数字 → audit FAIL
N-ADV-*             Advisory 复述 vs 抽取新 numerics
```

---

## 运行

```bash
# Offline F 层（P1-c · PR 不 blocking）
PYTHONPATH=. python3 scripts/pha_p1_golden_gate_test.py --tier f

# HTTP 合成 E1（P1-d · 需 8788）
PYTHONPATH=. python3 scripts/pha_p1_golden_gate_test.py --tier h --assets synthetic

# HTTP 真机 E1/E2/E3（P1-e · 需 8788 + PHA_P1_ASSETS_DIR）
PHA_P1_ASSETS_DIR=~/.cursor/projects/.../assets \
  PYTHONPATH=. python3 scripts/pha_p1_golden_gate_test.py --tier h --assets real

# Public Gate 全量（P1-f · Weekly/发布前）
PYTHONPATH=. python3 scripts/pha_p1_golden_gate_test.py --tier all --assets real
```

报告落盘：`reports/p1_golden/p1_golden_gate_latest.json`（或 `PHA_E2E_REPORT_DIR`）。

### P1-d 合成 OCR 限制

PIL 程序化生成的 6-panel PNG **不触发** OCR screenshot 车道（metrics=0 · profile=`wearable_only`）。  
`--tier h --assets synthetic` 在 synthetic miss 时会 **自动 fallback** 到 `PHA_P1_ASSETS_DIR` 真机像素重跑 E1，以满足 `expectations_v1.json` 硬断言。  
纯 synthetic 无真机资产时 P1-d 会 FAIL — 这是已知 OCR 管线边界，非 product regression。

---

## 与既有 Fixture 关系

| 层级 | 路径 | 脚本 |
|------|------|------|
| γ OCR | `tests/fixtures/wearable/golden_ocr.json` | `pha_wearable_golden_fixture.py` |
| γ Compare | `tests/fixtures/wearable/golden_compare_table.json` | `pha_wearable_compare_table_selfcheck.py` |
| P1 期望 | `tests/fixtures/p1_golden/*.json` | `pha_p1_golden_gate_test.py` |

---

## 修订记录

| 日期 | 说明 |
|------|------|
| 2026-07-05 | P1-d/e/f：HTTP tier H · E1/E2/E3 真机签字 · synthetic OCR fallback 说明 |
| 2026-07-05 | P1-a/b 初版：expectations + numerics CHB 用例 |
