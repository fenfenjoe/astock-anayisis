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
- **openviking**：小满的语义记忆后端（**火山云版**，见 §4.1；本地 server 不再必须）

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

## 4.1 OpenViking 云版接入（推荐，替代本地 server）

OpenViking 可用**火山引擎云服务**（`api.vikingdb.cn-beijing.volces.com`），无需本地跑 `openviking-server`，也绕开了本地 embedding 月度配额问题。

### 接入（一次）

1. **装插件**（xiaoman 即小满 profile 已装 `@openviking/dsh-memory-plugin`）：
   ```bash
   dsh plugin --profile xiaoman add @openviking/dsh-memory-plugin
   ```
2. **写云端凭据**到 `~/.openviking/ovcli.conf`（敏感，勿入库）：
   ```json
   { "url": "https://api.vikingdb.cn-beijing.volces.com/openviking",
     "api_key": "<火山 OpenViking 云 API Key>" }
   ```
3. **隔离**：dsh_runner 已自动注入 `OPENVIKING_PEER_ID=xiaoman` + `OPENVIKING_RECALL_PEER_SCOPE=actor`（小满与其它 agent 记忆互不混淆）。

> 插件按 ${baseUrl}/mcp 连云端 MCP。endpoint/key 也可改用环境变量 `OPENVIKING_URL` / `OPENVIKING_API_KEY`。

### 验证

```bash
# 最小：dsh --profile xiaoman "用 viking_search 搜一条记忆"
# 或直接在小满会话里 viking_remember / viking_search 往返
```

已实测：xiaoman peer 的 `viking_remember → viking_search` 闭环通过；`OPENVIKING_PEER_ID` 不同（headless）搜不到 → 隔离有效。

### 与本地版的关系

- 配置 `ovcli.conf` 指向云后，本地 `openviking-server` 可**不启动**（`start_all.ps1` 的 openviking 服务可跳过）；本地版仍可作回退。
- 本地旧数据（仓库 `data/`、`~/.openviking/data/`）云版不读取；如需清理可手动删除这些目录（2026-09-07 起 TOS 备份已下线，删除不可云端恢复，请先确认不需要）。

## 5. 数据云备份（已下线 — 火山引擎 TOS）

> **2026-09-07 下线**：云权威库已迁移至火山 Supabase 版 Postgres（见 `docs/2026-09-07-云端数据库迁移方案.md`），
> TOS 对象存储（桶 `astock-data`）已停用：`scripts/config/cloud.json` 凭据已清空，`cloud_store.py`、
> `cloud_sync.py`、`cloud_clean_local.ps1` 等 TOS 代码已移除。权威数据全部在 Supabase 云库，
> 本地 `reports/`、`my_doc/每日复盘/`（持仓/调仓/复盘报告）为工作副本。
> 若需彻底删除 TOS 桶，见下方「清理 TOS 桶」步骤。

### 清理 TOS 桶（可选，不可逆）

```powershell
# 1. 确认无代码再写 TOS（本仓库已移除全部 TOS 调用）
# 2. 火山引擎控制台 → 对象存储 TOS → 桶 astock-data：
#    - 全选对象 → 删除（含 648 个对象，约 739 MB，其中 sqlite/ 旧快照 728 MB）
#    - 桶清空后删除桶本身
# 3. 可选：访问控制 → AccessKey → 停用/删除对应 AK/SK（若仅此桶使用）
```

> 数据安全：删桶前确认本地 `reports/`、`my_doc/每日复盘/每日调仓.md`、`harness/config/持仓.md` 均在，
> Supabase 云库报告/持仓齐全 —— 删 TOS 不丢权威数据。

## 7. 注意事项

- `openviking` 已接**火山云版**（`~/.openviking/ovcli.conf` 指向云，见 §4.1）；本地 `openviking-server` 可选/回退，非必需
- 若用本地版，其 `ov.conf` 在 `~/.openviking/`（机器特定，含 provider key）——新机器需 `openviking-server init` 或复制配置
- 凭据治理细则见 `docs/SECURITY.md`
