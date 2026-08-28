# astock-trade-entry — A股持仓/资产 页面 + 交易录入（DSH web 插件）

在 DeepSeek Harness Web GUI 中提供**持仓/资产页面**与**交易录入**能力：

- 侧边栏底部新增「持仓 / 资产」入口（图标 + 文字按钮），点击打开右侧抽屉页面；
- 页面展示：可用金额、当前持仓表（名称/代码/数量/成本价，T+0 品种带标记）、最近 10 条调仓记录；
- 录入表单：日期 / 名称 / 代码 / 方向（买入·卖出）/ 做T开关 / 数量 / 价格 / 备注；
- 录入后**自动更新持仓与可用金额**（成本价移动平均、清仓移除、资金扣减/回补），并写入
  `每日调仓.md`（§0 可用金额 + §1 当前持仓 + §2 调仓记录）与 `harness/config/持仓.md`；
- 内置校验：卖出不得超过持仓、**T+1 当日买入份额不可当日卖出**、可用金额不足拦截、代码-名称一致性；
- 「撤销最近一笔」：基于写前快照回滚，录错可一键撤销。

## 数据一致性（与每日复盘 harness 的关系）

| 文件 | 角色 | 写入方 |
|---|---|---|
| `my_doc/每日复盘/每日调仓.md` | **唯一权威来源**（复盘任务 4.5 以此为准） | 本插件（界面录入）或人工编辑 |
| `my_doc/每日复盘/harness/config/持仓.md` | 同步快照（复盘报告读取） | 本插件（与每日调仓.md 同步写入）+ 复盘 4.5 覆写 |

- 界面录入 = 直接写这两个文件，**口径与复盘任务 4.5 完全一致**（§0 可用金额、§1 持仓表、§2 调仓记录、config 快照格式）；
- 复盘流程零改动：仍从 每日调仓.md 读权威持仓 → 4.5 同步 config/持仓.md → 报告；
- 录入后如 4.5 重新同步，两文件内容一致（幂等），不会产生差异；
- 写入为原子操作（临时文件 + rename），且**先写 每日调仓.md、再写 持仓.md**，任一步失败回滚，绝不半更新。

## T+1 口径

A股/场内权益 ETF 当日买入份额当日不可卖出（`ledger.isT0` 白名单：513/159 跨境、511 债券等 T+0 品种除外）。
因此：**当日新建仓标的不可能当日止盈**——录入界面会拦截"卖出当日买入份额"，复盘模板（`复盘分析-模板.md` 第二节）
也禁止对当日新增持仓做"未止盈"批评（详见报告审阅经验 3.4）。

## 架构

```
dsh-plugins/astock-trade-entry/
├── index.mjs      # 宿主端：挂 /api/astock-trade-entry/{state,append,undo} 路由（webServer）
├── ledger.mjs     # 纯函数账本：解析/校验/重算/序列化（无 IO，可单测）
├── client.js      # 浏览器端：__ModuleLoader__ 插件，注册 sidebar.footer.action
├── cordis.patch.yml  # bundle 层插入 Loader entry
└── package.json   # dsh.client 元数据 + exports["./client"]
```

路由（仅 loopback 同源）：
- `GET  /api/astock-trade-entry/state`   — 持仓/资金/最近记录
- `POST /api/astock-trade-entry/append`  — 录入一笔（校验 → 重算 → 原子写两文件 → 快照）
- `POST /api/astock-trade-entry/undo`    — 撤销最近一笔（快照回滚）

## 部署（web profile）

1. `package.json`（`~/.dsh/profiles/web/package.json`）dependencies 增加：
   `"@astock/dsh-trade-entry": "link:E:/ideaworkspace/astock-anayisis/dsh-plugins/astock-trade-entry"`
2. 同一文件的 `dsh.profile.bundles` 增加 `"@astock/dsh-trade-entry"`。
3. 在 `~/.dsh/profiles/web` 执行 `pnpm install`（把 link 依赖物化到 node_modules）。
4. 重启 `dsh web`，刷新页面 → 侧边栏底部出现「持仓 / 资产」。

> 工作目录/项目根：插件默认取 `dsh web` 进程 cwd，要求其下存在
> `my_doc/每日复盘/每日调仓.md`。若 cwd 不同，在 `cordis.patch.yml` 的 Loader 行加
> `config.root: 'E:/ideaworkspace/astock-anayisis'`。

## 测试

```bash
cd my_doc/每日复盘/harness/automation && python -m pytest tests/ -q   # harness 既有测试（不受影响）
node -e "import('./dsh-plugins/astock-trade-entry/ledger.mjs').then(m=>console.log('ledger OK'))"
```
