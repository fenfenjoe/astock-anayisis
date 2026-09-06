---
name: windows-ps1-scripts
description: Windows PowerShell 运维/启动脚本开发与排障 checklist（start_all/sync_dsh 类服务编排脚本）。当创建或修改 scripts/*.ps1，或遇到 .ps1 解析错误（字符串未终止/缺大括号）、$PID 只读变量报错、写用户目录 EPERM、服务已运行却误报未启动、端口 10048 占用、dsh profile 插件 missing bundle 时触发，按单逐项排查。
origin: custom
version: 1.0.0
---

# Windows PowerShell 脚本开发与排障 Checklist V1.0

针对本仓库 `scripts/*.ps1`（服务编排、环境一键引导类脚本）在 **Windows + PowerShell 5.1 + TRAE 沙箱** 环境下的高频坑，按单检查。

## 触发场景

- 新建 / 修改 `scripts/*.ps1`（如 start_all.ps1、sync_dsh.ps1）
- .ps1 报 ParserError（"The string is missing the terminator"、"Missing closing '}'"）
- 变量报只读：`Cannot overwrite variable PID because it is read-only or constant`
- 安装类命令报 `EPERM` / `ENOENT _tmp_*`
- 服务实际已启动却提示"未启动"，或反之
- 端口绑定失败 `[Errno 10048]` / `winerror 10048`
- dsh 报 `cannot resolve profile bundle "@openviking/..."`

---

## 1. UTF-8 BOM 保活（最高频坑）

含中文注释/字符串的 `.ps1` **必须**保存为 **UTF-8 with BOM**。

- Windows PowerShell 5.1 对**无 BOM** 的 `.ps1` 按系统 ANSI（GBK）解码 → 中文字节错乱 → 引号配对失效 → 解析器报"字符串未终止/缺少 }"，报错位置往往与实际病因（编码）无关。
- 用文件编辑工具保存后 BOM 经常被剥离。**每次编辑完都要校验 BOM**：

```powershell
$p = "path\to\script.ps1"
$b = [IO.File]::ReadAllBytes($p)
if ($b[0] -ne 0xEF) {                 # BOM = EF BB BF
  $c = [IO.File]::ReadAllText($p, [Text.Encoding]::UTF8)
  [IO.File]::WriteAllText($p, $c, (New-Object Text.UTF8Encoding $true))
  "BOM restored"
} else { "BOM OK" }
```

## 2. 禁止占用只读自动变量

不要给这些 PowerShell 内置变量赋值：`$PID $PWD $HOST $ERROR $MATCHES $INPUT $ARGS $HOME $PSHOME $TRUE $FALSE $NULL $? $_`。

- 典型事故：函数里写 `$pid = Get-Content $pidFile` → 赋值抛错，且 `$pid` 仍保持**当前脚本自身 PID**（必然存活）→ `Is-Running` 类检查永远返回 true → 所有服务被误判 "already running, skip"。
- 对策：改名为 `$procId` 等业务变量名；**业务变量名全小写也要避开保留名**。

## 3. TRAE 沙箱写用户目录 → EPERM

沙箱内只允许写工作区。向工作区外写文件会被拦：

- `EPERM: operation not permitted, mkdir 'C:\Users\<u>\.pnpm-store'`
- `ENOENT _tmp_*`（npm/pnpm 临时目录）
- 常驻服务在沙箱内启动后，其**子进程继承沙箱限制**——例如 agent 调 dsh 写 `~/.dsh/profiles/xiaoman/cordis.yml` 也会 `EPERM`。

对策：

- 安装类命令（`npm i -g`、`dsh plugin ... install`、`pip install --user`）在**沙箱外**执行，或让用户在普通终端跑。
- 服务在沙箱内启动后出现疑似权限问题：`start_all.ps1 -Action stop` 后在沙箱外重新 `start_all.ps1`。
- 环境脚本头部注明"会写用户目录，沙箱内可能 EPERM"。

## 4. 服务编排脚本的状态判定

- 汇总服务状态时，以 **pid 文件 + `Get-Process -Id` 实际存活**为准，**不要**只看"本次新拉起"的哈希表——早已在运行、被 `already running, skip` 跳过的服务不在该表里，会被误报"未启动"。
- pid 文件模式：启动 `Set-Content $pf $proc.Id`；判定用 `Test-Path` + `[int]` 转换 + `Get-Process`；stop 时 `Stop-Process -Force` 后 `Remove-Item $pf`。
- `Start-Process -RedirectStandardOutput/-RedirectStandardError` 分离日志；启动后 `Start-Sleep` 给初始化留时间。

## 5. Windows 端口占用定位

`[Errno 10048]` / `通常每个套接字地址只允许使用一次` = 端口被占：

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { $pr = Get-Process -Id $_.OwningProcess; "$($_.OwningProcess) $($pr.ProcessName) $($pr.Path)" }
```

- 应用内"自动 taskkill 占用者"对 **SYSTEM 权限服务**（如酷狗 KGService.exe 占 8000）会静默失败（异常被吞）。
- 优先方案：让端口可通过**环境变量配置**（如 `DASHBOARD_PORT=8010`）并改脚本提示，而不是强杀他人服务。

## 6. dsh profile 插件依赖

- `~/.dsh/profiles/<name>/package.json` 里 `dependencies` 声明的插件，**不会**随 profile 配置同步自动安装；目录下缺 `node_modules` 时 dsh 报 `cannot resolve profile bundle "@openviking/..."`。
- 修复：`dsh plugin --profile <name> install`（其底层用 **pnpm**；pnpm 缺失先 `npm i -g pnpm`）。
- 环境引导脚本（sync_dsh.ps1）应包含：检测 node/npm（缺失引导 nvm4w）→ 装 pnpm → 装 dsh（钉选版本，版本不符仅警告不强降）→ 同步 profiles → 逐 profile 装插件 → 校验凭据。插件安装幂等，失败只警告不中断。

## 7. 外部命令 stderr ≠ 失败

- 原生命令（dsh/node/pnpm/python）常把进度、reasoning、日志写到 **stderr**，PowerShell 包装成红字 / `NativeCommandError` / `RemoteException`，但退出码可能为 0。
- 以 **`$LASTEXITCODE`** 和实际 stdout 内容判定成败，不要看到红字就当失败。

## 8. 验证闭环

1. 解析校验（0 错误）：
   ```powershell
   $errs = $null
   [System.Management.Automation.PSParser]::Tokenize((Get-Content $p -Raw), [ref]$errs) | Out-Null
   "parse errors: $($errs.Count)"
   ```
2. 实跑一遍 start / `-Action status` / `-Action stop`，看汇总与实际进程一致。
3. HTTP 服务用 `Invoke-WebRequest` 探活（期望 200）。
4. 端到端走真实链路（如登录拿 token → 调聊天 API），不要只看进程在不在。
5. 改动后再跑一次确认幂等（重复执行不应报错/重复安装）。

---

## 本项目相关文件

- `scripts/start_all.ps1` — 服务编排（dashboard / agent / openviking；pid 文件 + logs）
- `scripts/sync_dsh.ps1` — dsh 环境自愈（node/pnpm/dsh 检测安装 → profile 同步 → 插件安装 → 凭据校验）
- `.dsh/profiles/xiaoman/` — 小满 profile（package.json 声明 `@openviking/dsh-memory-plugin`）
- dsh 调用链：agent `dsh_runner.py` → `node dsh/lib/bin.js --profile xiaoman <task>`
