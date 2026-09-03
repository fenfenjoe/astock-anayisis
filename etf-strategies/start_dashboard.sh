#!/usr/bin/env bash
# ===========================================
# etf-dashboard 一键启动脚本（Git Bash / Linux / macOS）
# ===========================================
# 用法:
#   ./start_dashboard.sh                # 启动（首次自动构建镜像；已存在则直接拉起）
#   ./start_dashboard.sh rebuild        # 强制重新构建镜像后启动（Dockerfile/.env 有改动时用）
#   ./start_dashboard.sh stop           # 停止（保留数据卷）
#   ./start_dashboard.sh restart        # 重启（保留数据卷）
#   ./start_dashboard.sh status         # 查看运行状态
#   ./start_dashboard.sh logs           # 跟踪日志（Ctrl+C 退出）
#   ./start_dashboard.sh down -v        # 停止并删除数据卷（慎用，会清空 DB/缓存）
# ===========================================
set -euo pipefail
cd "$(dirname "$0")"                    # 定位到 etf-strategies/

COMPOSE=(docker compose)
CONTAINER="etf-dashboard"

say()  { printf '\033[1;34m[etf]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[etf]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[etf] %s\033[0m\n' "$*" >&2; exit 1; }

# ── 前置检查：docker / docker compose / 引擎 ──
require_docker() {
  command -v docker >/dev/null 2>&1 || die "未找到 docker，请先安装 Docker Desktop。"
  if ! docker info >/dev/null 2>&1; then
    die "Docker 引擎未运行。请先启动 Docker Desktop，等引擎就绪后重试。"
  fi
  docker compose version >/dev/null 2>&1 || die "docker compose 不可用（需 Compose v2）。"
}

# ── .env 兜底（不覆盖已存在文件）──
# 令牌为空时由宿主环境变量 ANTHROPIC_AUTH_TOKEN 兜底；两者皆无 compose 会报错提示填 .env。
ensure_env() {
  if [ -f .env ]; then
    return
  fi
  if [ -f .env.example ]; then
    cp .env.example .env
    warn "已从 .env.example 生成 .env（令牌为空时用宿主环境变量 ANTHROPIC_AUTH_TOKEN）。"
  else
    warn "未找到 .env.example，跳过（将依赖宿主环境变量）。"
  fi
}

# ── 等待健康检查 ──
wait_healthy() {
  local port="${DASHBOARD_PORT:-8000}" tries=0
  say "等待服务就绪 http://localhost:${port} ..."
  while [ "$tries" -lt 60 ]; do
    if curl -fsS -o /dev/null "http://localhost:${port}/" 2>/dev/null; then
      say "✅ 服务已就绪。"
      return 0
    fi
    sleep 2
    tries=$((tries + 1))
  done
  warn "⚠️ 60 次探测仍未就绪。查看日志: ./start_dashboard.sh logs"
}

# ── 首次启动时提示 admin 密码 ──
show_admin_hint() {
  local line
  line=$("${COMPOSE[@]}" logs 2>/dev/null | grep -a "默认管理员账号" | tail -1 || true)
  if [ -n "$line" ]; then
    warn "$line"
  fi
}

# ── 调度模式检测（提示，不阻断）──
# 系统 cron / 计划任务精确触发（etf-trigger-* / dsh-trigger-*）与容器内引擎 auto 的关系：
# - 检测到 etf-trigger-*（scheduler_cli 精确触发）→ 建议 DASHBOARD_SCHEDULER_ENABLED=0
#   （cron 模式：由计划任务触发，引擎 auto 关闭；两者幂等同 key 互斥，双开也安全但语义不清晰）
# - 检测到旧 dsh-trigger-* 仍启用 → 警告双跑，提示运行 setup_etf_scheduled_tasks.ps1 -Apply
check_schedule_mode() {
  if command -v schtasks >/dev/null 2>&1; then
    local etf_cnt dsh_cnt
    etf_cnt=$(schtasks /query /tn "etf-trigger-*" /fo csv 2>/dev/null | grep -c '"' || true)
    dsh_cnt=$(schtasks /query /tn "dsh-trigger-*" /fo csv 2>/dev/null | grep -c '"' || true)
    if [ "${etf_cnt:-0}" -gt 1 ]; then
      warn "⚠️ 检测到 etf-trigger-* 计划任务（系统精确触发模式）。"
      warn "   建议 .env 中 DASHBOARD_SCHEDULER_ENABLED=0 —— 由计划任务调 scheduler_cli 触发，引擎 auto 关闭。"
    fi
    if [ "${dsh_cnt:-0}" -gt 1 ]; then
      warn "⚠️ 检测到旧 dsh-trigger-* 计划任务仍存在/启用（可能与容器调度双跑）。"
      warn "   请运行 etf-strategies/scripts/setup_etf_scheduled_tasks.ps1 -Apply 迁移，或手动 Disable-ScheduledTask 停用。"
    fi
  fi
}

start() {
  require_docker
  ensure_env
  check_schedule_mode
  say "启动容器（首次会自动构建镜像）..."
  "${COMPOSE[@]}" up -d "$@"
  wait_healthy
  show_admin_hint
  say "完成。打开 http://localhost:${DASHBOARD_PORT:-8000} 查看；日志: ./start_dashboard.sh logs"
}

case "${1:-start}" in
  start)
    start
    ;;
  rebuild)
    start --build
    ;;
  stop)
    require_docker
    say "停止容器（保留数据卷）..."
    "${COMPOSE[@]}" stop
    ;;
  restart)
    require_docker
    say "重启容器..."
    "${COMPOSE[@]}" restart
    wait_healthy
    ;;
  status)
    require_docker
    "${COMPOSE[@]}" ps
    echo
    docker inspect -f '{{.State.Status}} ({{.State.Health.Status}})' "$CONTAINER" 2>/dev/null || true
    ;;
  logs)
    require_docker
    "${COMPOSE[@]}" logs -f --tail=100
    ;;
  down)
    require_docker
    say "停止并移除容器（$*）..."
    "${COMPOSE[@]}" down "$@"
    ;;
  *)
    echo "用法: $0 [start|rebuild|stop|restart|status|logs|down]"
    exit 1
    ;;
esac
