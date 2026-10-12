# P1 设计：小满解耦 — persona 上移 + 记忆 peer 修正

> 自进化框架 P1（第二阶段）
> 依据：用户决策「小满=全部剥离（含领域知识抽包）」+「文件引用模式」「显式 peer=xiaoman」
> 目标：把"小满资产耦合在 astock 项目里"改为"小满 Agent 资产归 Agent 层"——人格与记忆独立于项目，可跨项目迁移。
> 日期：2026-09-24 | 状态：**已实施（迁移完成 + 测试 + dump-config 验证）**

## 〇、实施结果

**验收标准全部达成：**
1. `~/.dsh/personas/xiaoman/persona.md` 存在（单一事实源，RUNTIME 标记版，含完整红线/谈财经量化经验）✅
2. `scripts/sync_xiaoman_persona.py` 幂等 + 备份 + dry-run + check ✅（8 项测试）
3. `~/.dsh/profiles/xiaoman/cordis.patch.yml` 的 `config.persona` = 源文件 RUNTIME 块内容（dump-config 验证含"量化经验"新行）✅
4. openviking-memory `peerId: xiaoman`（直接 patch 覆盖，dump-config 验证生效）✅
5. 项目 `etf-strategies/agent/personas/xiaoman/persona.md` 降级为指针文档 ✅
6. `dsh --profile xiaoman --dump-config` 验证配置合法 ✅
7. 全量测试 **598 passed, 1 skipped**（+8 项 P1）✅

**实施产物清单：**
- `~/.dsh/personas/xiaoman/persona.md`：新建（单一事实源，含 RUNTIME 标记）
- `scripts/sync_xiaoman_persona.py`：新建（提取 RUNTIME 块 → 重写 cordis.patch.yml config.persona）
- `~/.dsh/profiles/xiaoman/cordis.patch.yml`：persona 同步 + 追加 openviking-memory-runtime `peerId: xiaoman` patch
- `etf-strategies/agent/personas/xiaoman/persona.md`：降级为指针文档（源已上移说明 + 同步方法）
- `tests/test_sync_xiaoman_persona.py`：新增（8 项）

**关键技术决策/发现：**
1. **dsh persona 是纯字符串**（`z.string()`，不支持文件加载）→ "文件引用模式"落地为"源文件 + 同步脚本重生成内联"
2. **sync 脚本初版 bug**：按"下一个 `- id:`"定位 persona 块结尾 → 吃掉模型路由注释。修复为按**缩进结束**定位（6 空格缩进行 + 空行属块内，其余块外）。已加回归测试（test_replaces_persona_block_keeps_rest）
3. **peer 修复用直接 patch 而非 insert**：`- insert:` 是向 group config push 追加（会重复实例化插件）；直接 `- id: openviking-memory-runtime` 覆盖其 config 才是正确语义（cordis-plugin-include：buildMap 递归进 group，非 insert patch 按 id override）
4. **peer 解析优先级**（workspace-peer.mjs）：`cfg.peerId` 显式 → workspace 派生 → none。显式 peerId=xiaoman 后，小满记忆命名空间固定为 user/default/peers/xiaoman/...

**验证证据：**
- `dsh --profile xiaoman --dump-config`（node 绕过 ps1 执行策略）：dump 出 persona 含"量化经验"新行 + `openviking-memory-runtime config: peerId: xiaoman`
- sync 幂等：重跑报"无差异"；备份 .bak 已生成

## 一、耦合现状（已查证）

| 资产 | 现状 | 耦合点 |
|------|------|--------|
| **persona 源** | `etf-strategies/agent/personas/xiaoman/persona.md`（87行完整版，6.6KB） | 单一事实源在项目里，文件头写明"改完需同步到 ~/.dsh"（手工同步） |
| **运行时 persona** | `~/.dsh/profiles/xiaoman/cordis.patch.yml` 的 `config.persona`（内联精简版） | dsh system-prompt schema 是 `persona: z.string()`（纯字符串，**不支持文件引用**）；内联版与源文件**已不一致**（缺"谈财经时"的量化经验引用等） |
| **记忆归属** | OpenViking peer 默认从 workspace 派生：`E--ideaworkspace-astock-anayisis` | `resolveEffectivePeerId`：cfg.peerId 显式优先 → workspace 派生 → none；当前无显式 peerId |
| **记忆内容** | `~/.agents/memories/MEMORY.md`（用户级，跨项目工程经验） | 已是用户级组织（无需动） |

**机制根因（memory-plugin config.mjs / workspace-peer.mjs）：**
```js
resolveEffectivePeerId: explicit(cfg.peerId) → workspace(deriveWorkspacePeerId(cwd)) → none
deriveWorkspacePeerId(cwd) = cwd.replace(/[^A-Za-z0-9]/g, '-')  // 产生 E--ideaworkspace-astock-anayisis
```

## 二、设计方案（用户已确认：文件引用模式 + 显式 peer=xiaoman）

### 2.1 P1a：persona 上移 + 同步脚本

由于 dsh persona 是纯字符串（不支持文件加载），"文件引用模式"落地为：
**源文件上移 `~/.dsh/personas/xiaoman/persona.md`（单一事实源）+ 同步脚本从源文件重生成运行时内联 persona**。

```
~/.dsh/personas/xiaoman/persona.md     ← 单一事实源（完整人设卡）
        │  sync_xiaoman_persona.py（提取"运行时注入"部分）
        ▼
~/.dsh/profiles/xiaoman/cordis.patch.yml  ← config.persona 内联块（运行时实际注入）
```

- 同步脚本：`scripts/sync_xiaoman_persona.py`
  - 读 `~/.dsh/personas/xiaoman/persona.md` → 提取 persona 文本 → 重写 cordis.patch.yml 的 `config.persona`
  - 幂等（重跑结果一致）+ 备份（改前复制 .bak）+ dry-run（--dry-run 预览）
  - persona.md 用 `<!-- RUNTIME:START -->` / `<!-- RUNTIME:END -->` 标记运行时注入范围（人设卡里的元信息/迭代历史不进运行时）
- 项目 `etf-strategies/agent/personas/xiaoman/` → persona.md 降级为**指针文档**（说明源已上移 + 同步方法），behaviors.md / reading.md 保持（它们是学习/行为素材，非运行时 persona）

### 2.2 P1b：记忆 peer 修正

在 `~/.dsh/profiles/xiaoman/cordis.patch.yml` 增加 openviking-memory 插件 config：

```yaml
- insert:
    - id: openviking-memory
      name: '@deepseek-ai/cordis-plugin-group'
      config:
        peerId: xiaoman
```

或 env `OPENVIKING_PEER_ID=xiaoman`（profile 启动环境）。效果：
- 小满记忆 peer 固定为 `xiaoman`（OpenViking 命名空间 user/default/peers/xiaoman/...）
- 与 astock workspace peer 分离，跨项目迁移时记忆跟随小满
- `recallPeerScope` 保持默认 `all`（可召回其他 workspace 的公开记忆，不隔离）

### 2.3 迁移与回滚

- **迁移**：备份现有 cordis.patch.yml → 改 → `dsh --profile xiaoman --dump-config` 验证 YAML 合法 + persona 生效
- **回滚**：.bak 还原 + 删 persona 源（源文件内容已在 git 历史/备份中）

## 三、验收标准

1. `~/.dsh/personas/xiaoman/persona.md` 存在，内容 = 项目 persona.md 完整版
2. `sync_xiaoman_persona.py` 幂等（dry-run 两次 diff 为空）+ 备份机制
3. `~/.dsh/profiles/xiaoman/cordis.patch.yml` 的 `config.persona` = 源文件运行时标记内的内容
4. openviking-memory 配置 `peerId: xiaoman`（profile 级）
5. 项目 `etf-strategies/agent/personas/xiaoman/persona.md` 降级为指针（明确标注源已上移）
6. `dsh --profile xiaoman --dump-config` 验证配置合法

## 四、后续衔接

- **P3**：小满领域包抽取 `~/.agents/domains/finance/`（persona 上移后的自然延伸）
- 记忆迁移：历史 peer（astock workspace）记忆 → 可选合并进 xiaoman peer（保守：保留原地，新记忆走新 peer）

## 五、风险

- persona 从精简内联版升级为完整版 → 运行时 prompt 变长（token 成本略升）；行为可能略变（更完整的红线/谈财经指引）——属预期内的"对齐源文件"
- openviking-memory 0.2.1（xiaoman）与 0.1.0（web）config 兼容性：peerId 字段两版都有（input.peerId 解析）
- 同步脚本破坏 cordis.patch.yml → .bak 兜底 + dump-config 门禁
