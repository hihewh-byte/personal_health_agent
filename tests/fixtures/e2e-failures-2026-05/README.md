# E2E 失败样例摘要（2026-05 · 脱敏）

> 供 3A 回归 / 3B 金标对照。不含原始图片路径。

## DeepSeek-R1

- **状态**：显示「当前模型不支持工具调用…」（`model_no_tools` 路径）
- **定账**：品牌误为 ZENESSE；未稳定输出 Choline + Inositol 50mg
- **结构**：有「是什么/帮助」雏形，但依据扯到血脂/鱼油泛化
- **归属**：3B 感知 + 3A TASK/状态文案

## Qwen2.5 7B

- **首轮**：仅正面级信息（PS 100mg、ZENS 误读）
- **追问**：提及图1/图2，说明 merge 信息在上下文中曾出现但未进首轮 Tier0 定账
- **归属**：3B merge/Tier0 + 3A 双问结构

## Fixture 期望（F 层 · 仅 CI）

见 [`../supplement/README.md`](../supplement/README.md) · `now_ps_6800_6801`  
**非**生产门禁。架构完善后再跑 `scripts/pha_perception_golden_6800_6801.py`。
