# ===========================================
# sync_dsh.ps1 - dsh/openviking environment consistency sync
# ===========================================
# 1. Verify dsh / openviking-server versions against repo-pinned versions
# 2. Sync repo .dsh/profiles (xiaoman/headless) -> ~/.dsh/profiles (idempotent)
# 3. Check ~/.dsh/.credentials.yaml exists (copy from template if missing)
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/sync_dsh.ps1
# ===========================================
$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path   # <repo>/scripts
$repoRoot   = Split-Path -Parent $scriptRoot                    # <repo>
$projDsh    = Join-Path $repoRoot ".dsh"
$homeDsh    = Join-Path $env:USERPROFILE ".dsh"

Write-Host "=== [1/3] Version check ==="
$dshVer = (& dsh --version 2>$null | Out-String).Trim()
if ($dshVer) {
  Write-Host "  dsh: $dshVer"
  if ($dshVer -notmatch "0\.1\.0-rc\.6") {
    Write-Warning "  Version differs from pinned 0.1.0-rc.6; align with: npm i -g @deepseek-ai/dsh@0.1.0-rc.6"
  }
} else {
  Write-Warning "  dsh not found; install: npm i -g @deepseek-ai/dsh@0.1.0-rc.6"
}
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
  Write-Warning "  openviking-server not found; install: python -m pip install --user --upgrade openviking"
}

Write-Host "=== [2/3] Sync dsh profiles (repo -> ~/.dsh) ==="
if (Test-Path (Join-Path $projDsh "profiles")) {
  $src = Join-Path $projDsh "profiles"
  $dst = Join-Path $homeDsh "profiles"
  New-Item -ItemType Directory -Force -Path $dst | Out-Null
  Get-ChildItem $src -Directory | ForEach-Object {
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

Write-Host "=== [3/3] Credential check ==="
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
