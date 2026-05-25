# PHA Evidence Schema Registry (P1)

**契约版本**: `1.2.0`（P1.6 DCH 动态诱饵 + P1.5 穿戴扩展）  
**目录**: `personal_health_agent/storage/schemas/`（受信只读注册表）

## 用途

- 描述 Evidence Catalog 资产（`asset_id`、展示文案、7B 点单 instruction、fetch adapter、Manifest 域）。
- 由 `pha.universal_catalog_manager.UniversalCatalogManager` 启动时热加载。
- **不**在此目录写入可执行 SQL、动态表名或用户可控查询片段。

## 安全红线

1. **禁止裸 SQL 字符串**：`fetch` 仅允许 `adapter.module` + `adapter.callable` 符号反射。
2. **禁止动态表名拼接**：数据访问留在既有 Python Strategy（`lab_panel` / `wearable_ts`）。
3. **P1.5 已扩展 Ingestion**：`wearable_bundle.extension_registry` 中 `spo2` / `respiratory_rate` / `vo2max` / `wrist_temp` 已启用；需重新导入 Apple Health `export.zip` 后日表才有数据。

## 资产文件

| 文件 | asset_id | legacy_ids | asset_class |
|------|----------|------------|-------------|
| `lab_lipid_panel.schema.json` | `lab_lipid_panel` | `LDL_TABLE` | data |
| `wearable_bundle.schema.json` | `wearable_bundle` | `WEARABLE_90D` | data |
| `supplement_bg.schema.json` | `supplement_bg` | `SUPPLEMENT_BG` | context |

## A+ 意图路由（SchemaIntentRouter）

- 车道选择由 `intent.trigger_keywords` / `negative_keywords` 子串打分驱动；**Data 优先于 Context**。
- `supplement_bg` 为 Context 资产：`catalog.conditional=true`，仅在 combined 问且得分 ≥ 阈值时挂载 Catalog 第 3 行；纯血氧/睡眠分析句强制 2 行 Catalog。
- `intent.background_capture_keywords` 仅负责 DB 长期备忘录捕获，**不**参与车道拦截。

自测：`python scripts/pha_schema_intent_selfcheck.py`

## 双轨别名

旧 ID 经 `dual_track.resolve_map` 解析为 canonical `asset_id`，保留至 sprint 结束（契约 `accept_legacy_id_until`）。
