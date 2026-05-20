# ============================================
# AI量化交易平台 - Docker 镜像
# ============================================
# 支持 amd64 / arm64
# 包含: Web 面板, 策略引擎(模拟/SimNow), 调度器, 回测
#
# CTP 实盘交易需要挂载:
#   - ctp_flow/  (CTP 流目录)
#   - config/secrets.yaml  (CTP 凭据)
#   - data/live_state/  (SQLite/状态)
#
# 构建:
#   docker build -t quant-trading .
#
# 运行 Web 面板:
#   docker run -p 8501:8501 quant-trading
#
# 运行调度器:
#   docker run quant-trading scheduler
#
# 运行模拟回放:
#   docker run quant-trading simulate --symbol RB --days 10
# ============================================

# ---- 构建阶段 ----
FROM python:3.11-slim AS builder

WORKDIR /app

# 系统依赖（akshare 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 安装 CTP 接口 (Linux amd64)
RUN pip install --no-cache-dir vnpy_ctp

# ---- 运行阶段 ----
FROM python:3.11-slim

WORKDIR /app

# 运行时系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 从构建阶段复制已安装的包
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

# 复制项目代码
COPY . .

# 创建数据目录
RUN mkdir -p data/live_state data/raw data/cache data/processed logs ctp_flow/td ctp_flow/md config

# 暴露端口（Web 面板 + Streamlit）
EXPOSE 8501

# 环境变量
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Shanghai

# 默认入口: Web 面板
CMD ["streamlit", "run", "web/app.py", "--server.port=8501", "--server.address=0.0.0.0"]

# ──────────── 备用入口 ────────────
# scheduler:   docker run --entrypoint python quant-trading scripts/scheduler.py --daemon
# simulate:    docker run --entrypoint python quant-trading scripts/run_simulation.py --symbol RB --days 20
# engine:      docker run --entrypoint python quant-trading scripts/run_live_engine.py --symbol RB2610 --simulate
# status:      docker run --entrypoint python quant-trading scripts/status.py --watch
