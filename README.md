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
Phase 3: 期货CTA系统   ████████████████░░░░░  80% 🔄
Phase 4: AI模块       ░░░░░░░░░░░░░░░░░░░   0% ⬜
Phase 5: 实盘交易      ░░░░░░░░░░░░░░░░░░░   0% ⬜
Phase 6: 优化扩展      ░░░░░░░░░░░░░░░░░░░   0% ⬜
```


> 📅 当前阶段: Phase 3 (期货CTA系统) | 回测已完成，实盘连接已打通(SimNow 7x24)

## ✨ 特性

- 📊 **数据采集**: 支持AKShare采集A股/期货行情数据(腾讯证券+新浪财经+东方财富)
- 🧹 **数据清洗**: 8步清洗流程(缺失值/异常值/去重/停牌过滤/列名标准化+质量报告)
- 📐 **技术指标**: SMA/EMA/MACD/RSI/布林带/KDJ/ATR/CCI/OBV等12种指标
- ⚡ **熔断重试**: CircuitBreaker熔断器+指数退避重试+请求限速+本地Parquet缓存
- 📈 **A股回测**: 事件驱动回测引擎，支持滑点/手续费/印花税，5个内置策略
- 📉 **期货CTA回测**: 保证金/多空双向/T+0/逐日盯市回测引擎，2个CTA策略
- 📊 **可视化报告**: Plotly交互式图表(资金曲线/K线信号/月度热力图/多策略对比/HTML报告)
- 🛡️ **风控系统**: 持仓限制/仓位比例/每日亏损/止损线/交易频率，可扩展规则架构
- 💹 **实盘交易**: CTP/SimNow网关(模拟+实盘)+C++桥接DLL+订单/持仓/风险管理器
- 🤖 **AI能力**: 因子挖掘、机器学习预测、深度学习模型(开发中)

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
│   ├── 技术方案.md                    # ✅ 完整技术架构(16章)
│   ├── 项目计划.md                    # ✅ 6阶段开发计划
│   ├── 快速开发指南.md                # ✅ 快速上手指南
│   └── 常见问题.md                    # ✅ FAQ汇总
│
├── 📁 src/                           # 源代码
│   ├── core/                         # 核心模块
│   │   ├── config.py                 # ✅ 配置管理(YAML+环境变量)
│   │   └── logger.py                 # ✅ 日志系统(Loguru)
│   ├── data/                         # 数据模块
│   │   ├── collector.py              # ✅ A股数据采集器(双源+熔断+限速)
│   │   ├── futures_collector.py      # ✅ 期货数据采集器(主力合约+换月拼接)
│   │   ├── cleaner.py                # ✅ 数据清洗(8步流程+质量报告)
│   │   └── indicators.py             # ✅ 技术指标(12种)
│   ├── strategy/                     # 策略模块
│   │   ├── base.py                   # ✅ A股策略基类
│   │   ├── trend_strategy.py         # ✅ 趋势策略(双均线+MACD)
│   │   ├── mean_reversion_strategy.py# ✅ 均值回归(布林带+RSI+RSI2)
│   │   └── futures_strategy.py       # ✅ 期货CTA策略(双均线CTA+趋势通道)
│   ├── backtest/                     # 回测模块
│   │   ├── engine.py                 # ✅ A股回测引擎(事件驱动)
│   │   ├── futures_engine.py         # ✅ 期货CTA回测(保证金/多空/T+0)
│   │   └── visualizer.py             # ✅ 可视化(Plotly+HTML报告)
│   ├── trade/                        # 交易模块
│   │   ├── gateway.py                # ✅ 券商接口抽象基类
│   │   ├── ctp_gateway.py            # ✅ CTP/SimNow网关(模拟+实盘)
│   │   ├── ctp_real_api.py           # ✅ CTP实盘API(桥接DLL)
│   │   ├── order_manager.py          # ✅ 订单管理器
│   │   ├── position_manager.py       # ✅ 持仓管理器
│   │   └── risk_manager.py           # ✅ 风控系统(5条规则)
│   └── utils/
│       └── helpers.py                # ✅ 工具函数(绩效计算)
│
├── 📁 scripts/                       # 脚本
│   ├── collect_data.py               # ✅ A股数据采集
│   ├── run_backtest.py               # ✅ A股回测(5策略+HTML报告)
│   ├── run_futures_backtest.py       # ✅ 期货CTA回测(5品种)
│   ├── scheduled_collect.py          # ✅ 定时采集守护进程
│   ├── data_quality_check.py         # ✅ 数据质量检查(A-F评分)
│   ├── test_simnow.py                # ✅ SimNow仿真测试
│   ├── connect_simnow.py             # ✅ SimNow实盘联调
│   ├── test_data_cleaner.py          # ✅ 数据清洗测试
│   ├── test_new_strategies.py        # ✅ 新策略测试
│   └── verify_modules.py             # ✅ 模块导入验证
│
├── 📁 data/                          # 数据目录
│   ├── raw/stocks/                   # A股日线(10只+3指数)
│   ├── raw/futures/                  # 期货数据
│   ├── processed/                    # 处理后数据
│   └── cache/                        # 缓存
│
├── 📁 reports/                       # 回测报告
│   ├── strategy_comparison.html      # ✅ 多策略对比
│   └── backtest_*.html               # ✅ 各策略独立报告
│
├── 📁 ctp_bridge/                    # C++桥接DLL源码(SDK+头文件)
│
├── 📁 config/                        # 配置
│   └── secrets.yaml.example          # ✅ 密钥模板
│
├── 📁 .venv/                         # ✅ 虚拟环境
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

