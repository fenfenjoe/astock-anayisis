# ===========================================
# sync_dsh.ps1 - dsh/openviking environment consistency sync
# ===========================================
# 1. Check & auto-install prerequisites: node/npm, pnpm (dsh 插件管理器依赖),
#    dsh CLI（缺失时按钉选版本 npm i -g 自动安装）
# 2. Sync repo .dsh/profiles (xiaoman/headless) -> ~/.dsh/profiles (idempotent)
# 3. Install profile plugin deps: dsh plugin --profile <name> install (idempotent)
# 4. Check ~/.dsh/.credentials.yaml exists (copy from template if missing)
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/sync_dsh.ps1
#
# 注意：本脚本会向用户目录写文件（npm 全局目录、~/.dsh、pnpm store），
#       在受限沙箱内运行可能因 EPERM 失败，请在普通终端执行。
# ===========================================
$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path   # <repo>/scripts
$repoRoot   = Split-Path -Parent $scriptRoot                    # <repo>
$projDsh    = Join-Path $repoRoot ".dsh"
$homeDsh    = Join-Path $env:USERPROFILE ".dsh"

# 钉选版本（与 README.md / docs/DEPLOYMENT.md 保持一致）
$pinnedDsh = "0.1.0-rc.6"

# 安装全局 npm 包后刷新当前会话 PATH（npm 全局目录可能刚进用户 PATH）
function Refresh-Path {
  $machine = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
  $user    = [System.Environment]::GetEnvironmentVariable("Path", "User")
  $env:Path = "$machine;$user"
}

Write-Host "=== [1/4] Prerequisites: node / npm / pnpm / dsh ==="

# ── node + npm（dsh 运行时与安装器，无法自动安装，缺失则引导退出）──
if (-not (Get-Command node -ErrorAction SilentlyContinue) -or
    -not (Get-Command npm  -ErrorAction SilentlyContinue)) {
  Write-Warning "未找到 node/npm。请先安装 Node.js（Windows 推荐 nvm4w: https://nvm.sh），npm 随 Node 自带。"
  Write-Warning "安装完成后重新运行本脚本。"
  exit 1
}
Write-Host "  node: $(& node --version 2>$null)"

# ── pnpm（dsh plugin 的包管理器，缺失自动装）──
if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
  Write-Host "  pnpm 未找到（dsh plugin 依赖它），正在安装: npm i -g pnpm ..."
  npm i -g pnpm
  Refresh-Path
}
if (Get-Command pnpm -ErrorAction SilentlyContinue) {
  Write-Host "  pnpm: $(& pnpm --version 2>$null)"
} else {
  Write-Warning "  pnpm 自动安装失败，请手动执行: npm i -g pnpm，然后重跑本脚本"
}

# ── dsh CLI（缺失按钉选版本自动安装；版本不一致仅警告，不强制降级）──
if (-not (Get-Command dsh -ErrorAction SilentlyContinue)) {
  Write-Host "  dsh 未找到，正在安装: npm i -g @deepseek-ai/dsh@$pinnedDsh ..."
  npm i -g "@deepseek-ai/dsh@$pinnedDsh"
  Refresh-Path
}
if (Get-Command dsh -ErrorAction SilentlyContinue) {
  $dshVer = (& dsh --version 2>$null | Out-String).Trim()
  Write-Host "  dsh: $dshVer"
  if ($dshVer -and $dshVer -notmatch [regex]::Escape($pinnedDsh)) {
    Write-Warning "  dsh 版本与钉选 $pinnedDsh 不一致（当前 $dshVer）；如需对齐: npm i -g @deepseek-ai/dsh@$pinnedDsh"
  }
} else {
  Write-Warning "  dsh 自动安装失败，请手动执行: npm i -g @deepseek-ai/dsh@$pinnedDsh，然后重跑本脚本"
}

# ── openviking-server（可选：本地记忆服务；云版模式不需要）──
$ovExe = (Get-Command openviking-server -ErrorAction SilentlyContinue).Source
if (-not $ovExe) {
  $ovExe = (Get-ChildItem "$env:APPDATA\Python\Python311\Scripts\openviking-server.exe" -ErrorAction SilentlyContinue).FullName
}
if ($ovExe) {
  $ovVer = (& $ovExe --version 2>$null | Out-String).Trim()
  Write-Host "  openviking-server: $ovVer"
  if ($ovVer -notmatch "0\.4\.") {
    Write-Warning "  openviking version differs from pinned 0.4.x; align with: python -m pip install --user --upgrade openviking==0.4.16"
  }
} else {
  Write-Warning "  openviking-server not found（云版模式可忽略）; 本地版安装: python -m pip install --user --upgrade openviking"
}

Write-Host "=== [2/4] Sync dsh profiles (repo -> ~/.dsh) ==="
$srcProfiles = Join-Path $projDsh "profiles"
if (Test-Path $srcProfiles) {
  $dst = Join-Path $homeDsh "profiles"
  New-Item -ItemType Directory -Force -Path $dst | Out-Null
  Get-ChildItem $srcProfiles -Directory | ForEach-Object {
    $target = Join-Path $dst $_.Name
    if (-not (Test-Path $target)) {
      Copy-Item $_.FullName $target -Recurse
      Write-Host "  synced profile: $($_.Name)"
    } else {
      Write-Host "  exists (skip): $($_.Name)"
    }
  }
} else {
  Write-Warning "  repo .dsh/profiles missing (git not fully pulled?)"
}

Write-Host "=== [3/4] Install profile plugin deps (dsh plugin --profile <name> install) ==="
if (-not (Get-Command dsh -ErrorAction SilentlyContinue)) {
  Write-Warning "  dsh 不可用，跳过插件安装（先解决 [1/4] 中的 dsh 安装问题）"
} elseif (-not (Test-Path $srcProfiles)) {
  Write-Warning "  repo .dsh/profiles 缺失，跳过"
} else {
  Get-ChildItem $srcProfiles -Directory | ForEach-Object {
    $name = $_.Name
    $pj   = Join-Path $_.FullName "package.json"
    if (-not (Test-Path $pj)) { Write-Host "  no package.json: $name (skip)"; return }
    $deps = (Get-Content $pj -Raw | ConvertFrom-Json).dependencies
    if (-not $deps -or $deps.PSObject.Properties.Count -eq 0) {
      Write-Host "  no plugin deps: $name (skip)"; return
    }
    Write-Host "  installing plugins for profile: $name ..."
    & dsh plugin --profile $name install 2>&1 | ForEach-Object { "    $_" }
    if ($LASTEXITCODE -ne 0) {
      Write-Warning "  profile '$name' 插件安装失败（见上方日志）；可手动重试: dsh plugin --profile $name install"
    } else {
      Write-Host "  ok: $name plugins ready"
    }
  }
}

Write-Host "=== [4/4] Credential check ==="
$credFile = Join-Path $homeDsh ".credentials.yaml"
if (-not (Test-Path $credFile)) {
  $tmpl = Join-Path $projDsh ".credentials.example.yaml"
  if (Test-Path $tmpl) {
    Write-Warning "  ~/.dsh/.credentials.yaml missing! Copy the template and fill in DEEPSEEK_API_KEY:"
    Write-Host "    Copy-Item `"$tmpl`" `"$credFile`"   # then edit with your real key"
  } else {
    Write-Warning "  ~/.dsh/.credentials.yaml missing and no template found."
  }
} else {
  Write-Host "  ~/.dsh/.credentials.yaml exists (ok)"
}

Write-Host ""
Write-Host "Sync done."
