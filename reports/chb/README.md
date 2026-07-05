# CHB Runtime Artifacts（本地 · 不进 Git）

此目录存放 **用户运行时** 生成的 Chronic Health Brief JSON（`brief_{ledger_hash}.json`）。

- **已加入 `.gitignore`** — 禁止提交真实健康数据。
- Fresh clone 为空；可选复制 [`tests/fixtures/chb/synthetic_brief_demo.json`](../../tests/fixtures/chb/synthetic_brief_demo.json) 作演示。
- 有本地数据后运行：`PYTHONPATH=. python3 scripts/pha_chb_compile_all_users.py`
