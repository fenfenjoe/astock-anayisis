# DSH（DeepSeek Harness）插件生态「Agent 自进化/自我改进」研究报告

> 数据来源：逐一抓取 12 个 GitHub 仓库的 README（main/master 分支 raw URL），并补充抓取了 dsh-rule-evolve 的 package.json、dsh-fail-logger 的 lib/index.js 源码级实现。所有 README 均自带详尽的源码结构说明，故"源码结构"以各 README 文档结构为准。
> 抓取方式：本会话沙箱 curl 因 `SEC_E_NO_CREDENTIALS` 无法直连 GitHub TLS，改走 OpenViking `viking_add_resource` 抓取 raw URL 成功；`api.github.com` 与仓库 HTML 页（JS 渲染）抓不到内容。以下内容全部基于已抓取原文。

---

## 1. dsh-continual-evolve（ZK-Andy）

**一句话定位**：版本化、可审计、可回滚的 harness 状态层——从会话轨迹提炼 prompt notes / memories / skills / subagent specs 为一等公民状态。

**进化机制流程**（README 明示五步：Sediment → Guard → Approve → Apply&Inject → Validate&Rollback）：

- **输入**：会话轨迹（turn-interval + compaction checkpoint 自动评审门提议）+ 模型手动 `evolve_add` 创建的条目。
- **处理**：代码强制校验——edit schema、blast-radius/scope 一致性、promotion 策略（项目作用域标记、薄内容、近重复检测、凭据筛查）；自动 review gate 按 `reviewIntervalTurns`（默认 6 轮）从轨迹切片提议候选；global 写入要求显式人工批准。
- **产物**：本地 scope（会话内）/ 全局 scope（跨会话，merge 语义）两层 store；条目类型：prompt notes、memories、skills、subagent specs。
- **验证**：benchmark 循环——候选改进用**冻结用例 + 独立 scorer** 评估（rubric 用 AES-256-GCM 加密存储）。
- **生效**：原子 apply + snapshot + audit event；prompt notes/delegation specs 注入 system prompt（≤6/种 × 180 字符、相关性排序、被矛盾条目降级、空 store 零 token）；memories/skills 以 capped 目录索引（≤15 行 + 折叠计数）注入。
- **回滚**：**确定性回滚**——逆编辑由 applied results 生成（不用 LLM 重新猜）；被拒候选回滚后捕获为 draft regression cases（`auto_regression` benchmark，`autoCase` 默认开）；`/evolve rollback` 命令 + `/evolve consolidate`（把冲突提示 + 零使用 stale 折叠成一批可逆 archive）。

**关键设计点**：① 核心哲学"**The model proposes, the code guarantees**"——所有机械安全属性（schema、原子写、快照、版本化、审计、验收决策）代码强制、绝不靠 prompt 纪律；② 全局晋升有机械门槛（`promotionMinChars` 100、`promotionBlockPatterns` 拦截 POSIX 路径/session id/`~/.dsh`、global 近重复 ≥0.8 相似度写时拒绝）；③ 每条已应用进化 append 结构化 `evolve_complete` 事件到 `reviews.jsonl`（供第三方消费，`src/evolve-event.ts` 定义形状）；④ `/evolve mount` 可热挂 executable skill 为 live plugin；⑤ 576 个 vitest 测试 + CI 覆盖率门槛；⑥ 灵感源：penguin-harness（概念）+ prime-agent /refine（工程形态，有标注源码参考）。

**对自进化框架的启示**：进化必须是"模型提议 + 代码保证"双层，安全属性不能靠 prompt；验证门禁（冻结用例 + 独立 scorer）与确定性回滚（逆编辑而非 LLM 重猜）是跨会话记忆进化的信任地基。

---

## 2. dsh-evolve（william-jin-cmu）

**一句话定位**：agent 在 session 内随对话给自己长出/剪掉能力——热挂载/可逆卸载/重启恢复的持久插件。

**进化机制流程**：

- **输入**：用户对话中暴露的重复缺口（反复查的表、天天算的换算、老看的端点、私有信息、跨会话状态）；agent 从自然语言捕捉"值不值得进化"。
- **处理**：agent 现场写纯 ESM cordis 插件源码，`evolve_add(name, source, description?, config?)` 持久化到 evolve store（`~/.dsh/evolve/.mjs` + manifest）并**热挂载**；evolve 是完整 cordis 插件，不只工具——常驻 system prompt 规则、`agent/step` / `agent/settled` 事件钩子、定时器 + `agent.send(..., {wakeup:true})` 主动唤醒。
- **产物**：新工具（下一个 step 即可调用）/ 常驻规则 / 事件钩子 / 定时唤醒；持久 store（manifest 含 rev / description / config）。
- **验证**：agent 现场用工具实测（天气三查全过、摊销逐项验算、三条参数路径回归；实证中 agent 还自诊断出日期边界 bug `weekOffset:-1`、挂载失败（引号转义/additionalProperties）读错误重试修复）。
- **生效**：挂载即生效（dsh 工具列表每 step 从当前挂载插件**实时重算**，无 session 级快照；cordis 4 fiber 可回滚 effect——mount 即生效、dispose 即净）；重启 `autoRestore`（默认 true）自动重挂 manifest 全部 evolution。
- **回滚**：`evolve_remove(name, keepSource?)` 可逆卸载——fiber dispose 自动清理其注册的工具/监听/服务，移出 manifest、删除源码；同名再次 `evolve_add` = 替换（旧 fiber 先完整卸载）。

**关键设计点**：① 进化姿态 prompt（order 118）教模型"会复用才长、过时就剪、长了剪了要告知用户"+ 四条非工具进化配方；② "什么值得进化"筛选器：跨会话状态 / 实时外部数据 / 精确计算 / 私有信息四条；再加**形态筛选**——工具是 pull（模型得记得调），凡是"不经过模型决策也必须发生"的（每次都要、自动发生）该长成 prompt section / 事件钩子 / 定时器；③ cache-buster 用进程内单调 seq 而非持久 rev（rev 用于版本；避免 Node 模块缓存加载旧坏源码——这个 bug 正是 E2E 里 agent 自己诊断的）；④ 中途改工具集使 prompt cache 前缀失效（一次性成本）；⑤ 9 条未剪辑 E2E 实录（家庭记账跨会话延续 ¥486→¥548、周报聚合+自修 bug、天气别名、纪念日、汇率双源容错、错误码主动进化、回复长度自我监督拦下自己 407 字符通告→78 字符、worklog 零工具调用照样记、morning-reminder 插件凭空造出新 turn）；⑥ 信任立场：evolution 是真实模块加载、无沙箱、与主 harness 同权限，面向可信自用环境。

**对自进化框架的启示**：进化形态必须区分 pull（工具）与 push（规则/钩子/定时器）——"不经过模型决策也必须发生"的需求做工具是错误姿态；热挂载 + 可逆卸载让能力在会话内即时验证、重启恢复，是自进化真正"落地"的前提。

---

## 3. dsh-rule-evolve（zoahdev，原 dsh-evolve 改名）

**一句话定位**：带验证的规则进化循环——失败日志/经验文档 → 验证过的 AGENTS.md 规则（每规则带来源与最近验证结果）。

**进化机制流程**：

- **输入**：markdown 经验文档（`learn`）、已完成任务的回顾（`reflect`）、原始失败日志（`extract`：逐行扫 ERROR/failed/ERR_，noise 行跳过）。
- **处理**：`learn` 从 markdown 提取规则；`extract` 把失败日志自动转成"当 X 出错时做 Y"的条件规则；存 JSONL（`{id, rule, source, tags, addedAt, verified, lastVerifiedAt}`），按规则哈希去重，标签启发式推断（install/crash/windows/test/memory/security/performance）。
- **产物**：`AGENTS.md` 规则块（`- [EXP-001] … _(source: … · ✅ verified)_`）+ `experience.jsonl` 规则库。
- **验证**：`verify` 跑**真实检查流水线**（默认 `dsh-plugin-doctor check`，`--cmd` 可插拔，任意"成功即退出 0"的命令），每条规则盖章 `verified: true/false`；`tool-verify` 是"agent 写了个工具→能用吗？"就绪门禁，失败/警告检查自动变成经验条目（带验证结果戳）——带失败的发布教会下一个工具怎么不发布。
- **生效**：`evolve` = 验证规则 + 装进 dsh profile（`/profiles/web/AGENTS.md`，旧文件备份）+ 追加 `EVOLUTION.md` 进化日志；下一会话启动就带着教训；`rules` 渲染 AGENTS.md 放仓库根或 dsh profile 规则。
- **回滚/淘汰**：profile 安装时旧 AGENTS.md 备份；`prune` 是**软淘汰**（`retired: true`，reason 保留——可审计、从不删除）。

**关键设计点**（用户提到的四个命令对应 CLI：`evolve_learn`→learn、`evolve_apply`→rules/evolve/verify、`evolve_touch`→touch、`evolve_recall`→recall）：① 规则生命周期自维护：`score`（verifiedCount/usageCount/recency → active/stale）、`prune`（软淘汰）、`merge-duplicates`（Jaccard ≥0.7 近重复合并进高分区，`mergedInto` 保留）——"memory that forgets usefully"；② 跨会话强化：verify/evolve/tool-verify 增 verifiedCount，touch（或插件 `evolve_touch` 工具）增 usageCount，健康分奖励两者，反复验证+反复使用的规则存活、stale 淡出；③ `recall` 是零依赖 BM25-lite 检索（离线、无模型、无网络），并明确是未来接 embedding 提供者的接缝；④ `dash` 生成双语 agent-growth.html 成长报告、`badge` 生成 SVG 徽章（starting/learning/building/growing/legend 按 verified 规则数分级）；⑤ 契合官方讨论 #1881 三层持久记忆 Layer 1（Git 托管的 Markdown 规则）——本项目是"规则从哪来、如何保持诚实"的生产与验证半边。

**对自进化框架的启示**："没有经过验证的东西永远不会被学到"是最硬的原则——记忆进化必须与真实检查绑定；软淘汰 + 近重复合并让规则库自维护而不失真；BM25 级零依赖 recall 证明无嵌入模型也能检索，但留了升级接缝。

---

## 4. deepseek-harness-evolver（shinjiyu，npm 包名 plugin-evolve）

**一句话定位**：宿主无关的工具插件进化控制器 + DSH bundle——信号→提案→校验→本进程热挂→打分→固化/回滚的闭环（补全官方"创造模式"试验后的那一半）。

**进化机制流程**（状态机：`signals → analysis → abstract → stage → validate → mount → score → solidify | rollback ↘ rejected`）：

- **输入**：信号（`evolve_signal` 记 tool_error 等，含 payload.tool）；`analysis`/`evolve_analysis` 读最近 32 条 signal，按 kind + payload.tool 聚成进化点（ready 可提案 / watching 不足两次 / blocked_trial 有在途 trial / stagnant 被停滞锁）。
- **处理**：`abstract` 从 ready 点抽出一个**只 inject tools** 的插件草稿（manifest.json + plugin.js → `.evolve/abstracts/<pluginId>/`）；`stage` 送进 trial（`.evolve/candidates/<trialId>/`，扁平目录：manifest + 入口 + 可选 README/LICENSE）。
- **产物**：候选工具插件（manifest：`{id, kind:"tool", purpose, inject:["tools"], entry, constraints:{network:false, shell:false}}`；入口必须导出 `apply`）。
- **验证**：`validate` 静态检查（控制器**不执行代码**，只静态检查）+ `score` 真实运行打分（`samples≥10 且 successDelta>0 且 retryDelta`——如 retry-on-429 用真实 backoff 打 10 次看成功率）。
- **生效**：`mount` 热挂到本进程（`evolve_mount` 调 `ctx.plugin`，新工具立刻出现在本轮会话）；CLI `mount` 只写盘；`loadout` 让下一个进程 `import` 已进化/在途插件。
- **回滚**：`rollback`；`solidify` 固化到盘上（`.evolve/evolved/<pluginId>/v<n>/`）；**前 3 次 solidify 必须 `confirm:true`**（人工）；同一 signalKind 连续失败 3 次拒绝再 stage（停滞锁）。

**关键设计点**：① 同时最多一个 in-flight trial（`mounted.json`）；`.evolve/state.json` + `events.jsonl`（append-only）；② 严格安全策略表：只允许 kind:"tool"、inject 限 ["tools"]、network/shell 必须 false、体积 ≤32KiB、禁 fs/net/http/child_process/eval/new Function、禁 id（session/loader/agent-loop/evolve controller/plugin-evolve）、打分通过标准、人工确认、停滞锁；③ 明确"**不是已经自动自进化**"：不改 agent-loop/session/loader，抽象的是小工具插件草稿，不替你改业务工程；④ 官方创造模式已把 ctx.plugin + 可逆副作用做完，本插件补"试验之后的闭环"（信号→提案→校验→挂→打分→固化/回滚）；⑤ 演示案例 case:429 完整闭环。

**对自进化框架的启示**：工具进化需要明确的"信号→进化点"聚合（同 kind+tool 多次失败才提案），验证双轨（静态黑名单约束 + 真实运行成功率 delta）；停滞锁 + 前几次固化须人工确认 = 防失控的最小护栏。

---

## 5. dsh-genie（swaylq）

**一句话定位**：把 agent 运行时 `cordis_define` 的动态包固化为跨重启的正式插件（"Wishes that outlive the session"——DSH 自引用工具集缺失的另一半）。

**进化机制流程**：

- **输入**：agent 用官方 `cordis_inspect/cordis_define/cordis_run` 写好并热挂载、已在会话内验证过的动态包（dyn-1）+ 用户说 "keep it"。
- **处理**：`genie_keep dyn-1` → 把动态包固化为 wish：写入 `$DSH_HOME/genie/<wish>/`（package.json + cordis.patch.yml + index.js），symlink 进 launcher 的 flat fallback（`$DSH_HOME/profiles/node_modules`），append 名字到 profile 的 ordered bundle list（`dsh.profile.bundles`）。
- **产物**：可读、可编辑、可 git init、可发布的 wish 目录；`genie_list` 列出所有 wish 及是否 live in profile；`genie_wish` 免原型直接固化 agent 手写代码。
- **验证**：grant 前动态包已在会话内被 agent 证明可用（"you try it. it works."）。
- **生效**：重启后仍在（launcher 从 fallback 解析）；跨重启恢复。
- **回滚**：`genie_revoke` unlist + unlink（保留源码除非要求删除）。

**关键设计点**：① **无 pnpm / 无网络 / 无构建授权**——grant = 写文件 + symlink + append bundle 名，对比 git 安装插件需 prepare 脚本 + allowBuilds（安装时任意代码执行、在 agent 所有沙箱之外）；② 吃透 launcher 三个事实：`profiles/node_modules` flat fallback 实际 append-only、`healProfilesModuleFallback` 只修不错、`dsh plugin` reconcile 只回收 dependencies key 的 bundle 而 wish 写 `dsh.profile.bundles` 不被回收；③ Node 符号链接解析陷阱：wish 的 `node_modules → profiles/node_modules` symlink（否则 Node 从 wish 真实目录向上找永远看不到 fallback）；④ grant 后 dsh-genie 永不重写 wish（"It's just files"）。

**对自进化框架的启示**：把"试验成功 → 一键转正式"做成写文件 + 符号链接 + 追加 bundle 名，绕开正式安装链的无授权持久化；利用 launcher 的 append-only fallback 与 reconcile 盲区是实现"跨重启保留自进化成果"的工程捷径。

---

## 6. dsh-foundry（hellosky983，Plugin Foundry 插件铸造厂）

**一句话定位**：自举式"一切皆插件"编译器——把 DSH 写插件的繁琐运行时契约固化成蓝图（blueprint），选配方 + 填参数一键编译出可直接 `cordis_define` 的代码。

**进化机制流程**：

- **输入**：用户/子代理想快速下沉能力为运行时工具；`foundry_blueprints` 列出蓝图（id/name/category/description/params）。
- **处理**：`foundry_scaffold { blueprint, params }` 按蓝图渲染 code.host（已内置 `output:{schema,render}`、parameters 逐属性 DSL、inject 声明、可逆副作用契约）。
- **产物**：可直接粘贴的宿主/浏览器代码（`code.host` / `code.client`）。
- **验证**：`foundry_validate` 静态校验（定义前）；蓝图本身通过 `node --check` + 冒烟测试（mock ctx 验证工具 + foundry 服务 + `/foundry/state` 路由注册）。
- **生效**：把 code.host 交给 `cordis_define + cordis_run` → 名为 hello 的工具立即上线（模型与子代理皆可调用）。
- **回滚**：Uninstall（从 profile bundles 移除 + pnpm install）。

**关键设计点**：① `foundry` 服务（`ctx.get('foundry')`），任何插件 `registerBlueprint(...)` 续写配方 → 生态自我生长（"插件扩展插件"元编程，蓝图可被其他插件扩展）；② 9 种内置蓝图覆盖 Host/Client/RPC/事件/服务/定时器/系统提示/Skill/文件工具；③ Settings 蓝图画廊页（只读 GET `/foundry/state`，仅本地回环）；④ 蓝图要求"纯 JS 函数体、可逆副作用、正确的 inject 声明"；⑤ 零配置、无环境变量、无敏感数据；⑥ 经典坑：`defineTool` 参数必须是逐属性 DSL（`{prop:{type,required?}}`）而非 `{type:'object',properties}` 包装式；service 要用 `inject:['webServer']` 而非运行时 `ctx.get('webServer')`。

**对自进化框架的启示**：把"运行时契约"固化为可注册的 blueprint 注册表，让插件生态以"注册新配方"扩展自身能力；编译器产物喂给官方 `cordis_define`，形成"配方 → 编译 → 热挂"的能力生成流水线。

---

## 7. distill（LoserFox）

**一句话定位**：自动对话反思与技能蒸馏——回合结束后台反省子代理反思对话并创建/更新 SKILL.md 技能。

**进化机制流程**：

- **输入**：每回合完成（`agent/turn-stopping` 触发）后收集自上次检查点新增的人类 user/message 事件；达 `minUserMessages`（默认 3）触发。
- **处理**：派发后台反省子代理（受限工具集的全新子代理，工具白名单只留 skill 查看器，token 上限 2048、timeout 30s）；提示词带 Hermes 策展课程、消息窗口帧、可更新技能列表；子代理提议 `skip` / `create` / `update`。
- **产物**：新 SKILL.md（带 frontmatter 的 skill 包，写 `targetRoot`：project→`/.agents/skills` 或 user→`~/.agents/skills`）或对先前蒸馏技能的完整替换。
- **验证**：`isSkillName` 校验 kebab-case、描述/内容非空；create 目标已存在跳过；**update 只在目标带 `distilled-by: dsh-distill` 所有权标记时才应用**（用户手写/内置/运行时注册技能永不重写）。
- **生效**：写入的技能后续轮次出现在 `dsh-tool-skill` 目录，本地技能提供方像发现手写技能一样发现它。
- **回滚**：无显式回滚（技能是普通文件）；update 是整文件重写（无局部补丁/不支持 references 等辅助文件）。

**关键设计点**：① **纯观察者**：主对话不注册任何工具/提示，唯一模型可见效果是后台子代理写入的技能间接出现；不写入会话日志（仅运行时 `distill/review-request` 通知给观察者持久化）；② 依赖 `ctx.subagents` + `subagent-spawn-in-process`（spawn 提供方）+ `tool-skill`（子代理可查看技能）；③ 检查点推进到最后一条已反思消息（每轮只覆盖新消息；内存检查点，进程内）；④ 失败绝不崩溃循环：提供方缺失/运行失败/取消/无结果只记警告；⑤ 灵感源自 Nous Research hermes-agent `_SKILL_REVIEW_PROMPT`（MIT 署名）。

**对自进化框架的启示**：蒸馏应当完全后台化（回合后运行、从不与用户任务争抢、白名单工具集）；`distilled-by` 所有权标记是"自动改进不覆盖人工资产"的关键护栏——只更新自己生成的技能。

---

## 8. dsh-eval-harness（BiBoyang）

**一句话定位**：DSH 插件/skill 作者的回归评测门禁——yaml 用例 → headless 驱动真实 agent → 解析 session trace 断言 → baseline 对比出 PASS/WARN/FAIL 与 CI 退出码。

**进化机制流程**（本质是自进化的"验收/回归门禁"组件）：

- **输入**：`cases/*.yml` 用例（name/prompt + 断言：`turn_end`、`tools_called`（保序子序列）、`output_contains`、`max_steps`、`max_tokens`、`no_tool_errors`、`tools_exact`、`tools_not_called`、`tool_args_contains`、`tool_result_contains`、`output_judge`（LLM 语义评审））。
- **处理**：`eval_run` 逐条 fork `dsh --profile headless --patch <overlay>` 子进程跑真实 agent（overlay 把 session 落盘切到隔离目录，每条用例独立 workspace + session root，可 concurrency 并行）；解析落盘 `session.jsonl[.zstd]` trace（多帧 zstd 直读、零外部依赖），执行断言。
- **产物**：`report.json`（schemaVersion:1）+ `report.md`（summary + 各用例状态 + attemptResults + token 分字段聚合 + trials reliability）。
- **验证**：结构断言优先、judge 兜语义（结构全过才调 judge，不白烧 token）；LLM-as-judge 用 `eval_judge_validate` 在人工标注集上校准（**TPR/TNR 双指标 ≥0.9 才算 calibrated**，分开看——agreement 会骗人）。
- **生效**：`eval_gate` 对比 baseline 出 OVERALL=PASS|WARN|FAIL|N/A + 退出码（strict 收紧 WARN 为 2），CI 拦截回归；baseline 更新走手动触发 workflow + 人工复核 PR，**不自动合入**。
- **回滚**：baseline/report.json 入库版本化（人工复核后覆盖）；用例口径变更须重跑全量人工复核。

**关键设计点**：① 每用例完全隔离（per-case session 根 + workspace + concurrency）→ 并行互不污染；② 门禁信号极其丰富：PASS→FAIL、新增/移除、token 涨幅（默认 +50%）、skippedLines 增长、flaky 增多、pass 但带工具硬错误（agent 自我纠正的假通过）、重复错误签名 ≥2 次（共享态事故）、trials reliability（Wilson 下界）；③ trials 测 pass@k/pass^k（无偏估计，明确不用 plug-in (c/n)^k 因 Jensen 上凸上偏）；④ judge 生命周期管理：写可判定 rubric → 攒标注集（通过/失败都要有）→ 校准 → 进门禁 → 换模型/分布变化重校准；⑤ 防 CI 空跑假绿：筛选无命中直接报错；⑥ 报告头记 `dshVersion`（区分"dsh 变了"还是"模型变了"）。

**对自进化框架的启示**：任何自进化必须以"真实 agent 跑的回归用例 + baseline 对比"为验收门禁；LLM judge 作为断言要用混淆矩阵校准（TPR/TNR 分离），且结构断言失败不调 judge——保证不产生假绿、不白烧 token。

---

## 9. forkprobe（Jayden-X-L）

**一句话定位**：AI Skill 选型与试跑工具——同一任务交给模型本身和多个候选 skill 并排试跑，看真实输出后选 winner 并继续（"别猜哪个 skill 有用，直接并排看结果"）。

**进化机制流程**（这是自进化的"能力选择"环节——多候选对比 + 人类仲裁）：

- **输入**：任务 + 候选 skills/pipelines（curated 目录 / 本机已装 Skill（~/.codex、~/.agents、~/.claude、~/.dsh 及项目内）/ EverMind Skill Hub / GitHub / BYO 路径）。
- **处理**：`recommend.py` 生成候选清单（按内容指纹 + 来源去重、按场景匹配度排序）等待确认；`compare.py` 等 runner 并行试跑 baseline + 每个候选；外部发现只用清洗后的任务信号，不自动安装/执行未确认候选。
- **产物**：本地 HTML report（每路完整输出、耗时、token 估算、文件预览、AI 评审建议）；artifact 模式产出 PPTX / figure package / research package / 网页 / 视频成品（含 preview、QA）。
- **验证**：AI judge 评审 + **用户看真实输出后选 winner**；artifact QA（网页 1440×1000 与 390×844 视口截图 + Playwright 移动端溢出测量 + ffprobe 视频检查——不可测量就如实记录不伪报）。
- **生效**：选 winner → 生成 continuation handoff，当前 Agent 沿胜出 Skill 的风格/结构/产物继续正式任务；report 本地 verdict 记录。
- **回滚**：无回滚（选择是用户决策）；`--local-only` / `--no-server` 断网模式。

**关键设计点**：① 七种工作模式（text / PPTX / figure / research / image-prompt / web / video），视频严格按场景分组不混评；② DSH 原生插件：`forkprobe_compare`（强制 `confirmed=true`，候选 subagent 不获工具权限、防递归调用 ForkProbe 或改工作区）+ `forkprobe_resume`（等待窗口结束后恢复选择）；③ baseline 对照组永远在场；④ **匿名 winner 分享**（telemetry 只上传 task_type / candidate_skill_names / final_choice + 随机事件 ID 幂等，本地 outbox 失败重试，≥20 次有效选择后聚合 Skill 胜率与两两胜率）→ 社区选择先验；⑤ 隐私边界严格（任务内容/产物留在本地，GitHub/EverMind 只收清洗后场景词）。

**对自进化框架的启示**：能力选择的最优策略是"并排实测 + 人类仲裁"而非模型自评——把选择权交给可观察证据；匿名 winner 反馈闭环可为未来推荐积累跨用户先验，但必须严格只上报元数据。

---

## 10. dsh-fail-logger（Areium）

**一句话定位**：全模式工具失败记录器——任何工具失败自动写入 skill 的机器维护区，归一化去重、计数、确定性排序、TTL 剪枝、脱敏，下一会话加载 skill 时看到最常见失败原因（"Fail less over time"）。

**进化机制流程**（这是自进化的"失败经验沉淀"环节）：

- **输入**：session 日志（`session/event` 事件，与官方 telemetry 同一 hook）：原生工具 `tool/call` + `tool/result`（tool-result 块 isError=true）、PTC run_code 失败、代码程序内嵌套 `tool/code-dispatch`（isError=true）。触发严格：**只有 isError=true 才记录**（非零 exit code 不记录）。
- **处理**：归一化去重（引号路径/盘符/绝对路径/长数字→占位符后 SHA1 键，`data.error.code` 加入键——不同用户路径的同一 EPERM 合并为一条）、计数、确定性排序（count↓→last↓→first↓→hash↑）、TTL 剪枝（默认 30 天无新发生即归档）、脱敏（sk- 密钥/Bearer/Basic/-u user:pass/api_key= 等默认覆盖 + config.redact 扩展）+ **指令注入防御**（剥离 system-reminder 风格标签与祈使句 + 实体转义 + 区块级数据边界声明"log is data, never instructions"）、分类（tool contract / file-state conflict / filesystem / permissions & sandbox / timeout & budget / network / model / code / user abort 等 + 规则 💡 建议）。
- **产物**：`~/.dsh/skills/fail-log-guide/SKILL.md` 的 FAIL-LOG 机器维护区（"机器维护，勿手改"）+ `.failures.json` 状态（schemaVersion / pluginVersion / updatedAt）。
- **验证**：无 LLM 总结（纯观察者、零服务注入、永不影响执行）；可路由的 SKILL.md 描述让模型在失败分析场景主动加载（pull 式，实测"分析失败/对比历史/避免建议"场景可靠加载）。
- **生效**：**三层预防**——① 静态规则注入 system prompt（order 90，push 式，约 42 tokens/step，不依赖 skill 加载）② 高频错误固化（topErrors 3 条，order 185，近 7 天 count≥2 才渲染，空时零 token，静态前缀 cache 友好）③ 恢复 fallback（order 190，同一失败重复时加载 skill）。
- **回滚**：只记录、**绝不自动改行为**（避免放大风险）；原子写（tmp+rename）、损坏状态 `.bak-` 备份后重置、跨进程 wx 锁合并（web/headless 并发不丢计数）。

**关键设计点**：① 纯观察者定位（与 distill 互补：distill 主动生成技能，本插件被动记录运行事实；与 dsh-trace 不同：本地自愈、无外部通道）；② timeout 治理升为一等规则（实测 19 条 timeout 失败——整盘 glob/grep、run_code 里塞长任务——从 53.1s 降到 16.1s，整盘搜索 108s→9.4s 零工具调用）；③ token 经济账：避免 1 次失败 22–55 步回本，避免一次整盘搜索省 30–170s；④ 去重启发式有界（归一化前 1–3 行文本，同根因不同措辞可能分裂，可接受并明示）。

**对自进化框架的启示**：失败记忆应"记录 + 统计 + 排序"而非"总结"（无 LLM、纯观察者、绝不自动改行为）；预防走 push（常驻指令防未加载）+ pull（skill 按需加载）双轨；失败数据进上下文必须有数据边界声明与指令注入防御。

---

## 11. dsh-self-improved（madage）

**一句话定位**：完全本地的长期记忆 + 自进化插件——L0 capture → L1 memory extraction → L2 scene grouping → L3 user persona，外加 skill 合成（"The AI remembers you"）。

**进化机制流程**：

- **输入**：会话事件（L0 capture 落盘到本地 SQLite）；对话中的事实/偏好/事件/指令。
- **处理**：L1 用 `ctx.llm` 抽取 + 严格 JSON 校验/fallback + 去重 + throttled pump；L2 场景分组（scenes）；L3 用户画像（persona）持续演化；consolidate / decay / correct。
- **产物**：本地 SQLite（FTS5 + jieba + sqlite-vec）记忆库；场景 + **版本化 persona**；合成 skills → `dsh-skill`。
- **验证**：每 milestone 单元测试（test-storage / extract / recall / evolve / commands 全 PASS）+ headless 集成验证；M0–M6 全部完成并部署到真实 web profile。
- **生效**：每 turn 前（`agent/pre-step` 注入）检索相关记忆注入模型（keyword / vector / hybrid，RRF 融合）；合成 skill 出现在 dsh-skill 目录。
- **回滚/纠错**：`correct` / `forget` 工具 + 设置页 Memory 浏览器人工修正/遗忘（persona、scenes、skills 均可看/改/删）。

**关键设计点**：① 四层记忆金字塔架构（灵感自 TencentDB Agent Memory，独立实现、MIT）；② 完全本地（无任何数据上传），复用 DSH 原生服务（ctx.llm / session events / agent pre-step 注入 / dsh-skill / storageDomain）；③ **成本分时降级**：15 分钟维护循环只做抽取 + 免费维护（decay/governance，无 LLM 成本），全量进化（scenes/persona/skills）只在夜间 review（默认 22:00）或 `~60s` 后或手动 `/memory evolve` 跑；主开关关闭即全部定时器停、工具注销、记忆保留；④ `/memory` 命令零 LLM（直接查本地库）；⑤ 两个安装坑实录：peerDependencies 双实例导致 persona 注册冲突（用 dsh 自愈 symlink 布局 / `auto-install-peers=false` 修复）、重复 loader entry id 启动即崩（bundle 装配完全归 `dsh.profile.bundles`，profile 层不要手动 insert）；⑥ 自进化模块（consolidate/forget/correct + skill synthesis）设计受 OpenClaw 的 self-improving-agent 启发。

**对自进化框架的启示**：进化要分"廉价维护循环"（零 LLM）与"昂贵全量进化"（夜间一次）做成本分时降级；persona 版本化 + correct/forget 人工纠错闭环，是长期记忆进化"不跑偏"的必须组件。

---

## 12. dsh-genome（Elohia）

**一句话定位**：能力转化与组装引擎——管理 skill / MCP / plugin 三库，负反馈伺服闭环进化（参考钱学森工程控制论/系统论）。

**进化机制流程**（观测→比较→决策→执行→再观测）：

- **输入**：三库（skill 启动自动吸收：扫描 `~/.agents/skills`、`$DSH_HOME/skills` 等标准根 + `skills.list()` 全局层，零手动登记；MCP/plugin 由 install/up 维护）+ 工具调用 metrics（监听 `tools/result` 事件，每次调用自动写 metrics，按 model 分桶）。
- **处理**：`scan` 判定 Sick/Weak（**Sick = 错误率 > 10%**、Weak = 反馈不足，死区阈值）；`select` 晋升/淘汰决策（`{key, decision, by, reason}`）；`mutate` 变异意图 + Fix A/B/C 建议。
- **产物**：registry / metrics / history（进化树）数据；toolkit 挂载/回收。
- **验证**：负反馈选择——只有评估确认改善才晋升。
- **生效**：`/plugins/genome/up` 挂载 toolkit（按 model 分桶度量）；`/plugins/genome/down` 回收；进化树记录。
- **回滚**：`/plugins/genome/rollback` 30s 防呆回滚（disposer 全量回收 + 版本链）；**停机条件**：连续 N 轮无改善 → 稳态、停止进化。

**关键设计点**：① 控制论工程化：负反馈选择、死区（阈值门）、幅值限制（`maxExpanded=6`，**一次只变一个对象**）、30s 回滚冗余、停机条件、人机结合（综合集成）；② Web 设置页「基因组」可观测可操控（总览/发现/进化）+ composer dock 状态条（官方 Slots）；③ 商店桥：搜 GitHub dsh-plugin topic（内置 fetch，无需登录、限流 10 次/分钟）+ install 吸收进 registry（spec 白名单校验，拒绝 `;/&|` 命令注入）；④ 零外部依赖（仅 node 内置 + fetch）；⑤ SKILL.md 方法论层（`/genome scan|mutate|select|rollback|log|status`）。

**对自进化框架的启示**：进化引擎应借鉴控制论——观测指标 → 死区比较 → 保守决策（一次只动一个）→ 可回滚执行 → 无改善停机；skill 自动吸收 + 工具自动度量让"能力面"零成本自建，Web 可观测可操控是让自进化可控的关键。

---

# 共性模式总结

## 一、这些插件共同依赖的 DSH 底层能力

| 底层能力 | 具体机制 | 依赖它的插件 |
|---|---|---|
| **插件机制（cordis bundle）** | package.json 声明 `dsh.bundle` → `cordis.patch.yml` insert；`dsh plugin add` 安装、`--dump-config` 验证、profile 分层；组合层变更不参与 HMR（装后需重启） | 全部 12 个 |
| **动态包工具集（cordis_inspect/define/run）** | agent 现场写插件热挂载到本进程（动态包仅存内存、不跨重启） | dsh-genie（固化这些动态包）、dsh-foundry（编译产物喂给它）、dsh-genome（"动态实验体"） |
| **ctx.plugin 热挂载 + 可逆副作用（官方创造模式）** | 挂载即生效、dispose 即净；工具列表每 step 从当前挂载插件实时重算（无 session 级快照） | deepseek-harness-evolver（evolve_mount 调 ctx.plugin）、dsh-evolve（fiber effect）、dsh-foundry |
| **session 轨迹（session/event 事件流 + 落盘 session.jsonl[.zstd]）** | 事件帧 `{type, seq, time, data}`；官方 telemetry 同款 hook | dsh-continual-evolve（轨迹提炼）、distill（turn-stopping 收消息）、dsh-fail-logger（session/event 观察失败）、dsh-eval-harness（解析 trace 断言）、dsh-self-improved（L0 capture）、dsh-genome（tools/result 度量） |
| **headless 运行（dsh --profile headless）** | 独立子进程跑真实 agent，零上下文累积、可并发隔离 | dsh-eval-harness（eval_run fork 子进程）、forkprobe（artifact runner 路径） |
| **systemPrompt 分层注入（section + order）** | 可插拔 section、order 排序、函数式 text（动态/缓存友好） | dsh-continual-evolve（注入 notes + 目录索引）、dsh-fail-logger（order 90/185/190 三级）、dsh-evolve（order 118 进化姿态）、dsh-self-improved（pre-step 记忆注入） |
| **skill 机制（SKILL.md + 提供方 + dsh-tool-skill）** | 技能发现/查看/写入、frontmatter 路由描述决定加载率 | distill（创建/更新）、dsh-fail-logger（维护机器区 + 可路由描述）、dsh-self-improved（skill synthesis→dsh-skill）、dsh-rule-evolve（AGENTS.md 进 profile 规则）、dsh-genome（skill 库自动吸收） |
| **事件钩子** | `agent/turn-stopping`、`agent/pre-step`、`agent/step`、`agent/settled` | distill（回合后反思）、dsh-fail-logger（session/event）、dsh-evolve（钩子型进化）、dsh-self-improved（pre-step 注入） |
| **子代理机制（ctx.subagents + 提供方）** | spawn-in-process 提供方、受限工具集子代理、delegationDepth | distill（后台反省子代理）、dsh-eval-harness（子会话 trace 分档）、forkprobe（forkprobe_compare subagent fan-out） |
| **LLM 服务与工具契约（ctx.llm / dsh-tools defineTool）** | `output:{schema,render}`、parameters 逐属性 DSL、inject 声明、可逆副作用 | dsh-self-improved（L1 抽取）、dsh-foundry（固化的契约）、dsh-evolve（evolution 内直接 import @deepseek-ai/dsh-tools） |
| **本地存储域** | `~/.dsh/` 下各插件自有数据目录；`storageDomain` | 全部（.evolve/、~/.dsh/evolve/、~/.dsh/genie/、~/.dsh/skills/、~/.dsh/genome/ 等） |

## 二、自进化框架可复用的公共构件清单

1. **演化状态存储**：append-only 事件日志（events.jsonl / reviews.jsonl）+ 状态文件（state.json / mounted.json / experience.jsonl / .failures.json）+ SQLite（FTS5 + sqlite-vec，dsh-self-improved 范式）。统一 schema 版本号。
2. **版本化与快照**：manifest rev / 版本链 / atomic apply + snapshot / EVOLUTION.md 每轮进化日志 / baseline 入库（人工复核后覆盖）。**快照+日志=审计完备**。
3. **确定性回滚**：逆编辑由 applied results 生成（dsh-continual-evolve）；fiber dispose 自动清理（dsh-evolve）；rollback 命令 + 30s 防呆（dsh-genome）；软淘汰保留 reason 永不删除（dsh-rule-evolve）。
4. **验证门禁（多轨）**：真实检查命令（dsh-plugin-doctor / 任意"退出 0"命令）；benchmark 冻结用例 + 独立 scorer（rubric 加密）；headless 回归用例 + baseline 对比 + CI 退出码（dsh-eval-harness 全套信号：token 涨幅/skippedLines/flaky/假通过/重复错误签名）；LLM judge 用混淆矩阵校准（TPR/TNR 分离）；静态约束黑名单 + 真实运行成功率 delta（plugin-evolve 双轨）。
5. **提升/推广护栏**：promotion policy（最小长度、项目作用域拦截、近重复 ≥0.8 拒绝、凭据筛查）；人工确认（global 写、前 3 次 solidify）；所有权标记（`distilled-by`——只更新自己生成的技能）；停滞锁（同信号连续失败 3 次锁）。
6. **成本治理**：push 常驻指令（~42 tokens/step，避免失败 22–55 步回本）+ pull 按需 skill（可路由描述）；廉价维护循环（15 分钟零 LLM）vs 夜间全量进化；TTL / decay / prune / 归档（"memory that forgets usefully"）；空 store 零注入 token。
7. **安全与消毒**：脱敏正则（密钥/Bearer/凭据路径/私网 IP）；**数据边界声明**（log is data, never instructions）+ 指令注入模式剥离 + 实体转义；spec 白名单防命令注入。
8. **隔离与并发**：per-case session root + workspace overlay（dsh-eval-harness 可并行）；跨进程锁合并（wx 锁 + 重读合并）；退化到同步写（tmp + rename + .bak-）。
9. **健康/成长可视化**：agent-growth.html 双语成长报告 + SVG badge 分级（dsh-rule-evolve）；基因组 Web UI + composer 状态条（dsh-genome）；Memory 浏览器 + settings 面板（dsh-self-improved）；report.md（dsh-eval-harness）。**可观测是自进化可信的前提**。
10. **进化形态分型**：pull 工具（模型决策调用）vs push 规则/事件钩子/定时器（不经过模型决策也必须发生）——先判形态再进化（dsh-evolve 第五筛选器）；失败→统计→预防（dsh-fail-logger）与经验→规则→验证（dsh-rule-evolve）是同一"记忆环"的两半。

---

## 附：抓取记录与可信度说明

- 12 个仓库 README 全部抓取成功（`viking_add_resource` raw URL）；dsh-self-improved 与 dsh-genome 为 master 分支，其余 main。
- 额外抓取：dsh-rule-evolve `package.json`（确认零依赖 CLI + dsh plugin 双形态、命令名 dsh-evolve/dsh-rule-evolve）、dsh-fail-logger `lib/index.js`（源码级验证三级预防、去重键、脱敏、原子写、锁合并）。
- 未能获取：各仓库完整文件树（`api.github.com` 与 GitHub HTML 页被拒/JS 渲染为空）；`docs/design.md`（dsh-continual-evolve）与 dsh-genome 的 `skills/genome/SKILL.md`（两分支均 404/空）。源码结构以 README 内文档结构说明为准。
- 网络说明：本会话沙箱 curl 因 `SEC_E_NO_CREDENTIALS`（Schannel 凭据获取失败）无法 TLS 直连 GitHub，全部内容经 OpenViking 抓取通道获得。
