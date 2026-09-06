# xhs_scroll — 模拟人类"刷小红书"的最小工具（Playwright + 系统 Chrome）

> 目的：给小满 / Agent 一个能真正"读小红书信息流/搜索/笔记正文"的工具——用**你的真实登录态**，
> 以**人类的滚动节奏**浏览，把笔记结构化落盘（JSONL / Markdown），供后续喂给小满的知识管道。
> 选型依据与替代方案见 `docs/小满-小红书刷读工具调研.md`。
> 实测样例：`examples/feed-sample.jsonl`（feed 卡片 3 张）、`examples/sample-note.md`（单篇笔记）。
> `data/` 只放运行时登录态与输出（已 gitignore，含敏感 cookie，勿提交）。

## 原理（为什么这么稳）

- 小红书 web 端所有内容接口都要 x-s/x-t 签名，纯脚本请求基本不可行。
- 本工具不逆向签名：它用 **Playwright 驱动你本机已装的 Chrome**（免下载浏览器内核），
  页面自己会完成登录、签名、发请求；我们只**监听并抓取页面自身发出的接口响应**（homefeed /
  search / feed / comment），再整理成结构化卡片。
- 匿名无登录态什么都拿不到（页面是登录墙）→ 需要 `login` 一次扫码，之后复用 `data/session.json`。

## 环境与安装（只需一次）

```powershell
# 1) 建独立 venv 并装 playwright（本仓库已装好：scripts/xhs_scroll/.venv）
python -m venv scripts\xhs_scroll\.venv
scripts\xhs_scroll\.venv\Scripts\python -m pip install -r scripts\xhs_scroll\requirements.txt

# 2) 前置：本机装有 Chrome 或 Edge（会自动检测；也可改 xhs_scroll.py 里 channel="chrome"/"msedge"）
```

## 用法

```powershell
cd <repo>\astock-anayisis
$py = "scripts\xhs_scroll\.venv\Scripts\python.exe"

# ① 登录一次（会弹出真实 Chrome；扫码/手机号登录后自动检测并保存登录态）
$py scripts\xhs_scroll\xhs_scroll.py login            # 已有登录态想重登: 加 --force

# ② 刷发现页（模拟人滚动，抓 feed 响应，最多 30 张卡片）
$py scripts\xhs_scroll\xhs_scroll.py scroll --max-cards 30 --max-scrolls 15 --out scripts\xhs_scroll\data\feed.jsonl

# ③ 关键词搜索（同样限速滚动）
$py scripts\xhs_scroll\xhs_scroll.py search "基金定投" --max-cards 10 --out scripts\xhs_scroll\data\search.jsonl

# ④ 读单篇笔记（标题/正文/作者/互动/标签，可选评论）
$py scripts\xhs_scroll\xhs_scroll.py note https://www.xiaohongshu.com/explore/<24位id> --with-comments --out scripts\xhs_scroll\data\note.md
```

### 输出字段（JSONL 卡片）

`note_id / title / desc / type(video|normal) / link / author{user_id,nickname} / interact{liked, collected, comment, share}_count / tags / cover`；
`note` 命令另含 `comments[]（nickname/content/like_count）`，正文抓不到时回退 `page_text` 兜底。

## 接给小满（知识管道）

- **临时试读**：Dashboard「素材源」→「手动喂 URL」贴笔记链接 → 小满走 📖 阅读行为读并写感受（零开发）。
- **批量沉淀**：`scroll/search` 产出的 JSONL 可作为"少女动态风格样本/话题素材"，导入 knowledge 池或由小满阅读任务消费（可按需加一个 `import` 子命令对接 `agent/db.py`）。

## 风险与合规（务必读）

- 用途限于**你自己账号的个人阅读/研究**：低频、少量、不分发、不商用。
- 平台 ToS 禁止自动化；被抓特征会先限流/验证码，再严会封号。工具已内置 1.8~4.2s 随机间隔与随机滚动距离；出现验证码请立刻停止、降频。
- 越线行为（批量抓取、绕过风控、抓用户信息、商用售卖）有刑事判例，禁止。详见调研笔记 §4。

## 维护须知

- 小红书 DOM/接口随时会变：抓不到时先看抓到的响应日志（代码里可打印 `resp.url`）再修解析；
  字段以页面实际返回为准。
- 登录态 cookie 有有效期，失效重跑 `login --force`。
