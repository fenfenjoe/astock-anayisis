# 小满 Persona — 指针文档（源已上移）

> ⚠️ **本文件不再是 persona 的单一事实源。**

## 源已上移（P1 小满解耦，2026-09-24）

小满人设的**单一事实源**已迁移到用户级目录：

```
~/.dsh/personas/xiaoman/persona.md
```

运行时配置（`~/.dsh/profiles/xiaoman/cordis.patch.yml` 的 `config.persona`）由同步脚本从源文件重生成：

```bash
python scripts/sync_xiaoman_persona.py            # 同步（自动备份 .bak）
python scripts/sync_xiaoman_persona.py --check    # 检查是否一致
python scripts/sync_xiaoman_persona.py --dry-run  # 预览
```

## 为什么上移

- 小满是 **Agent（persona）**，资产应归 Agent 层（用户级），而非耦合在 astock 项目（workspace 层）
- 此前"项目内改 → 手工同步 ~/.dsh"易漏、易漂移（源文件 87 行 vs 运行时内联版已不一致）
- dsh 的 persona 是纯字符串配置（不支持文件路径加载），故采用"源文件 + 同步脚本重生成"模式

## 改人设的流程（新）

1. 编辑 `~/.dsh/personas/xiaoman/persona.md`（注意 `<!-- RUNTIME:START/END -->` 标记内的内容才是运行时注入的）
2. 运行 `python scripts/sync_xiaoman_persona.py` 同步到运行时配置
3. （可选）`dsh --profile xiaoman --dump-config` 验证生效

## 本目录其他文件

- `behaviors.md` / `reading.md`：小满行为/学习素材（非运行时 persona，保留在项目内作为参考）
- 历史版本：见 git 历史（本文件上移前的完整内容）

---

> 关联：`docs/Agent自进化框架研究.md`、`evolution/design/P1-小满解耦-persona上移与记忆peer修正.md`
