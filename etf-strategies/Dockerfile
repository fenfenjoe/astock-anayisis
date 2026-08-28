# syntax=docker/dockerfile:1.7
# ===================================
# AStock ETF Dashboard — Docker 镜像
# ===================================
# 构建:  docker build -t etf-dashboard .
# 运行:  docker run -p 8000:8000 -v ./data:/app/data etf-dashboard
#
# 每日复盘定时任务依赖：镜像内安装 node + Claude Code CLI（claude -p），
# 认证走 ANTHROPIC_AUTH_TOKEN / ANTHROPIC_BASE_URL 环境变量（方舟 ARK）。
# 仓库根（prompt/报告/持仓/交易日历）需在运行时挂载，见 docker-compose.yml。

FROM python:3.11-slim-bookworm

# 时区
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 系统依赖（matplotlib 需要 libjpeg；curl/ca-certificates 供 nodesource 安装脚本用）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 安装 Python 依赖（利用 Docker 缓存层）
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

# Node.js + Claude Code CLI（每日复盘调度器用 claude -p 执行 prompt；
# 版本与宿主 ~/.claude/settings.json 使用的全局安装保持一致）
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code@2.1.229 \
    && npm install -g @deepseek-ai/dsh@0.1.0-rc.6 \
    && rm -rf /var/lib/apt/lists/* \
    && claude --version && dsh --version

# 复制应用代码
COPY . .

# 确保运行时目录存在
RUN mkdir -p /app/dashboard/data /app/cache /app/report /app/agent/data /root/.dsh/profiles

# 环境变量
ENV PYTHONUNBUFFERED=1
ENV DASHBOARD_PORT=8000

# 持久化卷
VOLUME ["/app/dashboard/data", "/app/cache", "/app/report"]

EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')" || exit 1

CMD ["python", "dashboard/app.py"]
