# ============================================================
# setup_etf_scheduled_tasks.ps1
# Windows Scheduled Tasks migration: dsh-trigger-* -> etf-trigger-*
# ============================================================
# Migrates the daily-review scheduled tasks to call the dashboard
# cross-platform entrypoint (dashboard.scheduler_cli) instead of
# the old dsh_trigger.py, so idempotency & report-import are unified
# on scheduler_runs (SQLite) and the same dual-engine (dsh/claude) runs.
#
# Usage (run as Administrator on the machine that hosts the tasks):
#   powershell -ExecutionPolicy Bypass -File setup_etf_scheduled_tasks.ps1            # dry-run: print the plan
#   powershell -ExecutionPolicy Bypass -File setup_etf_scheduled_tasks.ps1 -Apply     # create etf-trigger-* + disable dsh-trigger-*
#   powershell -ExecutionPolicy Bypass -File setup_etf_scheduled_tasks.ps1 -Revert    # remove etf-trigger-*, re-enable dsh-trigger-*
#   powershell -ExecutionPolicy Bypass -File setup_etf_scheduled_tasks.ps1 -Cleanup   # remove ALL tasks -> engine-only mode
#
# Notes:
#   - Task list is generated from .claude/scripts/task_schedule.json (scoped to
#     my_doc/每日复盘/ prompts), so future schedule edits just re-run with -Apply.
#   - Trading-day / weekday / idempotency gates are enforced inside scheduler_cli
#     (same semantics as the dashboard engine); the Scheduled Task only fires the
#     rough trigger (e.g. 09:07 on Mon-Fri).
#   - Old dsh-trigger-* tasks are DISABLED (not deleted) so -Revert can restore.
#   - DEFAULT MODE (2026-08-27 user decision): engine follows the web process —
#     no system Scheduled Tasks needed. Use -Cleanup to remove any leftovers.
# ============================================================

param(
    [switch]$Apply,
    [switch]$Revert,
    [switch]$Cleanup
)

$ErrorActionPreference = "Stop"

# ---- Locate repo root & etf-strategies ----
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path      # .../etf-strategies/scripts
$EtfDir      = Split-Path -Parent $ScriptDir                        # .../etf-strategies
$RepoRoot    = Split-Path -Parent $EtfDir                           # repo root
$ScheduleFile = Join-Path $RepoRoot ".claude\scripts\task_schedule.json"
$PythonExe    = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $PythonExe) { $PythonExe = "D:\miniconda3\python.exe" }
if (-not (Test-Path $PythonExe)) { throw "python not found: $PythonExe" }

Write-Host "[etf] RepoRoot   = $RepoRoot"
Write-Host "[etf] EtfDir     = $EtfDir"
Write-Host "[etf] Python     = $PythonExe"

$DAY_NAMES = @("MON","TUE","WED","THU","FRI","SAT","SUN")

function Get-ScopedTasks {
    $sched = Get-Content $ScheduleFile -Raw -Encoding UTF8 | ConvertFrom-Json
    return @($sched.tasks | Where-Object { $_.prompt_file -like "my_doc/每日复盘/*" })
}

function New-TaskTriggers([object]$t) {
    # Returns an array of trigger objects (one per scheduled moment).
    # NOTE: -Daily 参数集不支持 -DaysOfWeek；指定星期必须用 -Weekly（WeeksInterval 默认 1）。
    # task_schedule.json 星期索引 0=Mon..6=Sun，.NET DayOfWeek 0=Sun..6=Sat → 用名称映射。
    $dayOfWeekMap = @{ 0 = "Monday"; 1 = "Tuesday"; 2 = "Wednesday"; 3 = "Thursday"; 4 = "Friday"; 5 = "Saturday"; 6 = "Sunday" }
    $triggers = @()
    if ($t.hourly) {
        foreach ($h in @($t.hourly_range)) {
            $at = "{0:D2}:{1:D2}" -f $h, [int]$t.target_minute
            if ($t.days_of_week -and $t.days_of_week.Count -gt 0 -and $t.days_of_week.Count -lt 7) {
                $dow = @($t.days_of_week | ForEach-Object { $dayOfWeekMap[$_] })
                $triggers += New-ScheduledTaskTrigger -Weekly -DaysOfWeek $dow -At $at
            } else {
                $triggers += New-ScheduledTaskTrigger -Daily -At $at
            }
        }
    } else {
        $at = $t.target_time   # "HH:MM"
        if ($t.days_of_week -and $t.days_of_week.Count -gt 0 -and $t.days_of_week.Count -lt 7) {
            $dow = @($t.days_of_week | ForEach-Object { $dayOfWeekMap[$_] })
            $triggers += New-ScheduledTaskTrigger -Weekly -DaysOfWeek $dow -At $at
        } else {
            $triggers += New-ScheduledTaskTrigger -Daily -At $at
        }
    }
    return $triggers
}

function New-TaskDef([object]$t) {
    $name = "etf-trigger-$($t.task_id)"
    $triggerPy = Join-Path $EtfDir "scripts\etf_trigger.py"
    # 用绝对路径执行薄封装入口（etf_trigger.py 自设 sys.path），不依赖工作目录
    $arg  = "`"$triggerPy`" --task $($t.task_id)"
    $desc = if ($t.description) { $t.description } else { $t.task_id }
    $action = New-ScheduledTaskAction -Execute $PythonExe -Argument $arg -WorkingDirectory $EtfDir
    $triggers = New-TaskTriggers $t
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
    New-ScheduledTask -Action $action -Trigger $triggers -Description $desc -Settings $settings -Principal $principal
}

function Invoke-Apply {
    $tasks = Get-ScopedTasks
    Write-Host ""
    Write-Host "=== Creating etf-trigger-* tasks ($($tasks.Count)) ==="
    foreach ($t in $tasks) {
        $name = "etf-trigger-$($t.task_id)"
        $times = if ($t.hourly) { "hourly :$($t.target_minute) in $($t.hourly_range -join ',')" } else { $t.target_time }
        $arg  = "--task $($t.task_id)"
        Write-Host ("  {0,-28} {1,-22} python scripts\etf_trigger.py {2}" -f $name, $times, $arg)
        if ($Apply) {
            $def = New-TaskDef $t
            Register-ScheduledTask -TaskName $name -InputObject $def -Force | Out-Null
        }
    }
    # Disable old dsh-trigger-* (keep for rollback)
    Write-Host ""
    $old = @(Get-ScheduledTask -TaskName "dsh-trigger-*" -ErrorAction SilentlyContinue)
    if ($old.Count -gt 0) {
        Write-Host "=== Disabling $($old.Count) old dsh-trigger-* tasks ==="
        foreach ($o in $old) { Write-Host "  Disable $($o.TaskName)"; if ($Apply) { Disable-ScheduledTask -TaskName $o.TaskName | Out-Null } }
    } else {
        Write-Host "=== No old dsh-trigger-* tasks found (nothing to disable) ==="
    }
    Write-Host ""
    if ($Apply) {
        Write-Host "Done. Verify with:  Get-ScheduledTask -TaskName 'etf-trigger-*' | Select TaskName, State"
    } else {
        Write-Host "Dry-run complete. Re-run with -Apply to actually create tasks."
    }
}

function Invoke-Revert {
    Write-Host "=== Removing etf-trigger-* tasks ==="
    $etf = @(Get-ScheduledTask -TaskName "etf-trigger-*" -ErrorAction SilentlyContinue)
    foreach ($e in $etf) { Write-Host "  Unregister $($e.TaskName)"; Unregister-ScheduledTask -TaskName $e.TaskName -Confirm:$false }
    Write-Host "=== Re-enabling old dsh-trigger-* tasks ==="
    $old = @(Get-ScheduledTask -TaskName "dsh-trigger-*" -ErrorAction SilentlyContinue)
    foreach ($o in $old) { Write-Host "  Enable $($o.TaskName)"; Enable-ScheduledTask -TaskName $o.TaskName | Out-Null }
    Write-Host "Rollback complete."
}

function Invoke-Cleanup {
    # 回归"引擎随 Web 启停"模式：删除所有 etf-trigger-*，保持 dsh-trigger-* 停用
    # （旧任务不再需要——引擎模式由 dashboard 进程内调度，无需任何系统计划任务）。
    Write-Host "=== Removing etf-trigger-* tasks ==="
    $etf = @(Get-ScheduledTask -TaskName "etf-trigger-*" -ErrorAction SilentlyContinue)
    if ($etf.Count -gt 0) {
        foreach ($e in $etf) { Write-Host "  Unregister $($e.TaskName)"; Unregister-ScheduledTask -TaskName $e.TaskName -Confirm:$false }
    } else {
        Write-Host "  无 etf-trigger-* 任务（已干净）"
    }
    Write-Host "=== Keeping old dsh-trigger-* DISABLED (if any) ==="
    $old = @(Get-ScheduledTask -TaskName "dsh-trigger-*" -ErrorAction SilentlyContinue)
    foreach ($o in $old) {
        if ($o.State -ne 'Disabled') { Write-Host "  Disable $($o.TaskName)"; Disable-ScheduledTask -TaskName $o.TaskName | Out-Null }
        else { Write-Host "  $($o.TaskName) 已停用" }
    }
    if ($old.Count -eq 0) { Write-Host "  无 dsh-trigger-* 任务" }
    Write-Host ""
    Write-Host "Cleanup complete. 调度现为【引擎随 Web 启停】模式："
    Write-Host "  - 启动 Web（start_local.ps1 / Docker 容器）→ 调度引擎自动启动"
    Write-Host "  - 关闭 Web（Ctrl+C / 容器停止）→ 调度引擎自动停止"
    Write-Host "  无需任何系统计划任务。"
}

if ($Revert) { Invoke-Revert } elseif ($Cleanup) { Invoke-Cleanup } else { Invoke-Apply }
