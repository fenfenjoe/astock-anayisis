# 部署与多机一致性（Deployment & Multi-Machine Consistency）

> 最后更新：2026-08-28
> 适用范围：本仓库（A股投研 + 拟人 Agent「小满」）

## 1. 服务拓扑（3 服务 + dsh 依赖）

```
┌─────────────┐     ┌──────────────────┐     ┌──────────────┐
│  dashboard  │     │  agent（小满）    │     │  openviking  │
│  FastAPI    │     │  Python 编排壳    │     │  记忆服务     │
│  :8000      │◄────┤  :常驻 tick       │     │  :1933       │
│  聊天/文章/  │     │  RSS采集/发文/动态 │     │  语义记忆     │
│  报告调度    │     │  └→ dsh_runner   │     │  (embedding) │
└─────────────┘     └──────┬───────────┘     └──────────────┘
                           │ dsh --profile xiaoman（Agent 2 大脑）
                           ▼
                   ┌─────────────┐
                   │  dsh CLI    │  ~/.dsh（DSH_HOME，机器本地）
                   │  + skills   │  仓库 .dsh/skills + profiles（git 同步）
                   └─────────────┘
```

- **dashboard**：web 界面 + API + 报告/信号调度（dsh headless）
- **agent**：小满常驻进程（Python 壳，LLM 全走 `dsh --profile xiaoman`）
- **openviking**：小满的语义记忆后端（独立服务；火山 embedding，配额 9/4 重置后可用）

## 2. 多机一致性机制（配置随仓库走）

| 内容 | 机制 |
|---|---|
| 技能库 | `.dsh/skills/**` 入 git（`.gitignore` 白名单：`.dsh/*` + `!.dsh/skills/**`） |
| dsh profiles | `.dsh/profiles/xiaoman` 入 git（唯一活 profile）；`sync_dsh.ps1` 同步到 `~/.dsh/profiles` |
| 凭据 | `.dsh/.credentials.example.yaml` 模板入 git；每机复制为 `.credentials.yaml` 填真实 key（忽略） |
| 版本锁定 | dsh `0.1.0-rc.6`（npm）、openviking `0.4.x`（pip）；`sync_dsh.ps1` 校验并提示 |
| 其他凭据 | `.env*`、`data/.secret_key`、`notify_config.json`、`~/.openviking/ov.conf` 均不入 git |

## 3. 新机器部署（Onboarding）

### 本机（Windows）

```powershell
# 1. 拉代码
git clone https://github.com/fenfenjoe/astock-anayisis.git && cd astock-anayisis

# 2. 安装运行时
npm i -g @deepseek-ai/dsh@0.1.0-rc.6
python -m pip install --user --upgrade openviking==0.4.16
python -m pip install -r etf-strategies/requirements.txt   # dashboard 依赖

# 3. 一致性同步（版本校验 + profiles 同步 + 凭据检查）
powershell -ExecutionPolicy Bypass -File scripts/sync_dsh.ps1
# 若提示凭据缺失：复制模板填 key
#   Copy-Item .dsh\.credentials.example.yaml ~\.dsh\.credentials.yaml  # 填 DEEPSEEK_API_KEY

# 4. 一键启动 3 服务
powershell -ExecutionPolicy Bypass -File scripts/start_all.ps1
#   停止: ... -Action stop   查看: ... -Action status
```

### Docker

```bash
cd etf-strategies
cp .env.example .env        # 填 ANTHROPIC_AUTH_TOKEN（必填）+ DEEPSEEK_API_KEY
docker compose up -d --build   # dashboard + agent + openviking 三服务
```

> 容器内 dsh 启动时从挂载的 `/repo/.dsh/profiles` 同步 xiaoman profile（`cp -rn`，幂等）。

## 4. 部署形态选择

| 形态 | 适用 | 说明 |
|---|---|---|
| 本机（`start_all.ps1`） | 开发/单机日常 | 日志在 `scripts/logs/`，PID 在 `scripts/.pids/` |
| Docker（compose） | 服务器/团队 | 三服务隔离，配置统一走 `.env` |

## 5. 数据云备份（火山引擎 TOS，免费级）

将报告 / SQLite / 日志 / OpenViking 数据同步到云端（数据总量约 16MB，月成本 ≈ ¥0.002）。

### 开通（一次）

1. 火山引擎控制台 → **对象存储 TOS** → 创建桶 `astock-data`（地域 cn-beijing）
2. 控制台 → **访问控制 → AccessKey** → 创建 AK/SK（记下）
3. 配置：
   ```powershell
   Copy-Item scripts\config\cloud.json.example scripts\config\cloud.json
   # 编辑填入 ak / sk（endpoint/bucket 默认即可）
   ```
   > 或设置环境变量 `CLOUD_AK` / `CLOUD_SK`（二选一）

### 执行

```powershell
python scripts/cloud_sync.py            # 同步全部（sqlite 一致性快照 + 报告 + 日志 + OpenViking）
python scripts/cloud_sync.py --dry-run  # 试跑，只打印不上传
```

### 定时（每 30 分钟）

```powershell
schtasks /Create /TN "astock-cloud-sync" /TR "python E:\ideaworkspace\astock-anayisis\scripts\cloud_sync.py" /SC MINUTE /MO 30 /F
```

### 云端结构

```
bucket astock-data/
├── sqlite/<时间戳>/cache.db, agent.db   # 一致性快照（保留所有历史版本）
├── report/  daily-reports/              # 回测 + 每日复盘报告
├── logs/etf/  logs/harness/             # 日志
└── openviking/                           # OpenViking 向量数据
```

### 恢复（新机器 / 本地数据已删除）

```powershell
# 方式1：启动时自动恢复（dashboard 与 agent 进程，环境变量开启）
$env:CLOUD_RESTORE_ON_START = "1"
python etf-strategies/dashboard/app.py   # 启动即从 TOS 拉取最新数据

# 方式2：手动恢复
python scripts/cloud_sync.py --download
```

### 清理本地（数据由 TOS 兜底）

```powershell
# 先确保 TOS 是最新
python scripts/cloud_sync.py
python scripts/cloud_sync.py --download --dry-run   # 确认恢复清单

# 删除本地可恢复数据（报告/日志/SQLite/OpenViking；保留配置与持仓 md）
powershell -ExecutionPolicy Bypass -File scripts/cloud_clean_local.ps1
# 加 -IncludeHoldings 连持仓 md 一起删（由 TOS 恢复）
```

> 凭据：`scripts/config/cloud.json` 已入 .gitignore（见 docs/SECURITY.md）。

## 6. 严格零本地模式（数据全在云端）

设置以下环境变量后，本地不持久化数据（一切以 TOS 为准）：

| 变量 | 作用 |
|---|---|
| `DB_MODE=memory` | SQLite 改 `:memory:` 内存库（启动从 TOS 载入快照、定时回传；磁盘零文件） |
| `CLOUD_RESTORE_ON_START=1` | dashboard/agent/start_all 启动时自动从 TOS 恢复 |
| `LOGS_PURGE_LOCAL=1`（默认开） | cloud_sync 上传日志后清空本地 |

**数据读写路径（云模式）**：
- 持仓/调仓：TOS `holdings/` 直读写（portfolio）
- 回测报告：生成→传 TOS `report/`，展示从云端读（`GET /api/report/file/{name}`）
- 复盘报告：导入从 TOS `daily-reports/`（指纹守卫）
- SQLite：`:memory:` + 快照 `sqlite/<ts>/{cache,agent}.db`（serialize 上传 / backup 载入）
- 日志：上传后清空本地
- OpenViking：启动拉取 `openviking/` → 本地临时 → 停止清理（Windows 极限）

**切换**：不设置这些变量 = 原文件模式（降级/开发/测试）；设置后 = 严格零本地。

> 已知坑：Python 3.11 `sqlite3.deserialize()` 对 WAL 快照半成功（连接损坏）——
> 快照恢复统一走「临时文件 + sqlite3.backup 载入内存，即时删除」（`_deserialize_mem`）。

## 7. 注意事项

- `openviking` 的 `ov.conf` 在 `~/.openviking/`（机器特定，含 provider key）——新机器需 `openviking-server init` 或复制配置
- 火山 embedding 月度配额超限（429）时，OpenViking 不可用（小满其余功能不受影响）；重置后 `start_all.ps1` 或 compose 自动恢复
- 凭据治理细则见 `docs/SECURITY.md`
