# 云数据库迁移方案：AIDAP Supabase 引擎 → AIDAP PostgreSQL 引擎

> 状态：🟡 进行中（2026-09-17）— Step 1/2 代码侧完成，Step 3 已完成
> 目标：消除 Supabase 组件算力浪费 + 通过「算力空闲自动挂起」实现算力归零，
> 月成本从 ~270 元降至 ~5-20 元。数据仍 100% 在云，无本地持久化。

## 进度

| 步骤 | 状态 |
|---|---|
| Step 1: cloud_db.py 直连后端 | ✅ 完成（27 pg 测试全绿，含 SSL 连接测试，PostgREST 回归无损） |
| Step 2: agent 节流改造 | ✅ 完成（含发文门控修复 + meta_get_many 预取，模拟验证访问间隔 600s>300s） |
| Step 3: 新 workspace 创建 | ✅ 完成（API 自动创建，见下） |
| Step 4: schema 迁移 | ⏳ 待 pg8000 安装 + 连接验证 |
| Step 5: 数据迁移 | ⏳ 待 schema 就绪 |
| Step 6: 切换与验证 | ⏳ 待迁移完成 |
| Step 7: 清理旧 workspace | ⏳ 待验证稳定 |

### Step 3 已完成信息（2026-09-17，API 自动创建）

| 项 | 值 |
|---|---|
| WorkspaceId | `great-palm-10353999` |
| 引擎 | PostgreSQL 17（无组件算力） |
| 算力 | 0.25~2 CU（AutoScalingLimit） |
| 自动挂起 | `SuspendTimeoutSeconds=300`（已配置，ModifyComputeSettings） |
| BranchId | `br-charm-dodo-c1b882f3`（main, Ready） |
| ComputeId | `cp-ideal-warm-a425ed9a`（Primary, Active） |
| 数据库 | `aidb` |
| 账号 | `user_admin` |
| 主机 | `cp-ideal-warm-a425ed9a.pg7.aidap-global.cn-beijing.volces.com` |
| 连接串 | `postgresql://user_admin:<pwd>@cp-ideal-warm-a425ed9a.pg7.aidap-global.cn-beijing.volces.com/aidb?sslmode=require&channel_binding=require` |

> 密码含特殊字符 `>`（URL 编码 `%3E`），存 .env 时用 PGPASSWORD 明文即可，
> PGDATABASE_URL 需 URL 编码。连接要求 SSL（sslmode=require）+ channel_binding=require，
> cloud_db._pg_connect 已支持 ssl_context（pg8000 1.30+）。

> 创建方式：`scripts/aidap_workspace.py`（读 ~/.volcengine 登录缓存自动刷新 STS，
> 无需显式 AK/SK）。API Version=2025-10-01（volcengine-go-sdk 确认）。
> 账号曾欠费（40016 AccountInArrears）导致 CreateWorkspace 被拒，用户充值后创建成功。

> 注意：账号下另有 2 个 PostgreSQL workspace（`dandy-rice-22d38a8l` astock-db-pg、
> `deft-apple-6124db2g` x）疑似用户充值后自行创建，迁移完成后需确认是否清理。

## 一、背景与动机

### 1.1 现状成本（实测）

当前 workspace `jolly-ivy-dca877b0`（Supabase 引擎）两个算力：

| 算力 | 最小规格 | 说明 |
|---|---|---|
| Database compute | 0.25 CU | 实际在用（数据 KB 级） |
| Supabase 组件 compute | 0.5 CU | **从未活跃**（Auth/Storage/Realtime 全没用） |

计费：数据库算力 0.5 元/CU/小时 + 组件算力 0.5 元/CU/小时。
最小 0.75 CU × 0.5 元 × 720h ≈ **270 元/月**（24/7 Running）。其中组件算力是纯浪费。

### 1.2 核心矛盾

agent 每 300 秒 tick 一次，每次 5-8 次云库往返 → workspace 永远无法进入
「算力空闲自动挂起」（阈值最小 300 秒，默认 300 秒）→ 算力 24/7 计费。

### 1.3 方案选择

| 方案 | 月成本 | 迁移成本 | 是否治本 |
|---|---|---|---|
| **换 PostgreSQL 引擎 + 节流 + 自动挂起** | **~5-20 元** | 中 | ✅ 算力归零 |
| 换 PostgreSQL 引擎（不节流） | ~90 元 | 中 | ⚠️ 省 2/3，不归零 |
| 保持现状 | 270-360 元 | 无 | ❌ |

## 二、目标架构

```
┌─────────────────────────────────────────────────┐
│  上层（零改动）                                  │
│  agent/db.py  dashboard/db.py  api_daily.py     │
│  sync.py  scheduler_agent.py ...                │
└──────────────────────┬──────────────────────────┘
                       │ select/insert/update/upsert/delete
┌──────────────────────▼──────────────────────────┐
│  cloud_db.py（唯一访问层）                       │
│  PostgREST over HTTPS  →  直连 PostgreSQL        │
│  （保留对外 API 签名不变）                       │
└──────────────────────┬──────────────────────────┘
                       │ pg8000 直连（PGHOST/PGUSER/...）
┌──────────────────────▼──────────────────────────┐
│  AIDAP PostgreSQL 引擎 workspace（新）           │
│  0.25 CU 起步 + 算力空闲自动挂起（300s）         │
│  无 Supabase 组件算力                           │
└─────────────────────────────────────────────────┘
```

**关键设计**：cloud_db.py 是唯一访问层，上层全部走它的抽象 API。
只要 cloud_db.py 内部从 PostgREST 换成直连 SQL（pg8000），上层零改动。

## 三、实施步骤

### Step 1：cloud_db.py 改造（可独立完成，不依赖新 workspace）

- [ ] 新增直连后端：环境变量 `CLOUD_DB_BACKEND=pgdirect` 时走 pg8000
- [ ] 配置：`.env` 增加 `PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD`（或 `PGDATABASE_URL` 连接串）
- [ ] filters `[(col, op, val)]` 映射 SQL WHERE：`eq→=`、`neq→<>`、`gt→>`、`lt→<`、`gte→>=`、`lte→<=`、`is→IS NULL/NOT NULL`、`in→IN (...)`
- [ ] JSON 字段（sources/topics/todo_data）直连时读写 jsonb
- [ ] 保留 PostgREST 后端（`CLOUD_DB_BACKEND` 未设置时默认 postgrest）→ 平滑切换 + 可回滚
- [ ] 现有测试（mock `_req` 层）继续有效

### Step 2：agent 节流改造（数据全在云，无本地持久化）

- [ ] agent/db.py 的 meta_get/meta_get_many/activity_open 加**进程内内存缓存**（TTL ~240s，非持久化）
- [ ] 每 tick 必读的 4 个值（online/current_state/state_until/activity_open）命中缓存 → 每 4-5 分钟只 1 次云库往返
- [ ] meta_set 仍直写云库（强一致写路径不变）
- [ ] 进程重启即缓存清空，从云重新加载（符合"数据全在云"）

### Step 3：新 workspace 创建（用户操作 / 可选自动化）

**方式 A：自动化（推荐，脚本已备好）**——`scripts/aidap_workspace.py` 已实现
火山 OpenAPI 签名调用（纯 requests，无需 SDK），用户提供 AK/SK 后一键完成
创建 PostgreSQL workspace + 配置自动挂起 + 取连接串：

```bash
# 创建（PostgreSQL 17，算力 0.25~2 CU）
python scripts/aidap_workspace.py --ak <AK> --sk <SK> create --name astock-db-pg
# 配置自动挂起（300s 阈值）
python scripts/aidap_workspace.py --ak <AK> --sk <SK> suspend --workspace <ID> --timeout 300
# 拿连接串
python scripts/aidap_workspace.py --ak <AK> --sk <SK> conn --workspace <ID>
```

**方式 B：控制台手动创建（无需 AK/SK）**：

1. 登录火山引擎控制台 → 搜索「AI 原生数据库管理平台」（AIDAP）
2. 项目/地域选择：与现有 workspace 相同（华北 2 · 北京 / cn-beijing）
3. 创建 Workspace：
   - **引擎：PostgreSQL 17**（不是 Supabase 引擎！）
   - 名称：如 `astock-dashboard-pg`
4. 初始算力配置：
   - 算力扩展范围：**下限 0.25 CU，上限 2 CU**（比值 ≤ 8 合规）
   - **开启「算力空闲时自动挂起」**，等待时间设 **300 秒**（最小，也是默认）
5. 创建完成后，把以下信息告诉我（我用于连接与迁移）：
   - Workspace ID
   - **连接串**：控制台 → 该 Workspace → 连接信息/账号管理 → 复制
     `postgresql://<user>:<pass>@<host>.pg.aidap-global.cn-beijing.volces.com/<db>?sslmode=require`
     （或 PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD 分项）
   - 数据库管理账号与密码

> 备注：方式 A 的 API 已核实：CreateWorkspace（EngineType=PostgreSQL,
> EngineVersion=PostgreSQL_17, ComputeSettings.AutoScalingLimitMinCU/MaxCU）、
> ModifyComputeSettings（SuspendTimeoutSeconds 300~604800）、
> DescribeDBAccountConnection（拿连接串，仅 PostgreSQL/veDB MySQL 引擎支持）。
> 服务地址 aidap.cn-beijing.volcengineapi.com。AK/SK 从火山控制台
> 「访问控制 → API 访问密钥」获取。

### Step 4：schema 迁移

**建库 DDL 已备好**：`scripts/cloud_schema_pg.sql`（合并全部 cloud_schema_*.sql 为
单一文件，22 张权威表 + 13 索引，PostgreSQL 方言，幂等，已静态校验 PASS）。
kline_daily / backtest_nav 为本地可重建缓存（不在云库），无需迁移。

- [ ] 用户建好新 workspace 后，执行建库：
      `byted-supabase-cli db query -f scripts/cloud_schema_pg.sql`
      （或 pg8000 直连执行）
- [ ] 核对 22 张表齐全：`SELECT table_name FROM information_schema.tables
      WHERE table_schema='public' ORDER BY table_name;`
- [ ] 核对列/约束/索引与旧库一致（signal_tracking 25 字段、唯一索引 5 个）

### Step 5：数据迁移

- [ ] 从旧库导出全部表数据（JSON/CSV）
- [ ] 导入新库（保持 id/时间戳/JSON 字段原样）
- [ ] 校验行数与抽样数据

### Step 6：切换与验证

- [ ] 更新 `.env`：加 PG 连接串，`CLOUD_DB_BACKEND=pgdirect`
- [ ] 跑全量测试（含真实云库集成测试指向新库）
- [ ] Dashboard 页面加载验证
- [ ] agent 常驻验证（状态机/活动台账/调度正常）
- [ ] 监控一周账单确认成本达标

### Step 7：清理

- [ ] 确认稳定后，暂停/删除旧 Supabase workspace（释放组件算力）
- [ ] 移除 PostgREST 后端代码（如不再需要回滚）

## 四、成本预期

| 项 | 旧（Supabase） | 新（PostgreSQL + 节流 + 挂起） |
|---|---|---|
| 算力（24/7） | 0.75 CU ≈ 270 元 | 挂起时 0；唤醒 ~10-50 小时/月 |
| 唤醒算力 | — | ~0.25 CU × 0.5 元 × 30h ≈ **4 元** |
| 存储 | ~0.1 元 | ~0.1 元 |
| **月成本** | **~270 元** | **~5-20 元** |

## 五、风险与对策

| 风险 | 对策 |
|---|---|
| PostgreSQL 引擎连接串拿不到（历史 AccountPermissionDenied） | 已确认走火山 AK/SK 管理 API（DescribeDBAccountConnection），非 Supabase 控制台通道 |
| 节流引入状态读取延迟（最多 600s） | tick 本身 300s 周期；agent 本进程写后写穿透即时可见；他人写的值最多延迟 TTL |
| 迁移期间数据不一致 | 双后端并存，先验证新库再切换，保留回滚路径 |
| pg8000 未安装 | 加入 requirements.txt；沙箱网络受限装不了 → 用户环境 `pip install -r requirements.txt` |
| agent/dashboard 双进程读隔离 | dashboard/db.py 独立 meta 实现（无缓存），实时读不受 agent 节流影响 |
| like 过滤兼容（3 处生产调用） | 2026-09-17 已修：pgdirect 支持 like/ilike，PostgREST `*` 通配 → SQL `%`（api_daily 信号搜索 / dashboard prefix） |
| JSONB 字段双向处理 | 2026-09-17 已修：`_JSON_FIELDS` 扩展为 7 个（+log_entries/backtest_params/assets_json/status_history），serialize 与 row_dict 双端覆盖 |

## 六、验收标准

- [ ] cloud_db.py 直连后端全量测试通过（含 filters/JSON/upsert/批量）
- [ ] agent 节流改造后，全量测试通过（586 passed / 18 skipped 基线）
- [ ] 新 workspace 创建、schema + 数据迁移完成、读写验证通过
- [ ] Dashboard + agent 常驻切换后运行正常
- [ ] 一周账单确认月成本 ≤ 20 元
