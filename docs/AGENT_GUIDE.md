# AGENT_GUIDE — AStock 量化系统使用手册（给 Agent 读）

> 版本：v1.0（2026-10-16）· 配套解耦改造：`docs/2026-10-15-AStock与Agent解耦方案与进度.md`
>
> 本文是**外部 Agent（小满 / dsh / 其他 AI）**接入本量化系统的标准化说明书。
> 本仓库是**纯量化系统**：数据 / 回测 / 信号 / 报告 API + CLI，不包含 agent 运行时。

---

## 1. 系统定位

- **量化侧**（本仓库 `astock-anayisis`）：A 股 ETF 多策略回测 + 信号生成 + Web Dashboard(:8010) + REST API。
- **Agent 侧**（`~/.dsh/workspace/xiaoman/`，不在本仓库）：小满运行时(:8020)、自动化调度、harness、Web。
- **职责分离**：量化系统管**数据与 API**，Agent 管**执行与展示**。Agent 通过本文档调用量化接口拿数据/跑回测/导入报告，再自行组织输出。

```
astock-anayisis (纯量化系统)          ~/.dsh/workspace/xiaoman (小满之家)
├── backtest/ 回测引擎                 ├── agent/    小满运行时(:8020, X-Api-Key)
├── dashboard/ Web+API (:8010, JWT)   ├── automation/ ETF自动化
├── cli.py / daily_signal.py / ...    ├── harness/   每日复盘
├── docs/AGENT_GUIDE.md  ← 本文档       ├── scripts/  调度基础设施
└── my_doc/ 持仓/调仓/报告              └── web/      小满 Web(纯前端 SPA)
```

---

## 2. 快速开始

```bash
cd etf-strategies
pip install -r requirements.txt
```

**环境变量**（`.env`，参考 `.env.example`）：
| 变量 | 用途 |
|---|---|
| `DASHBOARD_PORT` | Dashboard 端口（标准 **8010**） |
| `DASHBOARD_DB_BACKEND` | `cloud` 走 Supabase 云库；默认本地 SQLite |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` | 云库凭据（权威表：持仓/报告/工单/调度） |
| `AGENT_API_KEY` | 小满 Agent API 的 X-Api-Key（在 `~/.dsh/workspace/xiaoman/` 配置，非本仓库） |

**启动 Dashboard**：
```bash
DASHBOARD_PORT=8010 python dashboard/app.py   # → http://localhost:8010
# 或 Windows: etf-strategies/scripts/start_local.ps1
```
默认账号 `admin` / `admin123`（登录拿 JWT）。

---

## 3. 量化 API 清单（Dashboard :8010，JWT Bearer 认证）

登录：`POST /api/auth/login {username, password}` → `{token}`，之后所有请求带
`Authorization: Bearer <token>`。

### 3.1 策略 / 信号 / 回测
| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/strategies` | 全部策略绩效指标（年化/夏普/MaxDD/Calmar/胜率/换手） |
| GET | `/api/strategies/{sid}` | 单策略详情（KB + 指标） |
| GET | `/api/strategies/{sid}/source` | 策略源码 |
| GET | `/api/strategies/{sid}/rebalances` | 调仓历史 |
| GET | `/api/strategies/{sid}/diagnostics` | 策略内部状态（打分/持仓） |
| GET | `/api/strategies/{sid}/perf-1y` | 一年期绩效 |
| GET | `/api/signals` | 全部策略当日信号（买入/卖出/持有） |
| GET | `/api/signals/{sid}` | 单策略当日信号 |
| GET | `/api/daily-signals` | 每日信号列表（含历史） |
| GET | `/api/charts/equity` | 权益曲线数据 |
| POST | `/api/backtest/run` | 触发全量回测 |
| POST | `/api/backtest/{sid}` | 运行单策略回测 |
| POST | `/api/refresh/signals` | 强制刷新信号 |
| POST | `/api/refresh/klines` | 增量同步 K 线 |
| GET | `/api/scores/{sid}` | 打分曲线 |

### 3.2 报告 / 持仓 / 调仓
| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/reports` | 报告列表 |
| GET | `/api/reports/{report_date}/{report_type}` | 某日某类报告（早盘/盘中/复盘） |
| POST | `/api/reports/import` | **导入报告**（Agent 生成后回写） |
| GET | `/api/portfolio` | 当前持仓 + 资产 |
| PUT | `/api/portfolio/holdings` | 更新持仓 |
| POST | `/api/portfolio/trades` | 记录调仓 |
| POST | `/api/portfolio/trades/undo` | 撤销调仓 |
| POST | `/api/portfolio/refresh` | 刷新持仓/行情 |

### 3.3 信号质量 / 工单 / 通知
| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/signal-quality` | 信号质量统计 |
| GET | `/api/signal-history` | 信号历史 |
| GET | `/api/tickets` | 工单列表（自动化发现的 BUG/REQ） |
| GET | `/api/tickets/{ticket_id}` | 工单详情 |
| POST | `/api/tickets/{ticket_id}/retrigger` | 重新触发工单 |
| GET | `/api/notify/status` | 企业微信通知状态 |
| POST | `/api/notify/test` | 测试通知 |

---

## 4. CLI 工具

| 命令 | 用途 |
|---|---|
| `python run_backtest.py` | 全量回测 → 绩效表 |
| `python run_backtest.py --sid S4` | 单策略回测 |
| `python daily_signal.py` | 生成当日信号 |
| `python list_strategies.py` | 策略列表（rich 表格） |
| `python html_report.py --sid S4` | 一年期 HTML 报告 |
| `python cli.py` | 交互式 CLI 菜单 |

---

## 5. 调用示例

### 5.1 取当日信号（curl）
```bash
TOKEN=$(curl -s -X POST http://localhost:8010/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' | python -c "import sys,json;print(json.load(sys.stdin)['token'])")
curl -s http://localhost:8010/api/signals -H "Authorization: Bearer $TOKEN"
```

### 5.2 取持仓（Python）
```python
import requests
BASE = "http://localhost:8010"
tok = requests.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "admin123"}).json()["token"]
H = {"Authorization": f"Bearer {tok}"}
print(requests.get(f"{BASE}/api/portfolio", headers=H).json())
```

### 5.3 导入报告（Agent 生成复盘后回写）
```python
requests.post(f"{BASE}/api/reports/import", headers=H, json={
    "report_date": "2026-10-16",
    "report_type": "evening_review",
    "content": "<markdown 或 html>",
})
```

### 5.4 运行单策略回测
```python
requests.post(f"{BASE}/api/backtest/S4", headers=H).json()
```

---

## 6. 数据时点约定（输出纪律）

- 每份报告开头标注 **「数据时点：YYYY-MM-DD HH:MM」**（盘中注明时间，盘后注明收盘）。
- 区分**实测值**（标来源端点，如"东财 push2his"）与**推算值**（标"估算" + 置信度）。
- 数据不足写"数据不足无法判断"，**不为填满表格而编造**。
- 资金面结论需结合量价/北向交叉验证，不单独作为买卖依据。

---

## 7. 数据源纪律

- 取数一律走 **`a-stock-data` skill**（本机已装）：mootdx(TCP)/腾讯财经优先（低封 IP 风险），东财限流（`em_get`，间隔≥1s）。
- 禁止用网络泛搜索或凭印象"估算"填核心数据栏（ROE/PE/PB/资金流/研报一致预期）。
- 端点与字段索引见 `a-stock-data/SKILL.md`。

---

## 8. 小满侧入口（Agent 回写/展示）

| 项 | 地址/说明 |
|---|---|
| 小满 Web（纯前端 SPA） | `~/.dsh/workspace/xiaoman/web/`（`python -m http.server 8080` 托管） |
| 小满 Agent API | `:8020`，鉴权 `X-Api-Key`（=`AGENT_API_KEY`，默认 `xiaoman-secret-key-change-me`） |
| 小满 Agent 启动 | `~/.dsh/workspace/xiaoman/scripts/start_all.ps1`（或 `python -m agent` in `agent/`） |
| 自动化调度 | `~/.dsh/workspace/xiaoman/scripts/task_schedule.json`（单一事实源） |
| 工单/需求 steering | `~/.dsh/workspace/xiaoman/automation/steering/` |

---

## 9. 常见任务流

1. **早盘分析**：取信号(`/api/signals`) + 持仓(`/api/portfolio`) → 走 `daily-review-harness` 早盘模板 → 生成报告 → `POST /api/reports/import`。
2. **盘中检查**：取实时信号/行情（`a-stock-data`）→ 与持仓对比 → 输出买卖提醒。
3. **收盘复盘**：取当日信号/持仓/盘后行情 → 走复盘模板评估早盘预测 → 经验沉淀（`harness/experience/`）→ 导入报告。
4. **发现 BUG/需求**：写入 `~/.dsh/workspace/xiaoman/automation/{bugs,steering}/` → 在 dsh web 让 dsh 处理。
