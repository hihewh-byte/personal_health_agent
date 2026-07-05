# RFC · Enterprise Multi-Tenant Gateway

> **文件名**：`docs/rfcs/rfc-enterprise-multi-tenant.md`  
> **版本**：v0.1（2026-07-05）  
> **状态**：📋 **Ratified（法理设计 · Future Work · 零生产代码）**  
> **上位法**：[`pha-pm-constitution.md`](../pha-pm-constitution.md) · [`wave4a-open-source-readiness-spec.md`](../wave4a-open-source-readiness-spec.md) · [`rfc-stage4b-personalization-flywheel.md`](rfc-stage4b-personalization-flywheel.md)

---

## 0. 核心诉求

> 在 **不修改** PHA Core FSM · Harness Profile 拓扑 · CompareTable 算法的前提下，支持「医院/科室 → 医生 → 多病人」的 B 端并发访问与鉴权隔离。

**个人开源版（Wave 4a） deliberately 不包含本 RFC 的实现。**

---

## 1. 非目标

- 不修改 `orchestrate_chat_turn_events` 签名或 Profile registry
- 不在 Phase 1 改 SQLite 主键或加 `tenant_id` 列
- 不将 RBAC 逻辑嵌入 Harness / LLM prompt
- 不要求 P1 金标 / PR CI 重签

---

## 2. 为什么 FSM 可以 100% 零改

PHA Core  today 只认 **`effective_user_id`**：

```text
orchestrate_chat_turn_events(user_id=…)
sqlite: WHERE user_id = ?
reports/chb/{user_id}/
chat_sessions: user_id column
```

Enterprise Gateway 在 HTTP 边界完成：

```text
(JWT tenant_id, actor_id, patient_id) → effective_user_id
```

Core 收到的仍是单一字符串 `user_id` — FSM · Tier0 · CompareTable · CHB 读路径 **物理不变**。

---

## 3. Phase 1：复合 user_id 命名空间（推荐首发）

### 3.1 格式

```text
effective_user_id = "{tenant_id}:{patient_id}"
```

| 组件 | 规则 |
|------|------|
| `tenant_id` | 科室/医院 slug；`[a-z0-9_-]{1,64}` |
| `patient_id` | 院内患者 ID；同上 |
| 分隔符 | 单字符 `:`；**禁止** patient_id 含未转义 `:` |

### 3.2 与现有存储的兼容性

| 子系统 | Phase 1 行为 |
|--------|--------------|
| SQLite `wearable_daily` PK `(user_id, day)` | ✅ 复合串作为 user_id |
| `reports/chb/{user_id}/` | ✅ 目录名含 `:`（文件系统允许） |
| P2 `pha_chb_compile_all_users.py` | ✅ 遍历目录名即可 |
| 个人版 `default` | ✅ 无冒号 · 向后兼容 |

**无需** Phase 1 迁移脚本。

### 3.3 Phase 2+（规模化，Future）

| 阶段 | 存储演进 |
|------|----------|
| Phase 2 | 路径规范 `tenants/{tid}/patients/{pid}/`（CHB · 附件 · 导出） |
| Phase 3 | SQLite 加 `tenant_id` 列 + 复合索引；查询层 filter |
| Phase 4 | 可选 per-tenant DB 分片 |

RFC 批准 Phase 1 为 Enterprise **最低可编码** 切口；Phase 2+ 单独立项。

---

## 4. Enterprise Gateway 职责

```text
Client (Clinician App / EHR iframe)
    │
    ▼
Enterprise Gateway (:8443 或 reverse proxy)
    ├── JWT 校验（iss / exp / aud）
    ├── 解析 claims: tenant_id, sub=actor_id, roles[]
    ├── RBAC: care_relationships 表 → 是否可访问 patient_id
    ├── 构造 effective_user_id = f"{tenant_id}:{patient_id}"
    ├── 跨租户/越权 → 403 + structured audit NDJSON
    └── 转发 → PHA Core (:8788) 现有 REST/SSE API
    │
    ▼
PHA Core（无 tenant 概念 · 信任 Gateway 注入的 user_id）
```

### 4.1 Gateway **不做**

- 不调用 LLM · 不组装 Harness slot
- 不读写 SQLite 直接（Phase 1 全部转发 Core）
- 不修改 chat turn 路由

### 4.2 Gateway **必须做**

- 生产环境 **禁止** 静默 fallback 到 `user_id=default`
- 每次转发附带 `X-PHA-Actor-Id` · `X-PHA-Tenant-Id`（审计；Core 可选记录）
- 结构化越权日志（不含 PHI 正文）

---

## 5. 最低 RBAC 模型

### 5.1 角色

| 角色 | 权限 |
|------|------|
| `tenant_admin` | 管理 tenant 成员 · 审计只读 |
| `doctor` | 绑定 patient 的 chat / 数据读 / 报告导出 |
| `patient` | 仅 `effective_user_id` 对应自己（C 端） |
| `device_ingest` | 仅 Ingest API 写 wearable；无 chat |

### 5.2 关系表（Gateway DB · 非 PHA Core SQLite）

```text
tenant_members(tenant_id, actor_id, role, created_at)
care_relationships(tenant_id, doctor_id, patient_id, status, granted_at)
device_bindings(tenant_id, device_id, patient_id, bound_at)
```

Device Ingest 须查 `device_bindings` 解析 `patient_id` → `effective_user_id`（见 Device RFC §3.2）。

---

## 6. 安全红线

| ID | 红线 |
|----|------|
| MT-1 | Gateway 是唯一 tenant 解析点；Core API 不得接受裸 `tenant_id` Query 绕过 RBAC |
| MT-2 | 个人开源版默认 `127.0.0.1` + 无鉴权 — **与 Enterprise 部署不得混用同一公网端口** |
| MT-3 | 跨 tenant 访问 attempt → 403 · 日志不得含化验数值/聊天正文 |
| MT-4 | JWT 短 TTL + refresh；禁止 long-lived token 嵌入前端 |

---

## 7. 高并发与内存沙盒

- Gateway：**无状态**；会话 stickiness 不需要
- PHA Core：现有 `user_id` 分区已足够；SSE session 按 `session_id` + `user_id` 双键校验
- **禁止** thread-global 当前 tenant；Request-scoped context only
- 水平扩展：Gateway 多副本 + Core 多 worker；共享 SQLite **不** 作为 Enterprise Phase 1 目标（Phase 3+ 外置 PG）

---

## 8. §X. SOTA Benchmarking

| 标杆 | PHA 采纳 |
|------|----------|
| **SMART on FHIR** | Gateway 鉴权 + 资源 scoped 到 patient |
| **Keycloak Organizations** | tenant hierarchy · role mapping |
| **Supabase RLS** | Phase 3 可选 DB 层 filter；Phase 1 用命名空间 |

---

## 9. 验收场景（Future 编码阶段）

| ID | 场景 | 期望 |
|----|------|------|
| MT-E1 | Doctor A 访问 Patient X（有 care_relationship） | 200 · 正确 effective_user_id |
| MT-E2 | Doctor A 访问 Patient Y（无关系） | 403 · audit log |
| MT-E3 | Tenant T1 doctor 访问 Tenant T2 patient | 403 |
| MT-E4 | 同 effective_user_id 对话 | FSM profile 与 personal 版一致 |
| MT-E5 | Device ingest 写 wearable | 行落在 `{tid}:{pid}` 分区 |

---

## 10. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-07-05 | v0.1 Universal 版；Phase 1 复合 user_id；FSM 零改论证 |
