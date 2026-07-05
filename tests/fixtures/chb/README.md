# CHB Synthetic Fixtures（开源安全 · 无 PII）

> **用途**：演示 `USER_CONTEXT_BRIEF` 槽位结构；**禁止**将真实用户 CHB 提交进 Git。

## 文件

| 文件 | 说明 |
|------|------|
| `synthetic_brief_demo.json` | 完全虚构的 2 条 T0 事实（2099 演示日期 · Demo 前缀） |

## 本地启用演示 CHB（可选）

Fresh clone 默认 **无** `reports/chb/`  artifact — Harness 槽位留空，不阻塞 Turn。若需本地演示：

```bash
mkdir -p reports/chb/default
cp tests/fixtures/chb/synthetic_brief_demo.json \
   reports/chb/default/brief_c209d632963d6a6f.json
```

## 从自有数据生成（推荐）

导入 Apple Health / 化验数据后，离线编译：

```bash
PYTHONPATH=. python3 scripts/pha_chb_compile_all_users.py
```

产物写入 `reports/chb/{user_id}/`（已在 `.gitignore`，永不进库）。
