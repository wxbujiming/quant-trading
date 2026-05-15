# ============================================
# AI量化交易平台 - Makefile
# ============================================

.PHONY: help install dev test collect backtest clean jupyter web

help:  ## 显示帮助信息
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

install:  ## 安装依赖
	pip install -r requirements.txt

venv:  ## 创建虚拟环境
	python -m venv .venv
	@echo "虚拟环境已创建，请运行以下命令激活:"
	@echo "  Windows: .venv\\Scripts\\activate"
	@echo "  Linux/Mac: source .venv/bin/activate"

collect:  ## 采集数据
	python scripts/collect_data.py

backtest:  ## 运行回测
	python scripts/run_backtest.py

test:  ## 运行测试
	pytest tests/ -v

clean:  ## 清理缓存
	find . -type d -name "__pycache__" | xargs rm -rf
	find . -type f -name "*.pyc" | xargs rm -rf
	find . -type d -name ".pytest_cache" | xargs rm -rf
	find . -type d -name "*.egg-info" | xargs rm -rf

jupyter:  ## 启动Jupyter Lab
	jupyter lab --notebook-dir=notebooks

web:  ## 启动Web界面
	streamlit run web/app.py

lint:  ## 代码检查
	pylint src/

format:  ## 代码格式化
	black src/
	isort src/

data-clean:  ## 清理数据
	rm -rf data/raw/*
	rm -rf data/processed/*
	rm -rf data/cache/*

logs-clean:  ## 清理日志
	rm -rf logs/*
