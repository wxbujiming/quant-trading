"""
期货回测主入口

运行: python scripts/run_futures_backtest.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime, timedelta
import pandas as pd
from loguru import logger

from src.data.futures_collector import FuturesDataCollector
from src.backtest.futures_engine import (
    FuturesBacktestEngine,
    OrderDirection,
    OffsetFlag,
)
from src.strategy.futures_strategy import (
    DualMaCrossStrategy,
    SimpleTrendStrategy,
)


# ──────────── 品种参数配置 ────────────

PRODUCT_CONFIG = {
    "RB": {   # 螺纹钢
        "name": "螺纹钢",
        "multiplier": 10,       # 10吨/手
        "margin_rate": 0.10,    # 10%保证金
        "commission_open": 0.0001,   # 万分之一
        "commission_close": 0.0001,
        "commission_close_today": 0.0,  # 平今免收
        "tick_size": 1,          # 1元/吨
        "min_move_value": 10,    # 每跳价值 = 1 * 10
    },
    "CU": {   # 沪铜
        "name": "沪铜",
        "multiplier": 5,        # 5吨/手
        "margin_rate": 0.12,    # 12%
        "commission_open": 0.00005,  # 万分之0.5
        "commission_close": 0.00005,
        "commission_close_today": 0.0001,  # 平今加倍
        "tick_size": 10,
        "min_move_value": 50,
    },
    "IF": {   # 沪深300股指期货
        "name": "沪深300股指",
        "multiplier": 300,      # 300元/点
        "margin_rate": 0.12,    # 12%
        "commission_open": 0.000023,  # 万分之0.23
        "commission_close": 0.000023,
        "commission_close_today": 0.00023,  # 平今十倍
        "tick_size": 0.2,
        "min_move_value": 60,
    },
    "SC": {   # 上海原油
        "name": "原油",
        "multiplier": 1000,     # 1000桶/手
        "margin_rate": 0.15,    # 15%
        "commission_open": 0.0001,
        "commission_close": 0.0001,
        "commission_close_today": 0.0,  # 平今免收
        "tick_size": 0.1,
        "min_move_value": 100,
    },
    "P": {    # 棕榈油
        "name": "棕榈油",
        "multiplier": 10,       # 10吨/手
        "margin_rate": 0.10,
        "commission_open": 0.0001,
        "commission_close": 0.0001,
        "commission_close_today": 0.0,
        "tick_size": 2,
        "min_move_value": 20,
    },
}


def run_single_backtest(symbol: str, start_date: str = "2020-01-01",
                        end_date: str = None, strategy_name: str = "双均线CTA"):
    """
    对单个品种运行期货回测
    
    Args:
        symbol: 品种代码 (如 RB, CU, IF)
        start_date: 起始日期
        end_date: 截止日期
        strategy_name: 策略名称
    """
    config = PRODUCT_CONFIG.get(symbol)
    if not config:
        logger.error(f"未知品种: {symbol}")
        return None
    
    logger.info(f"\n{'='*60}")
    logger.info(f"开始回测: {config['name']}({symbol}) - 策略:{strategy_name}")
    logger.info(f"{'='*60}")
    
    # 1. 获取数据
    collector = FuturesDataCollector()
    df = collector.get_continuous_daily(f"{symbol}0")
    
    if df.empty:
        logger.error(f"获取 {symbol} 数据失败")
        return None
    
    # 过滤日期
    df["date"] = pd.to_datetime(df["date"])
    if start_date:
        df = df[df["date"] >= start_date]
    if end_date:
        df = df[df["date"] <= end_date]
    
    logger.info(f"数据: {len(df)} 条, {df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()}")
    
    # 2. 创建回测引擎
    engine = FuturesBacktestEngine(
        initial_capital=1_000_000,          # 100万初始资金
        contract_multiplier=config["multiplier"],
        margin_rate=config["margin_rate"],
        commission_open=config["commission_open"],
        commission_close=config["commission_close"],
        commission_close_today=config.get("commission_close_today"),
        slippage=0.0001,
    )
    
    # 3. 创建策略
    if strategy_name == "双均线CTA":
        strategy = DualMaCrossStrategy(params={
            "fast_period": 10,
            "slow_period": 30,
            "atr_period": 14,
            "atr_multiplier": 2.0,
            "max_risk_pct": 0.02,
            "use_trailing_stop": True,
        })
    elif strategy_name == "趋势通道":
        strategy = SimpleTrendStrategy(params={
            "channel_period": 20,
            "atr_period": 14,
            "atr_multiplier": 2.0,
        })
    else:
        logger.error(f"未知策略: {strategy_name}")
        return None
    
    # 4. 运行回测
    df = df.set_index("date")
    result = engine.run(df, strategy, symbol)
    
    # 5. 打印结果
    engine.print_result(result)
    
    return result


def run_all_products():
    """测试所有品种"""
    results = []
    
    for symbol, config in PRODUCT_CONFIG.items():
        try:
            # 双均线策略
            r1 = run_single_backtest(symbol, start_date="2022-01-01", strategy_name="双均线CTA")
            if r1:
                results.append((f"{config['name']}({symbol})-双均线CTA", r1))
            
            # 趋势通道策略（可选）
            # r2 = run_single_backtest(symbol, start_date="2022-01-01", strategy_name="趋势通道")
            # if r2:
            #     results.append((f"{config['name']}({symbol})-趋势通道", r2))
        except Exception as e:
            logger.error(f"{config['name']}({symbol}) 回测失败: {e}")
    
    # 汇总对比
    if len(results) > 1:
        print("\n" + "=" * 60)
        print("                    策略对比汇总")
        print("=" * 60)
        print(f"{'品种':<30} {'收益率':>10} {'夏普':>8} {'最大回撤':>10} {'胜率':>8}")
        print("-" * 60)
        for name, r in results:
            print(f"{name:<30} {r.total_return:>10.2%} {r.sharpe_ratio:>8.2f} "
                  f"{r.max_drawdown:>10.2%} {r.win_rate:>8.2%}")
        print("=" * 60)


if __name__ == "__main__":
    # 单品种测试
    # run_single_backtest("RB", start_date="2022-01-01", strategy_name="双均线CTA")
    
    # 全品种测试
    run_all_products()
