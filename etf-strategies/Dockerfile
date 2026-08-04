# syntax=docker/dockerfile:1.7
# ===================================
# AStock ETF Dashboard — Docker 镜像
# ===================================
# 构建:  docker build -t etf-dashboard .
# 运行:  docker run -p 8000:8000 -v ./data:/app/data etf-dashboard

FROM python:3.11-slim-bookworm

# 时区
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 系统依赖（matplotlib 需要 libjpeg）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 安装 Python 依赖（利用 Docker 缓存层）
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

# 复制应用代码
COPY . .

# 确保运行时目录存在
RUN mkdir -p /app/dashboard/data /app/cache /app/report

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
