# 基于 DeepSeek Harness 的 Agent 自进化框架研究文档

> 版本：v0.1（研究稿）
> 日期：2026-09-24
> 范围：为以 DeepSeek Harness（DSH）为底座的 Agent 设计一套"自进化框架"，包含通用层（处理自进化普遍需求）与可定制层（用户确立目标、引导进化方向、建立正循环）。
> 方法：业界方案调研 + DSH 生态调研（插件注册表 839 个插件） + 本机 DSH 运行时解剖 + 本项目已有实践（每日复盘 Harness）反推。

---

## 目录

1. [背景与目标](#1-背景与目标)
2. [什么是 Agent 自进化：业界方案调研](#2-什么是-agent-自进化业界方案调研)
3. [DSH 为什么是天然的自进化底座](#3-dsh-为什么是天然的自进化底座)
   - 3.1 DSH 架构解剖 / 3.2 六个"进化接缝" / 3.3 生态组件盘点 / 3.4 关键插件机制深挖 / 3.5 共性模式
4. [本项目已有的"事实自进化系统"](#4-本项目已有的事实自进化系统)
5. [自进化框架原理](#5-自进化框架原理)
6. [框架设计：通用层](#6-框架设计通用层)
7. [框架设计：可定制层](#7-框架设计可定制层)
8. [自进化的产物是什么](#8-自进化的产物是什么)
9. [落地路线图与风险](#9-落地路线图与风险)
10. [参考资料](#10-参考资料)

---

## 1. 背景与目标

Agent（智能体）当前最大的工程瓶颈不是"单次任务的正确率"，而是**能力的持续累积**：

- 每次会话都是"从零开始"：即使上次已经解决了相似问题、沉淀了经验，下次仍然可能重复犯错；
- 模型权重无法（也不应）为每个领域任务频繁微调；
- 用户在对话中教给 Agent 的知识、Agent 在实践中总结的规律，散落在历史会话里，无法自动变成"下次自动会做"的能力。

自进化（Self-Evolution）要解决的问题，就是让 Agent **在使用中持续改进自身**：把"这次做对了什么 / 做错了什么"转化为"下次自动怎么做"的持久化增量，且不依赖模型参数更新。

本框架的目标：

1. **通用部分**：抽象出任何 Agent 自进化都会遇到的需求（轨迹捕获、经验沉淀、反思、验证、版本化、回滚、健康检查、安全门禁、调度），提供开箱即用的机制；
2. **可定制部分**：允许用户为 Agent 确立目标（如"提升 A 股信号命中率"），并让整个进化回路朝向该目标形成**正循环**（目标 → 执行 → 反馈 → 改进 → 验证 → 目标达成 → 下一目标），而不是无方向的"随机变异"；
3. **以 DSH 为底座**：充分利用 DSH 的插件机制、Skill 机制、Memory 机制、Session 轨迹、headless 沙箱，将进化能力以"可安装、可组合、可审计"的框架形式落地。

---

## 2. 什么是 Agent 自进化：业界方案调研

### 2.1 定义与本质

业界对自进化 Agent 的通行定义（arXiv 2507.21046《Self-Evolving Agents: A Systematic Survey》等）：

> **自进化 Agent 是能通过自身与环境交互的反馈，持续修改自身某个持久组件的系统。** 与普通 Agent 的区别在于：普通 Agent 的 policy / prompt / skill 固定，能力全部来自预训练与一次性 prompt 工程；自进化 Agent 在使用过程中持续更新某一层（参数 / skill / memory / workflow / tool / 规则）的能力。

核心公式（Shilong Liu《A Taxonomy of Self-evolving Agents》以及阿里云 Agentic Cloud 框架）：

```
Agent = Model + Harness
Harness = 循环设计（loop）+ 记忆（memory）+ 工具（tools）+ 上下文管理
Agent 执行任务 → 产生 Artifact（产出物）
```

- **Model**：大脑，响应 prompt 的 LLM；
- **Harness**：把模型变成 Agent 的周边组件（循环、记忆、工具、上下文）；
- **Artifact**：Agent 产出的结果（报告、代码、策略、发现的算法、论文）。

自进化就是让 **Harness（乃至 Artifact 的生成方式）** 随使用不断改进。

### 2.2 三层进化框架（Artifact / Harness / Model）

按"进化发生在哪一层"，自进化系统可分为三层（越往下越难、越持久）：

| 层级 | 进化对象 | 代表系统 | 特征 |
|------|---------|---------|------|
| **L1 Artifact 迭代优化** | 任务的产出物本身 | 各种代码生成自修复、DeepSeek-R1 式 test-time 思考 | 最快、最浅，几乎每个 Agent 都在做（失败重试、自我修正） |
| **L2 Harness 自改进** | 提示词、记忆、工具、Skill、工作流、规则 | **Voyager、Reflexion、AFlow、AgentFactory、Ctx2Skill、OpenSkill**、DSH 生态各插件 | 中等速度；把"这次的经验"固化为"下次的能力"；**这是本框架的主战场** |
| **L3 Model 无金标学习** | 模型权重本身（自生成数据 + RL 微调） | Self-Challenging Agent (SCA)、Self-Rewarding、Native Evolution | 最慢、成本最高；需要训练基础设施，**DSH 场景一般不涉及** |

> 关键判断：**对以 DSH 为底座的 Agent 而言，自进化 = L2 Harness 自改进。** 模型权重不变，进化发生在 harness 层的 skill / memory / rule / workflow / plugin 上。这也是 2024-2026 最重要的范式转移——"能力容器从参数变为 Markdown 文本（SKILL.md），一切推理时注入 `system_prompt += K`"。

### 2.3 四大可进化支柱

自进化 Agent 系统 Π = (Γ, {ψᵢ}, {Cᵢ}, {Wᵢ}) 的四个可进化支柱（arXiv 2507.21046；misevolution 论文亦按此四维度分类）：

| 支柱 | 含义 | 进化方式 | DSH 中的对应物 |
|------|------|---------|---------------|
| **Model {ψᵢ}** | 模型参数/推理策略 | 参数微调、RL、推理时策略（test-time compute） | provider/model 配置（可切换） |
| **Context {Cᵢ}** | 指令（prompt）+ 长期记忆 | 提示词迭代、记忆写入/召回 | **Skill（SKILL.md）、system prompt、Memory 插件** |
| **Tools {Wᵢ}** | 工具集合 | 工具新增、改进、废弃 | **Tool 插件、MCP server、自定义工具** |
| **Workflow Γ** | 循环/流程/编排 | 工作流改写、子代理编排、调度 | **命令（commands）、自动化 prompts、headless 调度** |

> 注意：misevolution 论文（arXiv 2509.26354）按 **model / memory / tool / workflow** 四条路径分类，与上述四支柱一致——记忆是 Context 的核心组成部分。这四者就是"进化可以动的地方"，也是"可能进化错的地方"（见 2.6）。

### 2.4 三种范式

按"进化信号从哪来"，自进化有三种范式（Native Evolution 论文 §2 的分类）：

1. **经验驱动（Experience-Driven）**：人造任务 + 奖励信号，如 AgentTuning、ToolLLM、**Voyager**（Minecraft 中边探索边攒技能）。
2. **对抗自博弈（Adversarial Self-Play）**：Challenger-Solver 双角色，挑战者生成任务/找茬，解决者改进，如 **Absolute Zero、Ctx2Skill**（5 角色自博弈蒸馏技能）。
3. **元学习/免奖励（Meta-Learning / Reward-Free）**：训练时给结果奖励，推理时无任务无奖励地自我探索，如 Native Evolution。

> 对本框架的启示：**DSH 场景天然适合"经验驱动 + 对抗自博弈"混合**——"经验驱动"对应复盘式经验沉淀（Generator-Evaluator 分离，Evaluator 即挑战者），"对抗自博弈"对应"找茬式审阅/多 Agent 互评"。

### 2.5 代表性系统速览

| 系统 | 进化机制 | 对本框架的启示 |
|------|---------|---------------|
| **Voyager** (NVIDIA) | 自动课程（automatic curriculum）+ 技能库（可执行代码技能，按描述 embedding 检索）+ 迭代式提示与自验证（critic 验证、失败修改） | 技能库 + 检索 + 自验证三件套；"技能是可检索、可组合、可跨会话累积的单元" |
| **Reflexion** (Princeton) | 失败后生成自然语言反思，存入情景记忆缓冲，下次尝试前先读反思（口头强化学习） | "反思作为奖励信号"；Generator-Evaluator 分离的雏形 |
| **AFlow** | 代码形式演化工作流（operator 变异、交叉、选择），自动搜索 Agent 工作流 | 工作流本身可被当作进化对象（Workflow 支柱） |
| **GPTSwarm / MetaGPT** | 图/多智能体结构演化 | 多 Agent 结构可进化 |
| **AgentFactory** | 把成功任务解法固化为"可执行子代理代码"，持续基于执行反馈精炼；库随任务增长 | **进化产物不只是文本经验，而是可执行的子代理/工具代码** |
| **Ctx2Skill** | 上下文蒸馏为技能（5 角色自博弈） | 对话轨迹 → Skill 的自动转化 |
| **OpenSkill** | 从文档/仓库/网络获取锚点知识 → 合成可迁移技能 → 用自建虚拟任务（锚点驱动而非答案驱动）精炼 | 技能合成的"锚点验证"思想 |
| **MUSE-Autoskill** | 技能创建 + 记忆 + 管理 + 评估的完整技能生命周期 | Skill 生命周期管理的完整化 |
| **Self-Challenging Agent** | 挑战者生成 Code-as-Task 问题、执行者解决、用成功轨迹自生成数据微调参数 | L3 模型层进化的代表（本框架不涉及，但"挑战者-解决者"结构可借鉴到验证环节） |
| **AlphaEvolve / MAP-Elites** | 质量-多样性（Q+D）档案：不只保留最优，还保留多样化变体，多目标（fitness/novelty/robustness/cost） | 进化不只追求单点最优，还保留多样性变体，防局部最优 |

### 2.6 误进化风险（Misevolution）

《Your Agent May Misevolve: Emergent Risks in Self-evolving LLM Agents》(arXiv 2509.26354) 明确指出：**自进化会在 model / memory / tool / workflow 四条路径上出现"误进化"（misevolution）**——即进化偏离预期，导致不良甚至有害结果，且顶级模型也会中招。典型误进化形态：

- **奖励黑客**：针对评估标准钻空子而非真正改进；
- **记忆污染**：把一次性错误/噪声写进长期记忆，越用越偏；
- **工具滥用/自伤**：进化出的工具/规则损害原有能力（灾难性遗忘）；
- **工作流退化**：流程越改越绕，或绕开安全门禁；
- **目标漂移**：长期进化偏离用户真实意图。

> 这是本框架必须内置"安全门禁 + 评审闸 + 回滚 + 人工确认"的根本原因（见第 6 节通用层模块 G8/G9）。

---

## 3. DSH 为什么是天然的自进化底座

### 3.1 DSH 架构解剖

DeepSeek Harness 本体（`@deepseek-ai/dsh` v0.1.0-rc.6）是一个**极薄的启动器**：

```
dsh CLI (bin.js)
  └─ 解析 --profile <name> 等启动参数
      └─ 加载 profile（~/.dsh/profiles/<name>/）
          ├─ cordis.yml            # 空条目列表，树由 patch 组成
          ├─ cordis.patch.yml      # 用户补丁层（id 定位的配置覆盖/插入）
          ├─ package.json          # dsh.profile.bundles → 插件依赖
          └─ node_modules/         # pnpm 安装的插件包
              └─ 启动 cordis 插件树（@deepseek-ai/cordis 事件系统）
                  ├─ 官方 bundle：dsh-llm / dsh-session / dsh-tools / dsh-agent /
                  │               dsh-system-prompt / dsh-user-approval / dsh-timeout ...
                  └─ 第三方插件：@openviking/dsh-memory-plugin、dshmarket、dsh-find-plugin ...
```

核心事实：

- **Profile = 一个可组合的 Agent 实例**。`dsh --profile web` 是当前 GUI；`dsh --profile headless "任务"` 是一次性无界面执行（零上下文累积）；`dsh --profile xiaoman` 是另一个 Agent。每个 profile 是一棵 cordis 插件树。
- **Cordis 事件总线**是 DSH 的"神经系统"。插件通过 `ctx.on(...)` 挂事件钩子、`ctx.provide(...)` 提供服务、`ctx.effect(...)` 管理生命周期。
- **Agent 预设（agent-presets）**：minimal / standard / code / cordis，定义了不同工具组合与 persona，本身可被 patch 覆盖。
- **Skill 机制**：SKILL.md（Markdown 能力容器）可从 `~/.agents/skills/`、项目 `.agents/skills/`、项目 `.dsh/skills/`、插件自带 skills 目录等多处加载，注入到模型上下文。

### 3.2 六个"进化接缝"

DSH 为自进化提供了六个现成的接缝（以 @openviking/dsh-memory-plugin 的实际实现为证）：

| 接缝 | 事件/API | 自进化用途 |
|------|---------|-----------|
| **捕获** | `session/event`、`turn/end` | 把会话中的用户/助手/工具消息变成进化原料（轨迹→经验） |
| **注入** | `agent/session-start`、`agent/pre-step`（`agent.inject()`，注入为持久 user message 而非 system prompt） | 把已沉淀的经验/记忆/技能索引在合适的时机注入回模型上下文 |
| **服务** | `ctx.provide()` | 提供进化框架自身的运行时服务（如 evolve 服务、评估服务） |
| **工具** | `defineTool`（来自 @deepseek-ai/dsh-tools） | 注册进化相关工具（evolve_learn、skill_create、eval_run……） |
| **结构** | cordis.patch.yml `insert:` / `disable:`；`cordis_define` 动态插件 | 以"补丁层"方式增删插件/配置 = 结构性进化（可热重载、可审计） |
| **沙箱** | headless profile；`dsh --profile headless "..."` | 独立进程跑验证/实验，零上下文累积、崩溃自愈 |

> 关键细节：记忆/经验注入应走 **pre-step 持久 user message**（source 标注为 plugin），而不是 system prompt——因为部分 preset 的 persona 声明 `complete: true` 会清空其他 prompt 段，system prompt 注入会静默丢失；而 pre-step 注入是会话事件、可回放、可压缩、不进 request header。

### 3.3 DSH 生态中已有的自进化组件盘点

对 DSH 插件市场注册表（839 个插件，2026-08 快照）按 `evolv / self / memory / skill / learn / reflect / improv / grow / curriculum / experience / agent` 关键词过滤，得到 258 个相关命中；其中与"自进化"直接相关、可按模块归位的组件如下（★ 为 star 数，全部开源）：

**① 完整进化回路类（与本框架目标最接近）**

| 插件 | ★ | 机制概述（据注册表描述） |
|------|---|------------------------|
| **dsh-continual-evolve** (ZK-Andy) | 6 | **持续自进化**：版本化、可审计、可回滚的 harness 状态（prompts、memory、skills、subagent 规格）从会话轨迹提炼，带评审门禁与热重载 skill |
| **dsh-evolve** (william-jin-cmu) | 6 | **自进化**：agent 在会话中热挂载/移除持久插件（mid-session 自我修改） |
| **dsh-rule-evolve** (zoahdev) | 0 | **验证驱动的自进化回路**：失败日志 → 验证过的 AGENTS.md 规则；会话内插件（evolve_learn / evolve_apply / evolve_touch / evolve_recall），工具验证门禁，规则生命周期，本地召回 |
| **deepseek-harness-evolver** (shinjiyu) | 2 | Creator 模式补充：**stage（暂存）→ validate（验证）→ live-mount（经 ctx.plugin 热挂载）→ score（评分）→ solidify（固化）或 rollback（回滚）** 的内存工具插件试炼 |
| **dsh-genome** (Elohia) | 1 | 能力转换与组装引擎（钱学森控制论/系统框架）：常驻层管理 skill/MCP/plugin 注册表，自动吸收技能与工具指标，驱动**负反馈进化** |
| **dsh-self-improved** (madage) | 1 | 长期记忆 + 自进化：L0 捕获 → L1 记忆抽取 → L2 场景分组 → L3 用户画像，自动召回注入，**技能综合（skill synthesis）**，全本地（SQLite FTS5 + jieba） |
| **hindsight#coding-agents** (vectorize-io) | 20011 | 会学习的 Agent 记忆：长期项目记忆、自动召回与保留、知识页、深度反思、按仓库记忆库 |

**② 技能进化类（Skill 生命周期）**

| 插件 | ★ | 机制概述 |
|------|---|---------|
| **distill** (LoserFox) | 19 | 自动对话蒸馏：后台子代理反思 + **skill 创建/更新** |
| **forkprobe** (Jayden-X-L) | 66 | **同一任务对比多个 skill 选出胜者**（A/B 测试式技能进化） |
| **dsh-fail-logger** (Areium) | 8 | 自动记录失败工具调用，根因去重计数，**沉淀为 skill 让重复错误衰减** |
| **dsh-skillradar** (hellosky983) | 3 | 扫描当前会话可见 skills，按与最近对话的相关性排序 |
| **dsh-skillport** (Jesse-njx) | 2 | 把 Claude/Codex/Cursor/Gemini 的 SKILL.md 库导入 DSH |
| **Code2Skill** (leechen298) | 3 | 从用户授权源码生成 Functions / MCP 工具 / 工作流 Skill / 离线测试包 |
| **dsh-memory-director** (ljsysfurryACE) | 0 | 每轮后模型决定保留什么（MemoryDirector），按步注入相关记忆，跨会话持久化 |

**③ 结构性自修改类（Plugin 进化）**

| 插件 | ★ | 机制概述 |
|------|---|---------|
| **dsh-genie** (swaylq) | 1 | 把 agent 运行时用 `cordis_define` 动态创建的包**固化为跨重启存活的正式插件**（写 bundle + 注册 profile 层，无需 pnpm/联网/构建授权） |
| **dsh-foundry** (hellosky983) | 2 | 插件编译器：blueprint 注册表（scaffold → validate → deploy），三个模型工具 |
| **dsh-fabric** (hellosky983) | 2 | 用一套声明式 DSL 统一所有 DSH 扩展缝：运行时 fabric 服务 + fabric_extend / fabric_inspect 工具 + 能力图谱设置页 |
| **dsh-hot-plugin-host** (tianyaZTY) | 1 | 运行时插件加载：监听热目录，实时安装/更新 client-plugin bundle，免重启 |
| **dsh-plugin-autoevo** (klarkxy) | 0 | 先解析本地工具与 skills，再搜索、评审、一次性批准后安装社区插件 |

**④ 评估与治理类（进化的裁判）**

| 插件 | ★ | 机制概述 |
|------|---|---------|
| **dsh-eval-harness** (BiBoyang) | 5 | **评估 harness**：YAML 用例驱动真实 headless agent 运行，断言工具调用/参数/结果/token 用量，带 baseline 门禁（CI 回归） |
| **dsh-trajectory-governance** (dfycaly98931680) | 3 | 轨迹治理与异常诊断：扁平会话日志重建多分支轨迹树，检测循环死锁/无效重试/目标漂移，成本归因，一键中断 |
| **dsh-proof** (EvilIrving) | 1 | 独立只读验收层：每个顶层 turn 结束前派生只读验证者，未通过则把差距导回 agent 修正（Generator-Evaluator 分离的自动化） |
| **dsh-devtools** (izz-BLUE) | 1 | 元数据优先的运行时剖析器：turn/step 轨迹、模型与工具耗时时间线、provider 用量、重试、错误 |
| **dsh-session-health** (omdsh-dev) | 8 | 会话健康检查 |
| **dsh-doublecheck / dsh-auto-review** (PerryLink) | 2/4 | 第二模型自动复核 / 只读评审子代理返回结构化 allow/deny 裁决（fail-closed） |

**⑤ 记忆与经验类（进化的存储）**

| 插件 | ★ | 机制概述 |
|------|---|---------|
| **@openviking/dsh-memory-plugin**（本机已装） | - | 记忆捕获（session/event）+ 语义召回（pre-step 注入）+ viking URI 保护 + 7 个记忆工具；本会话正在使用 |
| **dsh-mneme#dsh-mneme** | 13 | 跨会话记忆：SQLite + 人类可编辑 Markdown 镜像、autoDream 整合、六个记忆工具、全离线语义搜索 |
| **dsh-auto-memory** | 12 | 三层记忆（用户/项目笔记/每日日志）+ 每轮自动整合 + 智能搜索 |
| **dsh-mnemon** | 33 | 跨 Agent 本地优先持久记忆，与 Mnemon 共享 |
| **MisakaNet** (skill) | 387 | 失败-恢复记忆：记录真实工程会话的失败-恢复教训，BM25 + 语义 RAG 检索，教训知识库 |
| **dsh-handoff** | 0 | 按工作目录与 git 分支自维护交接记忆：记录 turns、折叠为 Markdown、注入未来会话 |
| **dsh-observation-journal** | 3 | 观察日志（进化原料的另一种形态） |

**⑥ 调度与触发类（何时进化）**

| 插件 | ★ | 机制概述 |
|------|---|---------|
| **dsh-sentinel** | 8 | 条件驱动唤醒：文件/命令/HTTP/进程/webhook 持久监视，唤醒 agent |
| **dsh-aura-scheduler** | 1 | 主动调度：自适应心跳 + 价值网络（紧迫性/相关性/打断成本）决定何时主动说话 |
| **dsh-automation / dsh-plugins#dsh-plugin-scheduled-tasks / dsh-routines** | 42/4/1 | 定时/间隔/cron 运行 prompt（fresh headless 会话 + 持久运行历史） |
| **dsh-weekly-digest / dsh-period-report** | 2/0 | 聚合 git 提交、会话活动、每日记忆生成周报/定期报告（进化的"体检报告"） |

**⑦ 目标与需求管理类（进化方向）**

| 插件 | ★ | 机制概述 |
|------|---|---------|
| **dsh-specflow** | 1 | 规格工件、skills、commands、**goal-backed 实施**、任务进度上下文 |
| **want-a-init** | 1 | 模型驱动 /init：分析仓库生成/更新 AGENTS.md，常驻 system prompt 提醒维护 |
| **dsh-global-rules** | 4 | 从 web 设置面板编辑全局 AGENTS.md 规则，保存即生效 |
| **awesome-dsh / dsh-find-plugin** | 0/28 | 把"需求"变成"插件选择"的 agent skill / 插件检索工具 |
| **mstar-harness** | 45 | Skill 驱动的 harness/loop 工程工作流 agent 插件 |

> **结论：DSH 生态已经具备自进化的"零件库"**——完整的进化回路（continual-evolve）、自我修改（evolve/genie）、验证（eval-harness）、治理（trajectory-governance/proof）、存储（memory 系列）、触发（sentinel/aura）、方向（specflow/REQ 模式）。但**缺乏一个把零件组装成"通用层 + 可定制层"统一框架的编排层**——这正是本框架的定位。详见第 5、6、7 节。

### 3.4 关键自进化插件的机制深挖（基于插件源码/README 验证）

以下机制的细节均来自对应插件 README 与源码结构的实际调研（本机已抓取并索引），是框架设计的直接依据。

**① dsh-continual-evolve（ZK-Andy）——最接近"完整进化框架"的参考实现**

五模块工作流（Sediment → Guard → Approve → Apply&inject → Validate&rollback）：

| 模块 | 机制（已验证） |
|------|--------------|
| **Sediment（沉淀）** | 模型用 `evolve_add` 主动创建条目；或**自动评审闸（auto review gate）**每隔 N 轮 turn（默认 6 轮）+ 压缩检查点，从会话轨迹自动提出候选 |
| **Guard（守门）** | **代码强制校验**（非提示词规则）：编辑 schema、爆炸半径/作用域一致性、晋升策略（项目作用域标记、内容过薄、近重复检测、**凭据筛查——每个写入口都拒绝密钥**）；全局创建的近重复（相似度 ≥0.8）在写入时直接拒绝，中度重叠带 conflictHint 供后续合并 |
| **Approve（审批）** | **全局写入必须显式人工批准**；本地作用域候选落地前也需咨询 |
| **Apply&inject（应用与注入）** | 原子应用 + 快照 + 审计事件；prompt notes / 委托规格**注入 system prompt**（封顶、相关性排序、被矛盾条目降级、空库时零 token）；memories/skills 以封顶目录索引出现 |
| **Validate&rollback（验证与回滚）** | 基准（benchmark）用**冻结用例 + 独立 scorer** 给候选打分；被拒候选**确定性回滚**（由应用结果生成逆编辑，不用 LLM 重新猜）并捕获为 draft regression cases（auto_regression benchmark） |

> 对本框架的启示：**"模型提议 + 代码保证"双层结构**是防误进化的核心——所有机械安全属性（schema/原子写/快照/版本/审计/回滚）由代码强制，LLM 只负责内容提议；跨会话全局写入必须有 promotion 门槛 + 人工批准。

**② dsh-rule-evolve（zoahdev）——验证驱动的规则进化**

```
经验(markdown) → learn → 规则(AGENTS.md) → verify(真实检查流水线)
```

- 经验条目 JSONL：`{ id, rule, source, tags, addedAt, verified, lastVerifiedAt }`，按规则哈希去重；
- `extract`：把失败日志（ERROR/failed/ERR_ 行）自动转成"当 X 出错时做 Y"的条件规则，跳过噪声行；
- `verify`：跑真实检查（默认 dsh-plugin-doctor check，`--cmd` 可插拔为任意"成功即退出 0"的命令），每条规则盖章 `verified: true/false`——**"没有经过检查的东西永远不会被学到"**；
- `tool-verify`：工具就绪门禁，失败的检查条目反过来成为经验（"带着失败发布教会下一个工具怎么不发布"）；
- 规则生命周期：`score`（验证数/使用数/时效 → active/stale）、`prune`（软淘汰，`retired: true` + reason 保留，**从不删除**）、`merge-duplicates`（Jaccard ≥0.7 近重复合并到高分区，`mergedInto` 保留）；
- 跨会话强化：`touch` 增 usageCount，verify/evolve 增 verifiedCount，**反复验证 + 反复使用的规则存活**；
- `recall`：零依赖 BM25-lite 检索（验证过且高频的规则排前，预留 embedding 接缝）；
- `dash`：生成可分享的 Agent 成长报告 HTML；`badge`：SVG 徽章（starting/learning/building/growing/legend 分级）；
- 与官方 #1881 三层持久记忆的 Layer 1（Git 托管的 Markdown 规则）对接，自称是"这一层的生产和验证半边"。

> 对本框架的启示：**验证与学习必须绑定**（无验证不学习）；软淘汰 + 近重复合并让规则库自维护而不失真；跨会话强化（touch/verify 计数）让"真有用的"规则自然存活——这就是"memory that forgets usefully"。

**③ plugin-evolve / deepseek-harness-evolver（shinjiyu）——工具插件的进化闭环**

- 状态机：**signals（信号）→ analysis（分析）→ abstract（抽象）→ stage（暂存）→ validate（校验）→ mount（挂载）→ score（打分）→ solidify（固化）| rollback（回滚）**；
- 信号聚合：`signal` 工具记录 tool_error 等；`analysis` 读最近 32 条信号按 kind+payload.tool 聚成进化点（ready/watching/blocked_trial/stagnant）；
- 安全策略：静态检查（只注入 tools、禁 network/shell、体积 ≤32KiB、模块黑名单 fs/net/http/child_process/eval/new Function）；`score` 真实运行打分（samples ≥10 且 successDelta >0 才固化）；
- 护栏：**同一时间最多一个 in-flight trial**；同一 signalKind 连续失败 3 次拒绝再 stage（停滞锁）；前 3 次 solidify 必须 `confirm: true` 人工确认；
- `evolve_mount` 用 `ctx.plugin` 热挂到当前进程，新工具**本轮会话立即可用**；固化后 `loadout` 让下一进程 import。

> 对本框架的启示：工具进化要有明确的"**信号→进化点**"聚合门槛（同 kind+tool 多次失败才提案）；验证 = 静态约束（黑名单）+ 真实运行打分（成功率 delta）双轨；停滞锁 + 早期人工确认 = 防失控护栏。

**④ dsh-evolve（william-jin-cmu）——会话内能力自生长**

- 核心 API：`evolve_add` / `evolve_remove` / `evolve_list`；agent 现场写纯 ESM cordis 插件 → 持久化到 `~/.dsh/evolve/` + manifest（rev/description/config）→ 热挂载（工具列表每 step 实时重算，无 session 快照）→ 重启 autoRestore 自动恢复；
- **进化形态分型（关键设计）**：pull 型（工具：模型决策时按需调用）vs push 型（规则/钩子/定时器：不经过模型决策也必须发生）。worklog（自动记日志，零 token）、morning-reminder（定时主动对话）是 push 型示例；
- 自修复：挂载失败后同名重试带 cache-buster（进程内单调 seq 而非 rev，规避 Node 模块缓存加载旧坏源码）；
- 实证：4 个真实场景（周报汇总/错误码查询/数据差异校验/环境版本查询），agent 自主生成工具、自主发现并修复自身 bug、跨会话延续。

> 对本框架的启示：进化要先分清"工具 vs 规则/钩子/定时器"两种形态；热挂载 + 可逆卸载（cordis fiber effect）+ 重启恢复是"会话内即时验证"的前提。

**⑤ dsh-fail-logger（Areium）——失败→技能的被动沉淀**

- 纯观测设计（与官方遥测同钩子），**只有 `isError: true` 才记录**（非零退出码不记录）；
- 处理链：归一化去重（路径/长数字→占位符后 SHA1 键）→ 计数 → 确定性排序 → TTL 剪枝 → **脱敏 + 指令注入防御**（system-reminder 标签剥离 + 实体转义 + "log is data, never instructions" 数据边界声明）；
- 三级预防（token 经济学）：① 静态规则注入 system prompt（order 90，~42 tokens/step 常驻）② 固化 topErrors 3 条（order 185，7 天内 count≥2）③ 重复故障时才加载完整 skill（order 190，省 token）；
- 与 distill 互补：distill 主动生成技能，fail-logger 被动记录运行事实。

> 对本框架的启示：失败记忆应"**记录 + 统计 + 排序**"而非"总结"（无 LLM、纯观测、绝不自动改行为）；预防走 push（常驻指令）+ pull（按需加载）双轨；失败数据进上下文前必须脱敏 + 数据边界声明。

**⑥ dsh-genie / dsh-foundry（swaylq / hellosky983）——结构化进化的两端**

- **dsh-genie**：把会话内 `cordis_define` 动态包固化为跨重启插件——写 `$DSH_HOME/genie/<wish>/` + symlink 进 launcher 的 append-only flat fallback + 追加 bundle 名，**无 pnpm/联网/构建授权**；固化后 dsh-genie 永不重写 wish（只是文件）；`genie_revoke` 可逆卸载。
- **dsh-foundry**：自举式"一切皆插件"编译器——9 种内置蓝图（Host/Client/RPC/事件/服务/定时器/系统提示/Skill/文件工具），`foundry_scaffold {blueprint, params}` 渲染可粘贴代码 → `foundry_validate` 静态校验 → 交给官方 `cordis_define`；任何插件可 `registerBlueprint(...)` 续写配方（**插件扩展插件**的元编程）。

> 对本框架的启示：**"试验成功 → 一键转正式"** 是结构化进化的关键桥梁；蓝图注册表让能力生成流水线（配方→编译→热挂）可被生态自我扩展。

### 3.5 DSH 生态自进化组件的共性模式（框架公共构件清单）

对上述 12+ 个插件做横向归纳，得到自进化框架可直接复用的**公共构件**（第 6 节通用层将逐一对应）：

| # | 公共构件 | 代表插件 | 第 6 节模块 |
|---|---------|---------|------------|
| 1 | **演化状态存储**：JSONL 事件日志 + 状态文件（.evolve/state.json、events.jsonl、reviews.jsonl、experience.jsonl）+ SQLite（FTS5/sqlite-vec） | rule-evolve / plugin-evolve / self-improved | G8 版本化 |
| 2 | **版本化与快照**：manifest rev、版本链、snapshot、EVOLUTION.md 进化日志、baseline 入库 | continual-evolve / eval-harness / rule-evolve | G8 |
| 3 | **确定性回滚**：逆编辑生成（非 LLM 重猜）、fiber dispose、软淘汰保留 reason、30s 防呆回滚 | continual-evolve / evolve / rule-evolve / genome | G8 |
| 4 | **验证门禁**：真实检查（可插拔 --cmd）、冻结用例 + 独立 scorer、headless 回归 + baseline 对比、LLM judge 校准（TPR/TNR）、静态黑名单 + 真实运行打分 | rule-evolve / continual-evolve / eval-harness / plugin-evolve | G6/G7 |
| 5 | **晋升/推广护栏**：作用域标记、内容最小长度、近重复拒绝、凭据筛查、全局写人工批准、所有权标记（distilled-by）、早期固化人工确认、停滞锁 | continual-evolve / distill / plugin-evolve / genome | G9 |
| 6 | **成本治理**：push 常驻指令（小 token/step）+ pull 按需 skill、廉价维护循环 vs 夜间全量进化、TTL/衰变/剪枝/归档、空库零注入 | fail-logger / self-improved / rule-evolve / continual-evolve | G6/G9 |
| 7 | **防指令注入与脱敏**：redact、数据边界声明（data never instructions）、实体转义 | fail-logger | G9 |
| 8 | **隔离与并发**：per-case session root + workspace overlay、跨进程锁合并、并发子进程 | eval-harness / fail-logger | G6 |
| 9 | **健康/成长可视化**：agent-growth.html、SVG badge、基因组 Web UI、记忆浏览器、report.md | rule-evolve / genome / eval-harness / self-improved | G9 |
| 10 | **进化形态分型**：pull 工具 vs push 规则/钩子/定时器 | evolve | G5 |

---

## 4. 本项目已有的"事实自进化系统"

本项目（A 股投研）已经以每日复盘 Harness + DSH headless 自动化跑通了一套完整的自进化系统（见 CLAUDE.md 第七节与本仓库 `my_doc/每日复盘/harness/`）。它是本框架"可定制层"的最佳现实原型。

### 4.1 每日复盘 Harness 架构

```
my_doc/每日复盘/
├── harness/                     # 厨房（进化资产）
│   ├── prompts/                 #   永久模板（方法论框架，低频优化）
│   ├── experience/              #   经验沉淀（投资经验 86KB / 短线经验 / 报告审阅经验）
│   ├── config/                  #   日度配置（持仓快照）
│   ├── staging/                 #   当日可执行 prompt（每日覆盖，消灭副本）
│   ├── archive/                 #   历史 prompt 归档
│   └── automation/              #   自动化层
│       ├── prompts/             #     10 个自动化任务 prompt
│       ├── steering/            #     REQ 工单（open/in_progress/closed + INDEX + TEMPLATE）
│       ├── bugs/                #     Harness BUG 跟踪
│       ├── lib/ + tests/        #     可测试 Python 库 + pytest（TDD 门禁）
│       └── logs/                #     执行日志
├── reports/{yyyyMMdd}/          # 菜（Artifact）
└── 每日调仓.md                   #   调仓审计日志
```

### 4.2 已实现的进化闭环

```
问题发现（evening_review / logic_inspect / experience_health / bug_inspect_*）
  → REQ 创建（steering/open/，含优先级/影响范围/期望结果/测试交付物）
  → 自动实施（req_implement 12:57 → dev-workflow 5 步：brainstorming→writing-plans→TDD→executing→code-review）
  → 效果验证（evening_review 第十三步：测试+复盘确认）
  → CLOSED + 经验沉淀（experience/ 无日期标签、融合、冲突修正）
  → 健康监控（experience_health 周三：大小/重复/矛盾/过时/章节完整性）
```

已内置的关键机制（全部与业界自进化研究的结论吻合）：

- **Generator-Monitor-Evaluator 分离**：早盘预测（Gen）→ 盘中验证触发（Mon）→ 复盘逐条对账（Eval），严格禁止自产自评；复盘带着"找茬"心态。对应业界"对抗自博弈"范式。
- **可验证承诺（每日信号）**：每条信号是"可验证承诺"，T+3 目标价结算（hit/stopped/miss）+ 质量仪表盘（8 项指标），复盘必须逐条对账，禁止选择性遗忘。→ 这是"领域验证器"的现实形态。
- **经验沉淀协议**：无日期标签、与旧经验融合、冲突则修正原条目、3-5 句话、可操作。
- **REQ 闭环 + 人工确认门禁**：OPEN → IN_PROGRESS → IMPLEMENTED → CLOSED（测试通过+用户确认）；MANUAL_REVIEW BUG 必须人工确认。
- **TDD 门禁**：无测试不得推进到 IMPLEMENTED。
- **报告审阅经验**：2-3 轮审阅（数据校验 → 逻辑一致性 → 完整性/格式），沉淀为可复用 checklist。
- **staging 机制**：用复盘结果生成次日完整可执行 prompt，每日覆盖，消灭 prompt 副本，保证"经验→执行"的低损耗传导。
- **headless 独立进程**：每次任务零上下文累积，崩溃自愈。
- **幂等双保险 + 失败透明**：scheduler_state.json + task_state.json；日志落盘。

### 4.3 对通用框架设计的启示

1. **"厨房/菜"分离 = 进化资产与产物的分离**：harness（可进化资产）与 reports（一次性产物）分开存放，进化只发生在 harness 层。
2. **Generator-Evaluator 分离是防止"自进化骗自己"的第一道防线**：评估者必须独立于生成者（不同时机、不同心态、甚至不同进程）。
3. **领域验证器是"正循环"的发动机**：A 股的 T+3 结算、信号命中率、做T 胜率校准，就是该领域的"奖励函数"。没有它，进化就没有方向。
4. **REQ 工单是"进化方向的显式化"**：用户注入 + 系统自发现双通道，带优先级与验收标准。
5. **经验库需要健康检查**：经验会膨胀、重复、矛盾、过时——需要定期体检（experience_health 周三任务）。
6. **进化必须留人工确认的闸门**：REQ CLOSED 需要用户确认，MANUAL_REVIEW 必须人工。

> 本框架的定位：把上述"项目特有实践"抽象为"通用层机制"（谁都能用），同时保留"可定制层"让用户定义自己的目标、指标、验证器与 REQ 通道（本项目即为一个定制实例）。

---

## 5. 自进化框架原理

### 5.1 核心回路：执行回路 × 改进回路

自进化框架的本质，是在 Agent 的**执行回路**之外，叠加一条**改进回路**：

```
【执行回路】（快，每次任务）
  用户目标 → Agent（Model + Harness）→ 执行任务 → Artifact 产出
                                                    │
                                                    ▼
【改进回路】（慢，周期性/事件驱动）                轨迹（session log / 运行记录 / 信号结算）
  感知 → 反思 → 产物生成 → 验证 → 生效 → 回滚/审计
    │       │        │        │      │
    │       │        │        │      └─► 影响下一次执行（注入/热重载/配置变更）
    │       │        │        └─► 验证不通过 → 丢弃或回滚
    │       │        └─► Skill / Memory / Rule / Workflow / Tool / Plugin / Test
    │       └─► Generator-Evaluator 分离的找茬式评估
    └─► 轨迹结构化 → 错误模式 → 经验候选
```

**关键原理：进化 = 把"执行回路产生的信息"转化为"harness 的持久变更"，且变更必须经过验证才能生效。**

改进回路六步：

| 步 | 名称 | 输入 → 输出 | 通用层模块 |
|----|------|------------|-----------|
| 1 | **感知（Sense）** | 轨迹/运行日志/结果结算 → 结构化事件流 + 差异信号 | G1 轨迹捕获、G2 经验沉淀原料 |
| 2 | **反思（Reflect）** | 事件流 → 归因（对了为什么对/错了为什么错/根因） | G3 错误模式库、G4 评审标准 |
| 3 | **产物生成（Generate）** | 反思结论 → 进化候选（skill 草案/经验条目/规则/流程改进/工具需求） | G5 产物生成器 |
| 4 | **验证（Validate）** | 进化候选 → 验证结果（headless 实验/测试/评审/用户确认） | G6 评估沙箱、G7 测试 |
| 5 | **生效（Apply）** | 验证通过的候选 → 写入 harness（版本化） | G8 版本化与生效 |
| 6 | **回滚/审计（Rollback/Audit）** | 全链路可追溯；异常可回退 | G8、G9 安全门禁 |

### 5.2 进化产物生命周期

```
候选（Candidate）→ 暂存（Staged）→ 验证（Validated）→ 生效（Applied/Active）→ 弃用（Deprecated）→ 移除（Removed）
     ↑                                                                                    │
     └──────────────────────── 健康检查发现退化 ←──────────────────────────────────────────┘
```

每个进化产物都有：**版本号、创建时间、来源轨迹引用（sessionId）、验证记录、生效状态**——即"可审计"。

### 5.3 DSH 底座能力映射

| 自进化需要 | DSH 提供 | 说明 |
|-----------|---------|------|
| 进化原料 | Session 轨迹（lossless log）、session/event 事件流 | 改进回路第 1 步的输入 |
| 能力载体 | SKILL.md（Markdown 能力容器，热重载、可注入） | 主要进化产物形态 |
| 经验存储 | Memory 插件（OpenViking / dsh-mneme / dsh-auto-memory …） | 事实/规律/教训 |
| 纪律载体 | AGENTS.md / 全局规则（dsh-global-rules） | Rule 类产物 |
| 流程载体 | 命令（commands）、自动化 prompts、headless 调度 | Workflow 类产物 |
| 器官载体 | Tool 插件、MCP server、cordis 插件（dsh-genie/dsh-evolve/dsh-foundry） | 结构性进化 |
| 验证沙箱 | `dsh --profile headless "…"` 独立进程 | 每次验证零上下文累积 |
| 验证器 | dsh-eval-harness（YAML 用例 + 断言 + baseline） | 通用验证；领域验证器由可定制层提供 |
| 生效通道 | agent/pre-step 注入、cordis.patch.yml、热插件挂载 | 注入/结构两层生效 |
| 治理 | dsh-proof（只读验收）、dsh-trajectory-governance、审批链（dsh-user-approval） | 防误进化 |

---

## 6. 框架设计：通用层

### 6.1 设计原则

1. **进化资产与产物分离**（厨房/菜分离）：只有 harness 资产可被进化修改，产物目录只读。
2. **Generator-Evaluator 分离**：进化候选的生成者与验证者必须隔离（不同时机/进程/角色），防止自产自评。
3. **一切进化可审计、可回滚**：每个产物带版本 + 来源引用 + 验证记录；任何变更可一键回退。
4. **验证先于生效**：无验证不生效；验证有门禁（测试/baseline/人工确认）。
5. **进化不越权**：进化只能修改允许进化的范围（权限沙箱）；涉及金融/安全/钱的决定必须人工确认。
6. **低损耗传导**：经验 → 执行之间减少中间损耗（staging 机制：生成"可直接执行的指令"而非"参考资料"）。
7. **健康检查常态化**：经验库/规则库/技能库定期体检，防膨胀、重复、矛盾、过时。

### 6.2 九个通用模块

```
通用层（Evolution Engine）—— 回答"怎么进化"
├── G1 轨迹捕获器（Sense）
├── G2 经验沉淀协议（Reflect 的知识写入侧）
├── G3 错误模式库（Reflect 的失败侧）
├── G4 质量评审标准（Reflect 的产出侧）
├── G5 进化产物生成器（Generate）
├── G6 评估沙箱（Validate：headless 实验）
├── G7 测试与门禁（Validate：TDD/baseline/回归）
├── G8 版本化、生效与回滚（Apply/Rollback）
└── G9 安全门禁与审计（Govern）
```

#### G1 轨迹捕获器（Sense）

- **功能**：把会话事件（session/event）、运行日志、任务结果结算，结构化沉淀为可检索的"进化原料"。
- **DSH 实现**：监听 `session/event` + `turn/end`，写入结构化轨迹库（或直接交给 Memory 插件）；关键字段：时间、会话、角色、工具调用、结果、错误、token 用量。
- **产物**：轨迹事件流 + 失败快照 + 差异信号（如"预测 vs 实际"结算表）。
- **通用需求覆盖**：任何 Agent 进化都要回答"上次发生了什么"。

#### G2 经验沉淀协议（Reflect 知识侧）

- **功能**：定义"什么经验值得写、怎么写、如何与旧经验融合、冲突如何处理"。
- **规则**（取自本项目经验协议，可泛化）：
  1. 无日期标签（只写规律本身）；
  2. 与原有经验融合，不重复记录；
  3. 冲突 → 修正原条目而非简单追加；
  4. 简洁（3-5 句）、可操作（直接指导行为，而非抽象哲理）；
  5. 每条经验附来源轨迹引用（可追溯）。
- **DSH 实现**：经验写入 Memory 插件的经验域（如 viking 的 experiences 域）或 harness/experience/ 文件。

#### G3 错误模式库（Reflect 失败侧）

- **功能**：失败 → 根因分类 → 教训 → 防复发规则。
- **DSH 实现**：借鉴 dsh-fail-logger（失败工具调用自动记录 + 根因去重计数）、MisakaNet（失败-恢复教训知识库）；失败快照进 G1，根因归纳进经验库，反复出现的根因升级为"规则"（Rule）。

#### G4 质量评审标准（Reflect 产出侧）

- **功能**：沉淀"什么样的产出算好"的 checklist（数据校验、逻辑一致性、完整性、格式）。
- **DSH 实现**：本项目已有 `报告审阅经验.md`（2-3 轮审阅：数据校验 → 逻辑一致性 → 完整性/格式），可作为通用模板；各领域可扩展自己的评审维度。

#### G5 进化产物生成器（Generate）

- **功能**：把反思结论转化为**进化候选**，并打上"候选"标签进入暂存区（不直接生效）。
- **产物类型**（对齐四大支柱 + 验证器）：
  - Skill 草案（新增/改进 SKILL.md）
  - Memory 经验条目
  - Rule 规则草案（AGENTS.md）
  - Workflow/命令改进提案
  - Tool/插件需求提案（交给人或 dsh-foundry 类工具实施）
  - Test/Eval 用例（伴随每个能力变更）
- **DSH 实现**：提供 `evolve_propose` 工具（模型可调用）；产物写入 `evolution/staging/`。

#### G6 评估沙箱（Validate 实验侧）

- **功能**：在隔离环境验证进化候选是否真的变好。
- **DSH 实现**：
  - **headless 实验**：`dsh --profile headless "<候选 skill 场景的测试任务>"`，对比候选 vs 当前的输出；
  - **forkprobe 式对比**：同一任务跑多个 skill 变体，选胜者；
  - **dsh-eval-harness**：YAML 用例驱动 + 断言 + baseline 门禁；
  - **回归**：旧用例全量重跑，防止进化引入退化。
- **通用需求**：任何进化都必须回答"它真的变好了吗，还是只是这次凑巧"。

#### G7 测试与门禁（Validate 工程侧）

- **功能**：对"代码/脚本/流程"类进化施加工程门禁。
- **规则**：TDD（先测试后实现）、全量回归通过、无测试不得生效。
- **DSH 实现**：复用 dev-workflow（brainstorming → writing-plans → TDD → executing-plans → code-review）+ pytest 测试套件（本项目已有）。

#### G8 版本化、生效与回滚（Apply/Rollback）

- **功能**：管理进化产物的生命周期（候选→暂存→验证→生效→弃用→移除），支持热生效与一键回滚。
- **DSH 实现**：
  - Skill/经验/规则：版本化文件（git 或带版本头的文件）+ 热重载；
  - 插件级：dsh-genie（固化 cordis_define）、dsh-evolve（会话内热挂载）、deepseek-harness-evolver（stage→validate→mount→score→solidify/rollback）；
  - 配置级：cordis.patch.yml 补丁层（可审计、可禁用）。
- **通用需求**：进化出错是常态，回滚能力是底线。

#### G9 安全门禁与审计（Govern）

- **功能**：防止"误进化"（misevolution）：奖励黑客、记忆污染、工具自伤、工作流退化、目标漂移。
- **机制**：
  1. **人工确认闸**：涉及钱/金融/安全/身份/删除类变更必须人工确认（REQ CLOSED 需用户确认；MANUAL_REVIEW 必须人工）；
  2. **只读验证者**：dsh-proof 式独立只读验收，fail-closed；
  3. **双模型复核**：dsh-auto-review 式第二模型裁决；
  4. **审计日志**：每个产物带来源引用 + 变更记录（git commit / evolution log）；
  5. **进化边界**：明确"可进化范围"白名单（哪些目录/文件/技能允许被自动修改），越权拒绝；
  6. **健康检查**：定期体检经验库/规则库（大小/重复/矛盾/过时），发现退化自动标 Deprecated。

### 6.3 目录结构建议

```
<workspace>/
├── .agents/                          # 现有：技能/命令/记忆（进化产物的一部分）
├── evolution/                        # 自进化框架目录（新增，通用层）
│   ├── README.md                     #   框架说明
│   ├── config/
│   │   ├── evolution.yml             #   框架配置（开关/权限边界/调度）
│   │   └── goals.md                  #   用户目标定义（可定制层入口，见第 7 节）
│   ├── staging/                      #   进化候选暂存区（待验证）
│   │   ├── skills/                   #     skill 草案
│   │   ├── rules/                    #     规则草案
│   │   ├── workflow/                 #     流程改进提案
│   │   └── tools/                    #     工具/插件需求提案
│   ├── validated/                    #   验证通过、待生效
│   ├── active/                       #   已生效资产（软链/索引到真实位置）
│   ├── audit/                        #   审计日志（每次变更的记录 + 来源引用）
│   └── health/                       #   健康检查报告
├── harness/                          # （领域实例，如 my_doc/每日复盘/harness/）
└── reports/                          # 产物（只读）
```

---

## 7. 框架设计：可定制层

可定制层回答"**往哪进化**"——用户通过目标定义，把通用进化引擎（第 6 节）导向自己关心的方向，并建立"目标 → 反馈 → 改进 → 目标达成"的正循环。

### 7.1 目标定义体系

```
goals.md（用户编写，框架读取）
├── 愿景（Vision）        # 一句话：这个 Agent 最终要成为什么
├── 目标（Goals）         # 3-5 条中期目标，每条含：
│   ├── 指标（Metrics）   #   可量化的成功指标（KPI），如"信号命中率 ≥ 45%"
│   ├── 验证器（Verifier）#   如何结算该指标（领域特有，如 T+3 结算脚本）
│   ├── 进化方向（Direction）# 优先改进哪个支柱（skill/经验/流程/工具）
│   └── 权重（Weight）    #   目标间的优先级
├── 边界（Boundaries）    # 禁止进化的方向 / 红线（如"不做短线妖股""不碰融资"）
└── 节奏（Cadence）       # 何时体检、何时复盘、何时允许自动实施
```

**设计要点：**

- 目标是"可结算"的：每条目标必须有对应指标和验证器，否则进化无法判断是否在进步（正循环的发动机）；
- 边界是显式的：明确"不进化什么"，防止误进化与目标漂移；
- 用户只需维护 goals.md 与验证器，其余由通用层自动运转。

> 配套示例：本仓库 `evolution/config/goals.example.md` 提供了以 A 股投研为领域的完整填写示例（4 条目标 × 指标/验证器/方向/权重 + 边界红线 + 节奏），可直接复制为 `goals.md` 使用。

### 7.2 进化方向引导

| 引导机制 | 说明 | 对应通用层 |
|---------|------|-----------|
| **目标指标反哺** | 每次结算后，指标变化决定下一个进化周期优先改进哪支柱（命中率低 → 优先优化信号 skill；报告质量低 → 优先优化评审标准） | G1 感知（结算结果作为差异信号） |
| **REQ 工单双通道** | 用户手动注入（steering/open/）+ 系统自发现（复盘/巡检发现架构性问题自动建单），带优先级与验收标准 | G5 产物生成器 |
| **经验库健康体检** | 体检发现经验过时/矛盾 → 自动生成"修正 REQ" | G9 健康检查 |
| **用户对话信号** | 用户纠正、抱怨、表扬 → 结构化进"进化方向日志"（如"用户三次说报告太长"→ REQ） | G1 感知 |
| **领域验证器驱动** | 验证器（如 T+3 结算）持续产出的数据是进化的"奖励信号"，决定哪些经验/规则被强化或淘汰 | G6 评估沙箱 |

### 7.3 正循环设计

正循环 = 目标指标被持续结算 → 反馈驱动改进 → 改进被验证 → 指标上升 → 确认进步 → 进入下一目标。

```
        ┌────────────────────────────────────────────────────────┐
        ▼                                                        │
   [目标定义] goals.md（指标 + 验证器 + 方向 + 权重）              │
        │                                                        │
        ▼                                                        │
   [执行回路] 日常任务（headless/会话）→ 产出 Artifact + 轨迹      │
        │                                                        │
        ▼                                                        │
   [结算] 领域验证器（如 T+3 结算 / 报告评分）→ 指标更新           │
        │                                                        │
        ▼                                                        │
   [差距分析] 指标 vs 目标 → 差距最大的方向 → REQ/进化候选         │
        │                                                        │
        ▼                                                        │
   [改进回路] 候选 → 验证（headless/eval-harness/TDD）→ 生效       │
        │                                                        │
        ▼                                                        │
   [确认] 用户确认 + 健康检查 → 指标复测                          │
        │                                                        │
        └── 指标达标 → 标记目标完成 → 用户定义下一目标 ───────────┘
```

**防漂移设计**（正循环不变成死循环或乱循环）：

- 每轮进化必须回答"这轮改了什么、为什么、验证了什么、指标怎么变"（进化周报）；
- 连续 N 轮指标无改善 → 暂停该方向，回退最近变更，换方向（负反馈）；
- 目标指标不达标不意味着失败——检查是"指标设置问题"还是"能力不足"（区分目标问题与执行问题）；
- 用户随时可以暂停/重定向（进化框架不剥夺人的控制权）。

### 7.4 用户交互点与门禁

| 交互点 | 时机 | 用户动作 |
|--------|------|---------|
| 目标编辑 | 任意时刻 | 改 goals.md（或说"改目标：……"，由框架代写） |
| REQ 注入 | 任意时刻 | 说"提个需求：……" → 生成 REQ 工单 |
| 进化候选确认 | 候选验证通过后 | 批准 / 拒绝 / 修改（影响面大的必须人工） |
| 指标复测确认 | 每轮进化结束后 | 确认"这次进化确实变好了"（REQ CLOSED 需用户确认） |
| 健康检查 | 定期 | 查看体检报告，决定是否清理/修正 |
| 回滚 | 任意时刻 | "回滚最近一次技能变更" |

> 可定制层的"用户"既可以是人，也可以是上层系统（如把本框架作为某业务 Agent 的进化子模块，由业务方注入目标与验证器）。

---

## 8. 自进化的产物是什么

> 这是本框架最值得深思的问题。分三层回答。

### 8.1 直接产物：Harness 资产的持久变更

自进化"生成"的东西，首先是 **harness 层可持久化、可版本化、可继承的能力资产**：

| 产物类型 | 载体 | 回答的问题 | 例子（本项目） |
|---------|------|-----------|--------------|
| **能力（Skill）** | SKILL.md | "怎么做" | a-stock-data、daily-review-harness |
| **知识（Memory/经验）** | 记忆库/经验文档 | "知道什么" | 投资经验 86KB、报告审阅经验 |
| **纪律（Rule）** | AGENTS.md/规则文件 | "什么不能做 / 必须做" | 数据铁律（走 a-stock-data）、Generator-Evaluator 分离 |
| **方法论（Workflow）** | 模板/命令/自动化 prompt | "按什么流程做" | 复盘模板、REQ 闭环流程 |
| **器官（Tool/Plugin）** | 工具/插件/MCP | "能用什么新工具" | 数据取数工具、结算脚本 |
| **验证器（Test/Eval）** | 测试用例/eval 用例 | "怎么证明没变坏" | pytest 套件、T+3 结算 |
| **经验教训（Lesson）** | 错误模式库条目 | "上次错在哪" | 误把盘中价当收盘价 |

### 8.2 间接产物：更好的 Artifact

进化最终要体现在**用户可见的产出质量提升**上：更准的信号、更完整的报告、更少的重复错误、更快的任务完成。Artifact 是进化的"果"，不是进化的"体"。

### 8.3 本质产物：能力增量的累积 + 进化元能力（进化自举）

我认为自进化最本质的产物是**一条持续上升的"能力曲线"**，其构成是两类东西：

1. **能力增量（Capability Delta）**：每一次进化都在 harness 里留下一块"可复用的能力增量"——从**一次性正确的输出（Artifact）→ 可重复的能力（Skill）→ 自动化的方法（Workflow）→ 结构性的新器官（Tool/Plugin）**。这是一个"从结果到能力再到结构"的升维过程：Artifact 是一次性的，Skill 是可复用的，Workflow 是自动化的，Organ 是结构性的。自进化做的就是把"这次偶然做对的事"变成"下次必然能做的事"。

2. **进化元能力（Meta-capability of Evolving）**：最重要的产物是 Agent 学会了**"如何进化"**——如何发现问题、如何归因、如何沉淀、如何验证、如何防止自己骗自己。当这个元能力形成后，进化就**自举**了：Agent 不仅能解决领域问题，还能持续改进自己解决领域问题的方式。**自进化最终的产物，是一个"会进化的 Agent"本身，而不只是它攒下的那些文件。**

**一句话回答：Agent 自进化的产物 = 把"这次的经验"固化为"下次的能力"，最终固化出"自我改进的能力"。** 生成的是 Skill（能力）、Memory（知识）、Rule（纪律）、Workflow（方法）、Tool（器官）、Test（验证），以及贯穿其中的"进化轨迹与信任记录"（每个产物带来源、版本、验证记录）——一个可审计、可继承、可进化的 harness 层"基因组"。

> 类比：Artifact 是"今天的晚餐"（吃完了就没了）；Skill 是"菜谱"（下次还能做）；Workflow 是"厨房流水线"（不用想就能做）；Organ 是"新厨具"（能做以前做不了的菜）；进化元能力是"会学习做饭的人"（自己发明新菜）。自进化框架要经营的是后四者，而用户最终吃到的是更好的晚餐。

---

## 9. 落地路线图与风险

### 9.1 落地路线图（建议分四期）

| 阶段 | 内容 | 交付物 |
|------|------|--------|
| **P0 基线盘点** | 把本项目已跑通的机制（复盘闭环/REQ/经验协议/健康检查）整理为通用层文档与模板；确认进化边界（哪些目录可自动修改） | `evolution/` 目录 + goals.md 模板 + 通用层 README |
| **P1 通用层最小闭环** | G1 轨迹捕获（接 session 日志/结算表）→ G2 经验沉淀 → G5 候选生成 → G6 评估沙箱（headless 对比）→ G8 版本化回滚；接入 daily-review-harness 作为首个定制实例 | 最小进化回路跑通：一次"发现经验→沉淀→验证→生效→回滚"全流程 |
| **P2 可定制层完整化** | goals.md 目标体系 + 指标结算自动化 + 差距分析驱动 REQ + 进化周报 + 用户门禁交互 | 目标驱动的正循环：指标连续 2-4 周可视化上升 |
| **P3 结构化进化** | 接入 dsh-genie / dsh-foundry / dsh-evolve 类能力，支持 Skill/插件级热挂载；接入 dsh-eval-harness 做通用验证器；多 profile 间进化资产共享（一个 Agent 的经验沉淀给另一个 Agent） | Agent 能自主创建/挂载新工具，进化资产跨 Agent 复用 |

### 9.2 风险与对策

| 风险 | 表现 | 对策 |
|------|------|------|
| **误进化（Misevolution）** | 奖励黑客、记忆污染、工作流退化、目标漂移 | G9 全套：人工闸、只读验证者、双模型复核、审计日志、进化边界、健康检查 |
| **经验库膨胀/矛盾** | 经验越来越多但越来越没用 | G2 融合协议 + 定期健康检查 + 弃用机制 |
| **进化噪音** | 每个小波动都触发进化，改了又改 | 进化节奏控制（定时批处理而非实时）；差异信号设阈值；连续无改善自动回滚 |
| **上下文负担** | 注入过多经验/技能，token 成本上升、注意力稀释 | pre-step 按需召回（分数阈值 + token 预算）；skill 渐进式披露（先索引后全文） |
| **评估作弊** | 进化针对验证器钻空子 | 验证器与生成者隔离；多验证器交叉；定期更新验证器（领域验证器本身也可进化） |
| **人失去控制** | 系统自动改了一堆东西用户不知道 | 进化周报 + 所有变更可回滚 + 高影响变更必须人工确认 |
| **安全越权** | 进化产物修改了不该碰的东西 | 进化边界白名单 + 权限沙箱 + tools/pre-execute 护栏 |

### 9.3 与现有生态的关系

- **本框架 = 编排层**：不重复造轮子，把 DSH 生态已有的零件（continual-evolve / evolve / genie / eval-harness / memory 系列 / sentinel / specflow …）按"通用层 + 可定制层"组织起来；
- **本框架 ≠ 某个插件**：它更像一个"进化运行时的规范 + 参考实现"，以 `evolution/` 目录 + 一组约定（协议/模板/门禁）落地，具体执行由 DSH 的 skill/命令/插件机制承载；
- **与用户既有系统兼容**：daily-review-harness 的 REQ/经验/健康检查机制继续作为领域实例运行，框架负责抽象通用部分并让更多领域复用。

---

## 10. 参考资料

### 业界研究

- arXiv 2507.21046《Self-Evolving Agents: A Systematic Survey》 — 自进化 Agent 系统综述，四大可进化支柱（Model/Context/Tools/Workflow）
- arXiv 2305.16291《Voyager: An Open-Ended Embodied Agent with LLMs》 — 自动课程 + 技能库 + 自验证
- arXiv 2303.11366《Reflexion: Language Agents with Verbal Reinforcement Learning》 — 口头强化学习/反思记忆
- Shilong Liu《A Taxonomy of Self-evolving Agents》（2026） — Model/Harness/Artifact 三层、三级进化（artifact 迭代/harness 自改进/model 无金标学习）
- arXiv 2509.26354《Your Agent May Misevolve》 — model/memory/tool/workflow 四路径误进化风险
- agent-evolution.com《Self-Evolving AI Agents: A Survey of Feedback-Driven Generation, Evaluation, Memory, and Self-Modification》 — 五种进化回路 + Evolve-AGI Index
- arXiv 2603.18000《AgentFactory: A Self-Evolving Framework Through Executable Subagent Accumulation and Reuse》 — 可执行子代理代码作为进化产物
- arXiv 2604.27660《Ctx2Skill》 — 上下文蒸馏为技能（5 角色自博弈）
- OpenSkill（2026）— 开放世界技能自进化：锚点知识 + 虚拟任务验证
- MUSE-Autoskill（arXiv 2605.27366）— 技能创建/记忆/管理/评估全生命周期
- AlphaEvolve / MAP-Elites — 质量-多样性档案（保留多样变体，多目标）

### DSH 生态（插件注册表 dshmarket registry-snapshot.json，2026-08 快照，839 个插件）

- dsh-continual-evolve（ZK-Andy）— 版本化/可回滚 harness 状态从轨迹提炼，评审门禁 + 热重载
- dsh-evolve（william-jin-cmu）— 会话内热挂载/移除持久插件
- dsh-rule-evolve（zoahdev）— 失败日志→验证过的 AGENTS.md 规则
- deepseek-harness-evolver（shinjiyu）— stage→validate→mount→score→solidify/rollback
- dsh-genie（swaylq）— cordis_define 动态插件固化为跨重启正式插件
- dsh-foundry（hellosky983）— 插件编译器（scaffold→validate→deploy）
- dsh-fabric（hellosky983）— 声明式 DSL 统一 DSH 扩展缝
- distill（LoserFox）— 后台反思 + skill 创建/更新
- forkprobe（Jayden-X-L）— 同任务多 skill 对比选优
- dsh-fail-logger（Areium）— 失败工具调用根因沉淀为 skill
- dsh-eval-harness（BiBoyang）— YAML 用例驱动 headless 评估 + baseline 门禁
- dsh-trajectory-governance / dsh-proof / dsh-devtools — 轨迹治理/只读验收/运行时剖析
- hindsight（vectorize-io，20011★）、dsh-mneme、dsh-auto-memory、dsh-mnemon、MisakaNet — 记忆/经验存储
- dsh-sentinel / dsh-aura-scheduler / dsh-automation — 调度与触发
- dsh-specflow / want-a-init / dsh-global-rules — 目标与规则管理
- @openviking/dsh-memory-plugin（本机已装，本会话在用）— 记忆捕获/召回/注入的参考实现（pre-step 注入、viking URI 保护）

### 本机 DSH 运行时（解剖依据）

- `@deepseek-ai/dsh` v0.1.0-rc.6（launcher：profile boot + plugin management + web alias）
- `~/.dsh/profiles/web/` cordis.yml / cordis.patch.yml / package.json（bundle 树）
- `~/.dsh/profiles/web/node_modules/@openviking/dsh-memory-plugin/`（index.mjs 事件钩子：agent/session-start、agent/pre-step、session/event、turn/end、tools/pre-execute）
- `~/.agents/`（skills 29 个 / memories / commands / scripts / skill-manage.json）
- 本项目 `my_doc/每日复盘/harness/`（daily-review-harness skill、REQ steering、经验库、自动化闭环）

---

*（本文档为研究稿 v0.1；后续将按 P0→P3 路线图落地 `evolution/` 目录与通用层模块。）*
