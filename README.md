# AI量化交易平台

一个基于Python的个人AI量化交易平台，覆盖**A股**和**期货**两大市场。

## 📚 文档导航

| 文档 | 说明 |
|------|------|
| [技术方案](docs/技术方案.md) | 详细的技术架构设计 |
| [项目计划](docs/项目计划.md) | 开发计划和进度追踪 |

| [常见问题](docs/常见问题.md) | FAQ常见问题汇总 |
核心模块设计
1. 技术方案文档 (docs/技术方案.md)
项目概述和目标市场
技术架构设计
核心模块设计
数据流设计
券商接口对接方案
风险控制策略
性能优化方案
2. 项目计划文档 (docs/项目计划.md)
5个开发阶段规划
详细任务清单
里程碑定义
风险与应对措施
开发规范
3. 快速开发指南 (docs/快速开发指南.md)
环境准备步骤
核心功能使用示例
常见问题解答



Phase 1: 基础框架     ████████████████████ 100% ✅
Phase 2: A股回测系统   ████████████████████ 100% ✅
Phase 3: 期货CTA系统   ████████████░░░░░░░░  60% 🔄
Phase 4: AI模块       ░░░░░░░░░░░░░░░░░░░   0% ⬜
Phase 5: 实盘交易      ░░░░░░░░░░░░░░░░░░░   0% ⬜
Phase 6: 优化扩展      ░░░░░░░░░░░░░░░░░░░   0% ⬜
```


> 📅 当前阶段: Phase 3 (期货CTA系统) | 回测已完成，实盘待开发

## ✨ 特性

- 📊 **数据采集**: 支持AKShare采集A股行情数据(腾讯证券+新浪财经+东方财富)
- ⚡ **熔断重试**: CircuitBreaker熔断器+指数退避重试+请求限速+本地Parquet缓存
- 🤖 **AI能力**: 因子挖掘、机器学习预测、深度学习模型(开发中)
- 📈 **策略回测**: 事件驱动回测引擎，支持滑点、手续费模拟
- 💹 **实盘交易**: 支持CTP/QMT/IB等券商接口(开发中)
- 📉 **绩效分析**: 收益率、最大回撤、夏普比率等指标

## 🎯 目标市场

| 市场 | 交易频率 | 策略类型 | 优先级 |
|------|----------|----------|--------|
| A股 | 日线级别 | 因子选股、AI预测 | ⭐⭐⭐⭐⭐ |
| 期货 | 日内/分钟级 | CTA、套利 | ⭐⭐⭐⭐ |
| 美股 | 日线/高频 | 趋势跟踪 | ⭐⭐⭐ |

## 🚀 快速开始

### 1. 环境准备

```powershell
# 激活虚拟环境 (Windows)
.\.venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 采集数据

```bash
python scripts/collect_data.py
```

### 3. 运行回测

```bash
python scripts/run_backtest.py
```

### 4. 验证环境

```python
python -c "import pandas; import akshare; from loguru import logger; print('环境就绪！')"
```

## 📁 项目结构

```
ai-quant-platform/
├── 📁 docs/                          # 文档目录
│   ├── 技术方案.md                    # ✅ 技术架构设计文档
│   ├── 项目计划.md                    # ✅ 开发计划和进度
│   └── 快速开发指南.md                # ✅ 快速上手指南
│
├── 📁 src/                           # 源代码
│   ├── core/                         # 核心模块
│   │   ├── config.py                 # ✅ 配置管理
│   │   └── logger.py                 # ✅ 日志系统
│   ├── data/
│   │   └── collector.py              # ✅ 数据采集器
│   ├── strategy/
│   │   ├── base.py                   # ✅ 策略基类
│   │   └── trend_strategy.py         # ✅ 趋势策略示例
│   ├── backtest/
│   │   └── engine.py                 # ✅ 回测引擎
│   └── utils/
│       └── helpers.py                # ✅ 工具函数
│
├── 📁 scripts/                       # 脚本
│   ├── collect_data.py               # ✅ 数据采集脚本
│   └── run_backtest.py               # ✅ 回测脚本
│
├── 📁 data/                          # 数据目录
│   ├── raw/                          # 原始数据
│   ├── processed/                    # 处理后数据
│   └── cache/                        # 缓存
│
├── 📁 config/                        # 配置
│   └── secrets.yaml.example          # ✅ 密钥模板
│
├── 📁 .venv/                         # 虚拟环境 ✅
├── requirements.txt                  # ✅ 依赖文件
├── Makefile                          # ✅ 开发命令
└── README.md                         # ✅ 项目说明

## 🛠️ 开发命令

```bash
make help        # 显示所有命令
make install     # 安装依赖
make collect     # 采集数据
make backtest    # 运行回测
make jupyter     # 启动Jupyter Lab
make clean       # 清理缓存
```

## 📦 已安装依赖

| 包名 | 说明 |
|------|------|
| pandas 2.0.3 | 数据处理 |
| numpy 1.26.4 | 数值计算 |
| akshare 1.18.60 | A股数据采集 |
| loguru 0.7.3 | 日志系统 |
| plotly 6.7.0 | 可视化 |
| rich 15.0.0 | 命令行美化 |
| typer 0.25.1 | CLI框架 |
| requests 2.34.0 | HTTP请求 |
| beautifulsoup4 4.14.3 | HTML解析 |
| lxml 6.1.0 | XML解析 |
| py_mini_racer 0.6.0 | JS解释器(AKShare依赖) |
| curl_cffi 0.11.1 | HTTP/2支持(AKShare依赖) |

> **注意**: scikit-learn, xgboost, lightgbm等需要C编译器的包暂未安装，后续可安装Visual Studio Build Tools后补充

## 🧪 代码示例

### 数据采集

```python
from src.data.collector import DataCollector

collector = DataCollector()
stock_list = collector.get_stock_list()                        # 获取股票列表
df = collector.get_stock_history("000001")                     # 获取历史K线(自动走腾讯证券)
batch = collector.get_stock_history_batch(["000001","600000"]) # 批量采集(带限速)
info = collector.get_cache_info()                              # 查看本地缓存
```

### 策略开发

```python
from src.strategy.base import BaseStrategy, Signal

class MyStrategy(BaseStrategy):
    def init(self):
        pass
    def next(self, bar) -> Signal:
        return Signal.BUY  # 或 Signal.SELL / Signal.HOLD
```

### 运行回测

```python
from src.backtest.engine import BacktestEngine
from src.strategy.trend_strategy import SmaCrossStrategy

engine = BacktestEngine(initial_cash=100000)
strategy = SmaCrossStrategy(params={'fast_period': 10, 'slow_period': 30})
result = engine.run(data, strategy)
engine.print_result(result)
```

---

## 📊 回测结果 (平安银行000001, 2020-2024)

| 策略 | 总收益率 | 夏普 | 胜率 |
|------|:-------:|:----:|:---:|
| 双均线(10,30) | -37.85% | -0.38 | 21% |
| MACD(12,26,9) | +7.72% | 0.19 | 37% |
| 布林带(20,2) | -10.84% | -0.12 | 59% |
| RSI(14,30/70) | -10.66% | -0.02 | 52% |
| **RSI2短线反转** | **+11.35%** | **0.23** | **38%** |

## 📄 License

MIT License

