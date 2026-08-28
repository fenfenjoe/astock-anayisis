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

## 5. 注意事项

- `openviking` 的 `ov.conf` 在 `~/.openviking/`（机器特定，含 provider key）——新机器需 `openviking-server init` 或复制配置
- 火山 embedding 月度配额超限（429）时，OpenViking 不可用（小满其余功能不受影响）；重置后 `start_all.ps1` 或 compose 自动恢复
- 凭据治理细则见 `docs/SECURITY.md`
