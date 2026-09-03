# ═══════════════════════════════════════════════════════════════
# fetch_live2d_preview.ps1 — 生成候选模型预览页（可选无头截图）
#
# 前置：已执行 fetch_live2d_assets.ps1（或手工放置模型），且本机有 Chrome/Edge。
# 作用：
#   1) 扫描 static/live2d/model/ 下所有 *.model3.json，生成 preview.html；
#   2) 可选 -Screenshot：起本地静态服务，用无头浏览器对每个模型截图到 shots/，
#      供"画风拍板"对比（浏览器需能跑 WebGL，必要时加 --use-angle=swiftshader）。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts\fetch_live2d_preview.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\fetch_live2d_preview.ps1 -Screenshot
# 人工预览（不截图）：起 Dashboard 或静态服务后浏览器打开
#   http://127.0.0.1:8000/static/live2d/preview.html
# ═══════════════════════════════════════════════════════════════
param([switch]$Screenshot)

$ErrorActionPreference = 'Stop'
$RepoRoot   = Split-Path -Parent $PSScriptRoot
$StaticRoot = Join-Path $RepoRoot 'etf-strategies\dashboard\static'
$L2dDir     = Join-Path $StaticRoot 'live2d'
$ModelDir   = Join-Path $L2dDir 'model'
$ShotsDir   = Join-Path $L2dDir 'shots'

if (-not (Test-Path $ModelDir)) {
  throw "未找到 $ModelDir —— 先执行 scripts\fetch_live2d_assets.ps1"
}
$models = Get-ChildItem -Path $ModelDir -Recurse -Filter '*.model3.json' -File
if (-not $models) {
  throw "model/ 下没有 *.model3.json —— 先下载/放置模型"
}
New-Item -ItemType Directory -Force -Path $ShotsDir | Out-Null

# ── 生成 preview.html（列出全部候选；?model=xxx 只渲染单个）──
$cards = ''
foreach ($m in $models) {
  $rel  = $m.FullName.Substring($StaticRoot.Length).Replace('\', '/').TrimStart('/')
  $name = $m.Directory.Name
  $cards += @"
      <div class="card" id="card-$name">
        <h3>$name</h3>
        <div class="host" id="host-$name"></div>
      </div>
"@
}
$json = ($models | ForEach-Object { @{ name = $_.Directory.Name; url = 'live2d/' + $_.FullName.Substring($L2dDir.Length).Replace('\', '/').TrimStart('/') } }) | ConvertTo-Json

$html = @"
<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>小满 LIVE2D 候选模型预览</title>
<style>
  body { margin:0; padding:24px; background:#0e1520; color:#eee; font-family:'Segoe UI',sans-serif; }
  h1 { font-size:16px; color:#f2a15c; }
  .row { display:flex; flex-wrap:wrap; gap:16px; }
  .card { width:300px; border:1px solid #2a3a52; border-radius:10px; padding:10px; background:#131c2b; }
  .card h3 { margin:0 0 6px; font-size:13px; color:#f2c14e; }
  .host { width:300px; height:280px; background:radial-gradient(circle at 50% 90%, rgba(242,161,92,.12), transparent 60%); }
  .note { font-size:12px; color:#8aa0b8; margin-top:14px; }
</style></head><body>
<h1>小满 LIVE2D 桌宠 · 候选模型（画风拍板用）</h1>
<div class="row">$cards</div>
<p class="note">页面加载后逐个模型应出现并轻微摆动。无头截图用：
powershell -ExecutionPolicy Bypass -File scripts\fetch_live2d_preview.ps1 -Screenshot
选定后：把 pet.js 顶部 CFG.modelJson 指向对应 model3.json。</p>
<script src="live2d/vendor/pixi.min.js"></script>
<script src="live2d/vendor/live2dcubismcore.min.js"></script>
<script src="live2d/vendor/pixi-live2d-display.min.js"></script>
<script>
  var MODELS = $json;
  var only = new URLSearchParams(location.search).get('model');
  function render(m) {
    if (only && m.name !== only) { var c = document.getElementById('card-' + m.name); if (c) c.style.display = 'none'; return; }
    var host = document.getElementById('host-' + m.name);
    var app = new PIXI.Application({ width: 300, height: 280, backgroundAlpha: 0, antialias: true, autoStart: true });
    host.appendChild(app.view);
    PIXI.live2d.Live2DModel.from(m.url).then(function (model) {
      var s = 250 / model.height;
      model.scale.set(s, s);
      model.anchor.set(0.5, 1);
      model.position.set(150, 270);
      app.stage.addChild(model);
      setInterval(function () { try { model.motion('Idle', Math.floor(Math.random() * 3)); } catch (e) {} }, 6000);
    }).catch(function (e) { host.innerHTML = '<p style="color:#e66">加载失败: ' + e + '</p>'; });
  }
  MODELS.forEach(render);
</script>
</body></html>
"@
[System.IO.File]::WriteAllText((Join-Path $L2dDir 'preview.html'), $html, [System.Text.Encoding]::UTF8)
Write-Host "preview.html 已生成（$($models.Count) 个候选）→ $L2dDir\preview.html" -ForegroundColor Green

if (-not $Screenshot) { Write-Host '加 -Screenshot 可无头截图到 shots/'; exit }

# ── 无头截图 ──
$chrome = @(
  'C:\Program Files\Google\Chrome\Application\chrome.exe',
  'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
  'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
  'C:\Program Files\Microsoft\Edge\Application\msedge.exe') |
  Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) { throw '未找到 Chrome/Edge' }

# 起本地静态服务（root=static，URL 形如 /live2d/preview.html?model=X）
$port = 8765
$p = Start-Process python -ArgumentList @('-m','http.server',$port,'--bind','127.0.0.1') `
     -WorkingDirectory $StaticRoot -WindowStyle Hidden -PassThru
try {
  Start-Sleep -Seconds 2
  foreach ($m in $models) {
    $name = $m.Directory.Name
    $out  = Join-Path $ShotsDir ($name + '.png')
    $url  = "http://127.0.0.1:$port/live2d/preview.html?model=$name"
    Write-Host "截图 $name ..."
    & $chrome --headless=new --disable-gpu --use-angle=swiftshader `
      --window-size=420,420 --hide-scrollbars `
      --screenshot=$out $url 2>$null
    if (Test-Path $out) { Write-Host "  OK → $out" -ForegroundColor Green }
    else { Write-Host "  截图失败（$name），可手动开浏览器预览" -ForegroundColor Yellow }
  }
} finally {
  Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
}
Write-Host '完成。打开 shots/ 目录对比画风；选定后改 pet.js CFG.modelJson。' -ForegroundColor Cyan
