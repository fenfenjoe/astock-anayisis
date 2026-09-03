# ═══════════════════════════════════════════════════════════════
# fetch_live2d_assets.ps1 — 小满 LIVE2D 桌宠资产一键下载（需在有外网的机器上执行）
#
# 背景：执行环境（沙箱）无外网，无法代下资产。本脚本把 LIVE2D 运行时 + 候选模型
#       下载到仓库 static/live2d/ 的正确位置，之后直接 git add/commit 即可。
#
# 用法：  powershell -ExecutionPolicy Bypass -File scripts\fetch_live2d_assets.ps1
#         （默认：下载运行时 + 官方 Haru/Natori 候选）
#         增量拉取任一 GitHub 仓库里的模型目录（需含 .model3.json）：
#         powershell -ExecutionPolicy Bypass -File scripts\fetch_live2d_assets.ps1 `
#           -AddRepo hacxy/l2d-models -Branch main -SubPath models/sanmao -As sanmao
#         先列出某仓库里所有 Cubism4 模型目录（供选型，不下载）：
#         powershell -ExecutionPolicy Bypass -File scripts\fetch_live2d_assets.ps1 `
#           -ListModels -AddRepo hacxy/l2d-models -Branch main
#         拉取 live2d-widget 生态（Cubism2）npm 模型包 + 配套运行时（如 Pio）：
#         powershell -ExecutionPolicy Bypass -File scripts\fetch_live2d_assets.ps1 `
#           -AddNpm live2d-widget-model-pio
# 产物：  etf-strategies/dashboard/static/live2d/
#           ├── vendor/pixi.min.js                 # PixiJS v6.5.10（MIT；与 pixi-live2d-display 0.4 配对）
#           ├── vendor/live2dcubismcore.min.js     # Live2D Cubism4 Core（官方分发）
#           ├── vendor/pixi-live2d-display.min.js  # Cubism4 运行时（MIT）
#           └── model/Haru|Natori|…                # 候选模型（Cubism4）
# 之后：  选定模型 → 把 pet.js 顶部 CFG.modelJson 指向对应 .model3.json；
#         或在浏览器打开 static/live2d/preview.html 逐个预览（见 README.md）。
# ═══════════════════════════════════════════════════════════════
param(
  [switch]$ListModels,       # 仅列出仓库内 *.model3.json 目录（选型用，不下载）
  [string]$AddRepo = '',     # 增量拉取/列表：GitHub 仓库（owner/repo）
  [string]$Branch  = 'main', # 增量拉取/列表：分支
  [string]$SubPath = '',     # 增量拉取：仓库内模型目录（须含 .model3.json）
  [string]$As      = '',     # 增量拉取：本地目录名（默认取 SubPath 末段）
  [string]$AddNpm  = ''      # 拉取 live2d-widget 生态 npm 模型包（Cubism2，如 live2d-widget-model-pio）
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Dest     = Join-Path $RepoRoot 'etf-strategies\dashboard\static\live2d'
$Vendor   = Join-Path $Dest 'vendor'
$ModelDir = Join-Path $Dest 'model'

# ── 下载助手：按序尝试多个源，成功（HTTP 200 且大小>0）即停 ──
function Get-FileWithFallback {
  param([string[]]$Urls, [string]$OutFile)
  foreach ($u in $Urls) {
    Write-Host "  GET $u"
    & curl.exe -L --fail --silent --show-error --create-dirs -o $OutFile $u
    if ($LASTEXITCODE -eq 0 -and (Test-Path $OutFile) -and (Get-Item $OutFile).Length -gt 0) {
      Write-Host "  OK  $(Get-Item $OutFile).Length bytes → $OutFile" -ForegroundColor Green
      return
    }
    Write-Host "  FAIL（尝试下一个源）" -ForegroundColor Yellow
    Remove-Item $OutFile -ErrorAction SilentlyContinue
  }
  throw "全部源下载失败：$($Urls[0])"
}

# ── 从 GitHub 仓库按目录清单下载模型（官方 CubismWebSamples，避免整仓克隆）──
function Get-GithubDir {
  param([string]$Repo, [string]$Branch, [string]$SubPath, [string]$OutDir)
  Write-Host "`n[模型] $SubPath ← $Repo@$Branch"
  $treeUrl = "https://api.github.com/repos/$Repo/git/trees/$Branch`?recursive=1"
  $json = & curl.exe -L --fail --silent $treeUrl
  if ($LASTEXITCODE -ne 0) { throw "GitHub API 失败：$treeUrl" }
  $files = ($json | ConvertFrom-Json).tree |
    Where-Object { $_.type -eq 'blob' -and $_.path -like "$SubPath/*" -and $_.path -notlike '*/.git/*' }
  if (-not $files) { throw "目录 $SubPath 未找到任何文件（分支/路径可能变了，请改本脚本）" }
  foreach ($f in $files) {
    $rel  = $f.path.Substring($SubPath.Length).TrimStart('/')
    $out  = Join-Path $OutDir $rel
    $url  = "https://raw.githubusercontent.com/$Repo/$Branch/$($f.path)"
    & curl.exe -L --fail --silent --show-error --create-dirs -o $out $url
    if ($LASTEXITCODE -ne 0) { throw "下载失败：$url" }
  }
  Write-Host "  OK $($files.Count) 个文件 → $OutDir" -ForegroundColor Green
}

# ── 模式：仅列出仓库内所有 *.model3.json 目录（供选型，不下载）──
if ($ListModels) {
  if (-not $AddRepo) { throw '-ListModels 需配合 -AddRepo <owner/repo>' }
  Write-Host "`n[模型清单] $AddRepo@$Branch 下所有 Cubism4(.model3.json) 模型目录："
  $treeUrl = "https://api.github.com/repos/$AddRepo/git/trees/$Branch`?recursive=1"
  $json = & curl.exe -L --fail --silent $treeUrl
  if ($LASTEXITCODE -ne 0) { throw "GitHub API 失败：$treeUrl" }
  ($json | ConvertFrom-Json).tree |
    Where-Object { $_.type -eq 'blob' -and $_.path -like '*.model3.json' } |
    ForEach-Object { $_.path.Substring(0, $_.path.LastIndexOf('/')) } |
    Sort-Object -Unique |
    ForEach-Object { Write-Host "  $_" -ForegroundColor Green }
  Write-Host ''
  Write-Host '挑选后下载：fetch_live2d_assets.ps1 -AddRepo <同上> -Branch <同上> -SubPath <上面的目录> -As <本地名>'
  exit 0
}

Write-Host '════════ Live2D 资产下载 ════════' -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $Vendor, $ModelDir | Out-Null

# ── 1) 运行时（jsdelivr 优先 / unpkg 兜底；core 走官方 CDN）──
Write-Host "`n[运行时]"
Get-FileWithFallback -OutFile (Join-Path $Vendor 'pixi.min.js') -Urls @(
  'https://cdn.jsdelivr.net/npm/pixi.js@6.5.10/dist/pixi.min.js',
  'https://unpkg.com/pixi.js@6.5.10/dist/pixi.min.js')
Get-FileWithFallback -OutFile (Join-Path $Vendor 'pixi-live2d-display.min.js') -Urls @(
  'https://cdn.jsdelivr.net/npm/pixi-live2d-display@0.4.0/dist/cubism4.min.js',
  'https://unpkg.com/pixi-live2d-display@0.4.0/dist/cubism4.min.js')
Get-FileWithFallback -OutFile (Join-Path $Vendor 'live2dcubismcore.min.js') -Urls @(
  'https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js')

# ── 2) 官方免费示例模型（Cubism4 少女系，保底候选；画风拍板用）──
#     Sample Material Terms：可随应用免费商用；需署名 Live2D；不得单独再分发模型文件。
Get-GithubDir -Repo 'Live2D/CubismWebSamples' -Branch 'develop' `
  -SubPath 'Samples/Resources/Haru'  -OutDir (Join-Path $ModelDir 'Haru')
Get-GithubDir -Repo 'Live2D/CubismWebSamples' -Branch 'develop' `
  -SubPath 'Samples/Resources/Natori' -OutDir (Join-Path $ModelDir 'Natori')

# ── 3) 增量拉取：任一 GitHub 仓库中的模型目录（须含 .model3.json / Cubism4）──
if ($AddRepo) {
  if (-not $SubPath) { throw '-AddRepo 需配合 -SubPath（仓库内模型目录，须含 .model3.json）' }
  $local = if ($As) { $As } else { ($SubPath.TrimEnd('/') -split '/')[-1] }
  Write-Host "`n[增量模型] $SubPath ← $AddRepo@$Branch → model/$local" -ForegroundColor Cyan
  Get-GithubDir -Repo $AddRepo -Branch $Branch -SubPath $SubPath.TrimEnd('/') `
    -OutDir (Join-Path $ModelDir $local)
}

# ── 4) live2d-widget 生态（Cubism2）：npm 模型包 + 配套运行时 ──
if ($AddNpm) {
  Write-Host "`n[Cubism2 运行时] pixi-live2d-display cubism2 构建 + live2d.min.js 核心"
  Get-FileWithFallback -OutFile (Join-Path $Vendor 'pixi-live2d-display-cubism2.min.js') -Urls @(
    'https://cdn.jsdelivr.net/npm/pixi-live2d-display@0.4.0/dist/cubism2.min.js',
    'https://unpkg.com/pixi-live2d-display@0.4.0/dist/cubism2.min.js')
  Get-FileWithFallback -OutFile (Join-Path $Vendor 'live2d.min.js') -Urls @(
    'https://cdn.jsdelivr.net/gh/stevenjoezhang/live2d-widget@master/live2d.min.js',
    'https://raw.githubusercontent.com/stevenjoezhang/live2d-widget/master/live2d.min.js')

  # npm 模型包：registry → tarball → 解包到 model/<本地名>
  $localNpm = if ($As) { $As } else { $AddNpm }
  Write-Host "`n[npm 模型] $AddNpm → model/$localNpm"
  $meta = & curl.exe -L --fail --silent "https://registry.npmjs.org/$AddNpm/latest"
  if ($LASTEXITCODE -ne 0) { throw "npm registry 不可达：$AddNpm（需外网）" }
  $m = $meta | ConvertFrom-Json
  $tgz = Join-Path $env:TEMP ("$localNpm-$($m.version).tgz")
  & curl.exe -L --fail --silent --show-error -o $tgz $m.dist.tarball
  if ($LASTEXITCODE -ne 0) { throw "模型包下载失败：$($m.dist.tarball)" }
  $tmp = Join-Path $env:TEMP ("npmx_" + [guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Force -Path $tmp | Out-Null
  tar -xzf $tgz -C $tmp
  if ($LASTEXITCODE -ne 0) { throw "模型包解压失败" }
  $src = if (Test-Path (Join-Path $tmp 'package')) { Join-Path $tmp 'package' } else { $tmp }
  New-Item -ItemType Directory -Force -Path (Join-Path $ModelDir $localNpm) | Out-Null
  Copy-Item -Path (Join-Path $src '*') -Destination (Join-Path $ModelDir $localNpm) -Recurse -Force
  Remove-Item $tgz, $tmp -Recurse -Force -ErrorAction SilentlyContinue
  Write-Host "  已解包 → model/$localNpm"
  $found = Get-ChildItem (Join-Path $ModelDir $localNpm) -Recurse -Include '*.model.json','*.model3.json' -File
  if ($found) {
    foreach ($f in $found) {
      $web = '/static/live2d/' + $f.FullName.Substring($Dest.Length).Replace('\', '/').TrimStart('/')
      Write-Host "  模型入口: $web" -ForegroundColor Green
    }
    Write-Host '  下一步：把 pet.js 顶部 CFG.modelJson 填成上面的 .model.json（结尾 .model.json = 自动 Cubism2 运行时）'
  } else {
    Write-Host '  未在包内发现 *.model.json / *.model3.json，请人工检查包结构' -ForegroundColor Yellow
  }
}

Write-Host @"

════════ 完成 ════════
资产已就位：$Dest
体积提示：git add 提交即可（约 3~6MB）。

下一步：
  1) 浏览器打开 etf-strategies/dashboard/static/live2d/preview.html 预览候选模型
     （或跑 fetch_live2d_preview.ps1 -Screenshot 截图对比画风）；
  2) 选定后把 pet.js 顶部 CFG.modelJson 改成 /static/live2d/model/<选中的>/<xxx>.model3.json；
  3) 想加社区 Q 版模型：README.md 有候选清单，命中目录后重跑本脚本
     -AddRepo <owner/repo> -Branch <分支> -SubPath <模型目录> -As <本地名>。

授权提醒：模型资产遵循 Live2D Sample Material Terms —— 随应用分发需在
README/关于处署名 "Character © Live2D Inc."；模型文件不得脱离应用单独再分发。
社区模型请逐个核对各自 LICENSE/README。
"@ -ForegroundColor Cyan
