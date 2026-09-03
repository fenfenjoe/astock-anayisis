# etf-dashboard Docker 部署指南

> 版本：2026-08-27（随每日复盘调度迁移设计 v1 + 跨平台定时任务）
> 拓扑：容器内完成 **定时调度 → 执行引擎跑分析 → 报告自动导入 DB → Web 展示** 全链路；
>       仓库根（prompt/报告/持仓/交易日历）通过挂载与本地共用同一份文件。

## 1. 架构

```
宿主机
├── etf-strategies/.env        # 敏感令牌（ANTHROPIC_AUTH_TOKEN 等，不进镜像）
└── 仓库根 ../  ──挂载──▶  /repo（DASHBOARD_REPO_ROOT）
容器 etf-dashboard（restart: unless-stopped，端口 8000）
├── 执行引擎（DASHBOARD_SCHEDULER_ENGINE=auto）
│     ├─ 容器内未装 dsh → 自动落到 **claude -p**（认证：方舟 ARK，ANTHROPIC_AUTH_TOKEN）
│     │     └─ claude -p 执行 my_doc/每日复盘/harness/automation/prompts/auto_*.md
│     └─ 本地运行时若装有 dsh CLI → 自动用 dsh headless（DeepSeek Harness，免 ARK token）
├── dashboard scheduler（auto=1，20s tick）
│     ├─ 时间窗口判定（task_schedule.json，16 个每日复盘任务）
│     ├─ 幂等：scheduler_runs.window_key（SQLite）
│     └─ 报告增量重扫（60s，mtime 守卫）→ 自动导入 DB
├── Web 界面 :8000（策略/持仓/信号/报告/定时任务，30s 自动轮询刷新）
└── 数据卷：dashboard_data(DB+密钥) / dashboard_cache(K线) / dashboard_report(回测报告)
```

## 2. 前置要求

- Docker Desktop（Docker Engine ≥ 24 + Compose v2）
- 一个可用的 **方舟 ARK API 令牌**（`ANTHROPIC_AUTH_TOKEN`）：
  claude -p 在容器内经 Anthropic 协议路由到方舟 ARK（DeepSeek 模型），
  值可从宿主 `~/.claude/settings.json` 的 `env` 块获取（与本地 claude 一致）。

## 3. 快速开始

```bash
cd etf-strategies
cp .env.example .env          # 编辑 .env 填入 ANTHROPIC_AUTH_TOKEN
./start_dashboard.sh          # 首次自动构建镜像并启动；等待健康检查通过
# 打开 http://localhost:8000 （首次 admin 密码见日志: ./start_dashboard.sh logs）
```

Windows（Git Bash 可用时）同样执行 `./start_dashboard.sh`；
无 Git Bash 时手动执行：

```powershell
docker compose up -d --build
docker compose logs -f        # 首次 admin 密码在这里
```

## 4. 环境变量（.env）

| 变量 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `ANTHROPIC_AUTH_TOKEN` | ✅ | — | 方舟 ARK 令牌（claude -p 认证） |
| `ANTHROPIC_BASE_URL` | | `https://ark.cn-beijing.volces.com/api/plan` | ARK 端点 |
| `ANTHROPIC_MODEL` | | `deepseek-v4-flash-ga-260731` | 主模型 |
| `ANTHROPIC_DEFAULT_*_MODEL` | | 见 .env.example | 子模型路由 |
| `DASHBOARD_SCHEDULER_ENABLED` | | `1` | **1=容器内 auto 调度开启**（迁移后为唯一调度器） |
| `DASHBOARD_SCHEDULER_ENGINE` | | `auto` | 执行引擎：`auto`（容器内无 dsh → claude）/ `claude`（强制） |
| `DASHBOARD_SCHEDULER_WINDOW_MINUTES` | | 7 | 调度窗口容差（休眠恢复场景可 30） |
| `DASHBOARD_PORT` | | `8000` | 映射端口 |
| `DASHBOARD_ADMIN_PASSWORD` | | 自动生成 | 预设 admin 密码（推荐设置） |
| `DASHBOARD_SECRET_KEY` | | 自动生成 | JWT 密钥（持久化在 data/.secret_key） |
| `DASHBOARD_REPO_ROOT` | | `/repo` | 仓库根挂载点（勿改） |

## 5. 每日复盘定时任务（引擎随容器生命周期）

**调度模型（2026-08-27 最终决策）**：调度引擎随 Web 进程启停——**容器启动 = 调度启动，容器停止 = 调度停止**，无需任何系统 cron / 计划任务（Docker 内 `DASHBOARD_SCHEDULER_ENABLED=1` 默认开启）。

- 容器启动即导入历史报告 + 启动调度引擎（auto=1，20s 轮询，零 token）
- 16 个每日复盘任务（早盘/盘中×8/复盘/周度/巡检/REQ/提醒/信号质量周报）到点自动执行
- 执行完成 → 报告/信号自动导入 DB → Web「📄 报告」「📡 每日信号」「⏰ 定时任务」30s 内自动刷新
- **防双跑**：宿主上不要残留 `dsh-trigger-*` / `etf-trigger-*` 计划任务（如有：管理员运行 `scripts/setup_etf_scheduled_tasks.ps1 -Cleanup` 清除）
- 修改调度：编辑 `.claude/scripts/task_schedule.json`（挂载在 /repo，容器内立即生效，无需重建）
- 本地 Windows 启动同理：`scripts/start_local.ps1`（默认 auto ON，随 Web 启停）

### 5.1 可选：外部 cron 精确触发（非默认，仅特殊场景）

dashboard 引擎是 **20s 纯 Python 轮询（零 token）**；若某天需要**精确时刻触发 + Web 未运行时也执行**（服务器场景），
可用系统级定时任务调用独立触发入口，并把引擎 auto 关闭（`DASHBOARD_SCHEDULER_ENABLED=0`）：

```bash
# 触发入口（同步执行，退出码 = 任务成败）
python -m dashboard.scheduler_cli --task morning_analysis      # 正常（星期/交易日/幂等判定）
python -m dashboard.scheduler_cli --task evening_review --force
```

| 平台 | 配置示例 |
|------|---------|
| **Linux crontab** | `7 9 * * 1-5 cd /repo/etf-strategies && python -m dashboard.scheduler_cli --task morning_analysis`（盘中/盘后同理；脚本内部有交易日/幂等判定，非交易日自动跳过） |
| **macOS launchd** | 写 plist：`ProgramArguments = [python, -m, dashboard.scheduler_cli, --task, evening_review]` + `StartCalendarInterval` 15:52（1-5 星期） |
| **Windows 计划任务** | `scripts/setup_etf_scheduled_tasks.ps1 -Apply`（创建 `etf-trigger-*`，动作 = `python etf_trigger.py --task X`；`-Cleanup` 清除回归引擎模式） |

**两种模式的幂等共用 `scheduler_runs.window_key`**（cron 触发与引擎 auto 同 key），即使误开也互斥不重复执行。

## 6. 日常运维

```bash
./start_dashboard.sh logs        # 跟踪日志（含调度派发/报告导入记录）
./start_dashboard.sh restart     # 重启（保留数据卷）
./start_dashboard.sh rebuild     # 改 Dockerfile/.env 后重建镜像再启动
./start_dashboard.sh status      # 容器状态 + 健康检查
./start_dashboard.sh down        # 停止（保留数据卷）
./start_dashboard.sh down -v     # 停止并删除数据卷（慎用：清空 DB/K线/回测报告）
```

### 升级流程

```bash
git pull                        # 拉取最新代码（prompt/代码均在 /repo 挂载内）
./start_dashboard.sh rebuild    # 重建镜像（代码层）并重启
# 提示：/repo 挂载的 prompt/报告/经验改动无需重建，重启即可生效
```

### 备份

- 数据全部在数据卷与 `/repo` 挂载：备份 `docker volume`（`dashboard_data` 等）+ 仓库根即可
- 示例：`docker run --rm -v etf-dashboard_dashboard_data:/data -v %cd%:/backup alpine tar czf /backup/db.tgz -C /data .`

## 7. 故障排查

| 症状 | 排查 |
|------|------|
| 容器启动即退出，日志报 `ANTHROPIC_AUTH_TOKEN` 缺失 | .env 未填令牌（compose 显式 `:?` 校验） |
| 任务运行失败，日志显示 claude 认证错误 | ARK 令牌过期/权限；换令牌后 `./start_dashboard.sh restart` |
| 报告不刷新 | 检查「⏰ 定时任务」页引擎状态（auto 是否开）；`docker compose logs` 看 rescan 记录 |
| 取数慢/失败 | a-stock-data 优先 HTTP 源（腾讯/东财），容器 NAT 可直连；mootdx TCP 7709 不通时自动降级 |
| 内存不足（OOMKilled） | `docker stats` 查看；compose 已放宽 2G，仍不足可再调 `memory` |

## 8. 与本地运行的关系

- 本地与容器**共用同一份仓库**（`/repo` 挂载），报告/持仓/经验/交易日历天然一致
- 本地启动 `python dashboard/app.py` 与容器启动二选一（同一份 cache.db 需避免双写：
  本地用 `dashboard/data/cache.db`，容器用数据卷——**不要同时跑**，否则 K 线缓存双写冲突）
- 推荐：日常在容器跑（免 Python 环境）；本地只用于开发调试

### 8.1 本地启动与调度模式

- **Windows 本地启动**：`powershell -ExecutionPolicy Bypass -File scripts/start_local.ps1`
  - 自动检测宿主计划任务并提示调度模式：检测到 `etf-trigger-*`（精确触发）→ 建议引擎 auto 关闭（默认即如此）；
    检测到旧 `dsh-trigger-*` 仍启用 → 警告双跑
  - 要引擎轮询触发用 `-Auto`（与计划任务共用幂等 key，互斥不重复）；`-DryRun` 只预览
- **Linux/macOS 本地启动**：`python dashboard/app.py`（配 `DASHBOARD_SCHEDULER_ENABLED=0|1` 控制引擎 auto；
  系统 cron 用 `python -m dashboard.scheduler_cli --task X` 精确触发，见 §5.1）
- **Docker 启动**：`./start_dashboard.sh`（同样检测宿主计划任务：检测到 `etf-trigger-*` 时提示
  将 `.env` 的 `DASHBOARD_SCHEDULER_ENABLED` 置 0）
