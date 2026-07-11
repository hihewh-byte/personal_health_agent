# ToB 交接文档 · Hospital IoT Ops Agent（HIO）

> **读者**：专门负责 ToB / HIO 的新 Agent（及人类负责人）  
> **作者视角**：PHA / harness-core 主线 Agent 的产品判断与资产交接  
> **日期**：2026-07-11  
> **状态**：产品讨论阶段 · **默认零生产代码**，直到有明确买方信号或负责人下令开工 PoC

本文是 **唯一推荐入口**。先读完再改产品文档或写代码。

---

## 0. 你要做什么（Mission）

把「院内物联网运维可信助手」从 **可讨论的产品定义** 推进到 **可售前、可验收、可 PoC** 的 ToB 交付物。

| 阶段 | 目标 | 产出 |
|------|------|------|
| **现在（产品）** | 收敛卖什么、不卖什么、怎么验 | 产品定义定稿、一页纸售前、PoC 范围单 |
| **有买方信号后（PoC）** | 一个科室、一套只读视图、对抗熔断可演示 | 私有 PoC 仓 + golden_run PASS |
| **签约后（交付）** | 嵌厂商控制台、租户隔离、合同验收脚本 | 部署包 + 验收报告 |

**你不是来做**：全院智慧大脑、医疗器械注册申报、改写 PHA 个人版、把 JWT/基站协议塞进 `harness_core`、公开推送 `tax_agent`。

---

## 1. 产品判断（交接方自己的定义与建议）

以下与 Gemini 售前话术 **互补**：Gemini 负责「卖相硬」；本节负责「别卖错、别做炸」。

### 1.1 一句话（建议对外统一口径）

> **HIO-A**：挂在医院已有物联网平台之上的 **可信对账层**——用自然语言问设备利用率/离线/告警/位置，**回答里的数字必须能点开对到只读库**；逼它撒谎会熔断。

不要主打「更聪明的 AI」；主打 **仪表盘之上、不许撒谎的对话与审计包**。

### 1.2 真正可卖的差异化（按强度排序）

1. **合同可验收的诚实性**（0-LLM golden + 对抗注入熔断）——竞品大屏/通用 Agent 几乎没有。  
2. **本轮证据卡（Trust Trace）**——管理层「传统软件安全感」的体感卖点。  
3. **级联设备树强路由**——把开放域幻觉从入口掐死（MVP 不做 NER 猜设备）。  
4. **0-Token 周报填槽（HIO-R）**——粘性与续费理由，不是首单唯一卖点。

### 1.3 SKU 建议（比 Gemini 更狠的收敛）

| SKU | 建议 | 理由 |
|-----|------|------|
| **HIO-A** | **唯一 P0 主卖** | 买方痛点清晰（设备科对账）；数据视图相对标准 |
| **HIO-D** | **P0 标配售前包** | 没有「逼它答 99%→熔断」现场秀，溢价讲不清 |
| **HIO-R** | **同发或首单捆绑** | 实现成本低（fast_lane），主任周会刚需 |
| **HIO-G** | **P1，有绿道数据质量再谈** | 节点时间戳脏则产品信誉先死 |
| **HIO-A+** | **慎承诺** | 要碰 HIS/RIS，集成与政治成本远高于 IoT 视图 |
| **HIO-N** | **路线图** | 垂直场景，不进首单 |

### 1.4 GTM 建议

* **渠道优先**：先卖给 **物联网厂商/集成商**（增值模块挂控制台），再随厂商进院；不要一上来直销三甲设备科（销售周期与关系网不匹配）。  
* **楔子客户画像**：已有资产定位 + 利用率/告警库、缺「可信对话」的厂商（参考画像：中科慈航类）。  
* **PoC 成功标准（建议写进内部纪律）**：  
  1 个科室树 + ≥2 张只读视图 + 3 条固定问法 100% 对账 + 1 次对抗熔断演示 ≤ 30 分钟讲完。  
  **不是**功能清单做完。

### 1.5 必须写进产品边界的「诚实限定」

* 「100% 对得上账」**仅适用于合同写明的封闭问法集合**（利用率、离线次数、告警 Top-N、末次位置等），不是任意闲聊。  
* 合规话术：**运维/质控管理辅助，非诊疗**；**不宣称**「一定免医疗器械注册 / 免一切审批」——法务审定前用审慎表述（见产品定义书）。  
* 数值审计分级（技术 RFC 已有）：硬数字 L-strict 必熔断；软叙述 L-soft 可放行——售前别把「绝对」说成玄学。

### 1.6 仓库与代码归属建议

| 内容 | 建议位置 | 原因 |
|------|----------|------|
| 产品/RFC 文档（现状） | `personal_health_agent/docs/rfcs/*` | 已与 Core 蓝图挂钩；可继续迭代文档 |
| **HIO 生产/PoC 代码** | **新建私有仓**或 `myAgents/hospital_iot_ops_agent/`（本地） | **不要**把医院厂商适配、样例库、售前 Demo 数据推进 PHA 公网仓 |
| 控制平面 | **消费** `packages/harness_core`（拷贝或 path 依赖） | Core 已在 PHA 公网 vendored；HIO 是 Domain Plugin |
| `tax_agent` | **只读参考孪生**；**禁止 push / 禁止拷贝隐私数据** | 本地财务隐私 |

### 1.7 建议你（ToB Agent）接下来优先做的事

1. **产品定稿**：在现有定义书上补「封闭问法清单 v0」+「非目标一页」+「PoC 范围单」（仍可零代码）。  
2. **一页纸售前**：给厂商 BD 的 PDF/Markdown（问题→方案→验收→集成四步）。  
3. **数据契约冻结**：把 `asset_daily` / `asset_alert_event` / `location_fix` 字段级最小集写成可给厂商 DBA 的表。  
4. **等买方信号再写代码**：有具体 DB 引擎、科室、iframe vs 独立站决策后再开 PoC。  
5. **不要**并行开 HIO-G/A+/N 实现；不要改 harness-core 协议「顺便加医院字段」。

---

## 2. 已有文档资产（必读顺序）

| 顺序 | 路径 | 用途 |
|------|------|------|
| 1 | **本文** `docs/rfcs/handoff-tob-hio-agent.md` | 任务边界与建议 |
| 2 | [`product-definition-hio-ops-agent.md`](product-definition-hio-ops-agent.md) | **对外产品定义书**（定位/用户/功能/交付/验收）v0.2 |
| 3 | [`rfc-hospital-iot-ops-agent.md`](rfc-hospital-iot-ops-agent.md) | **技术+产品 RFC** v0.2（SKU、Trust Trace、数据偏好、对标） |
| 4 | [`../harness-core-protocol-v0.md`](../harness-core-protocol-v0.md) | Core 协议：Plan → freeze → compose/fast_lane → post_audit |
| 5 | [`../harness-core-evolution-blueprint.md`](../harness-core-evolution-blueprint.md) §5 | toB 与 Core 的边界（Gateway/Ingest 在外） |
| 6 | [`rfc-enterprise-multi-tenant.md`](rfc-enterprise-multi-tenant.md) | 租户/Gateway 设计（HIO 鉴权外部化时对照） |
| 7 | [`rfc-device-ingestion-adapter.md`](rfc-device-ingestion-adapter.md) | 设备摄入 L0（HIO 优先 DB View，未必走此 RFC） |

**公网仓库**：https://github.com/hihewh-byte/personal_health_agent（默认 `main`，个人健康 Agent；HIO 仅 DOC）。

---

## 3. 可复用的技术资产（代码层）

### 3.1 harness-core（控制平面 · 直接复用）

| 位置 | 说明 |
|------|------|
| `personal_health_agent/packages/harness_core/` | **公网已 vendored**，权威交付形态 |
| `myAgents/harness_core/` | 工作区根下同构骨架（接口级） |

**模块**：`turn_plan` · `turn_fsm` · `integrity` · `plan_vs_actual`  
**脊柱**：`INIT → SESSION → PLAN → COMPOSE → POST_AUDIT → DONE`  
**铁律**：数字白名单 / allowlist；plan vs actual；可 0-LLM 干跑。

### 3.2 适配器范例（照着写 HIO adapter，勿抄业务）

| 路径 | 说明 |
|------|------|
| `personal_health_agent/pha/harness_core_adapter.py` | PHA 薄适配；公网可参考 |
| `tax_agent/harness_core_adapter.py` | 本地孪生；**只读参考，勿外泄** |
| `personal_health_agent/scripts/pha_harness_golden_run.py` | 绿墙范例：须能打出 `PASS harness_core adapter` |

### 3.3 架构口诀（实现时贴在 PR 描述里）

```text
Core Spine ← Adapter ← Domain Plugins（PHA / Tax / 未来 HIO）
Plan → freeze evidence → compose | fast_lane → post_audit

Gateway / RBAC / 设备协议 / 基站  —— 全部在 Core 外
```

### 3.4 明确「不可直接当 HIO 用」的东西

* PHA 个人健康对话、穿戴同步、临床相关话术  
* ASI（`agentic_sales_intelligence`）——已判定 **不** 作为 harness 完备前置；勿整仓改造当 HIO  
* `tax_agent` 业务数据与任何真实财务/身份信息  

---

## 4. 铁律（违反即停）

1. **默认零 HIO 生产代码**，直到负责人确认买方信号或明确「开工 PoC」。  
2. **禁止**向公网 push：医院真实资产、脱敏不彻底的样例、厂商密钥、`tax_agent`。  
3. **禁止**把 JWT/RBAC/射频协议做进 `harness_core`；HIO 只做 Domain Plugin + 只读工具。  
4. **禁止**对外承诺医疗器械注册结论或「免一切合规」。  
5. **MVP 禁止**开放域 NER 猜设备；无树选中则引导选树，不空跑。  
6. 改 Core 协议须回到 PHA 主线评审；HIO 侧优先 **适配**，不优先 **分叉 Core**。

---

## 5. 建议工作拆分（给 ToB Agent 的 backlog）

### Track P · 产品（当前默认）

- [ ] 封闭问法清单 v0（中英各 ≤10 条）+ 每条对应 SQL/视图字段  
- [ ] 一页纸售前（厂商 BD）  
- [ ] PoC 范围单：科室、视图、部署形态（iframe/独立）、成功标准  
- [ ] 合同验收条款草稿（对齐产品定义 §5）  
- [ ] 竞品话术卡：PerformanceBridge 类「仪表盘」vs 我们「诚实闸」

### Track T · 技术设计（仍可 DOC）

- [ ] 三视图字段级契约（DBA 可执行）  
- [ ] Trust Trace JSON schema 草案（证据卡 UI 绑定）  
- [ ] HIO Adapter 接口草图（对照 `pha/harness_core_adapter.py`）  
- [ ] `run_hio_a_golden_run.py` 用例表（含对抗注入）

### Track C · 代码（仅授权后）

- [ ] 私有仓脚手架 + path 依赖 harness_core  
- [ ] Fake/脱敏 SQLite 样例 + 级联树 + 对话 + 证据卡最小 UI  
- [ ] fast_lane 周报（HIO-R）  
- [ ] golden_run 绿墙 + 售前对抗脚本（HIO-D）

---

## 6. 与 PHA 主线的分工

| 角色 | 负责 |
|------|------|
| **PHA / Core 主线 Agent** | harness-core 协议稳定、PHA 公网质量、个人健康产品 |
| **ToB / HIO Agent（你）** | HIO 产品定义深化、售前材料、PoC/交付、厂商集成叙事 |
| **协作点** | HIO 若发现 Core 缺口 → 提协议变更需求给主线，**不要静默分叉** |

历史上下文（人类可读）：Cursor agent transcript 中关于 PHA Phase A closeout、Core vendoring、HIO RFC 的讨论；Issue #1 保持 OPEN 作 builder 征集，与 HIO 无强绑定。

---

## 7. 交接检查清单（新 Agent 启动时自检）

- [ ] 已读产品定义书 + 本交接 + RFC §0–2  
- [ ] 能用自己的话复述：卖的是「可信对账层」不是「更聪明 AI」  
- [ ] 知道代码默认停在 DOC；知道公网 PHA 与私有 HIO 仓边界  
- [ ] 知道可复用 `packages/harness_core` + adapter/golden 范例  
- [ ] 知道铁律：无 NER、无 Core 塞 Gateway、无 tax 外泄、无法务未审的器械承诺  

---

## 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v0.1 | 2026-07-11 | 首版：产品判断 + 资产地图 + ToB Agent backlog |
