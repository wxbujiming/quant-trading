"""
投资组合回测脚本

对比不同资金分配策略在多个品种上的表现。

用法:
    python scripts/run_portfolio_backtest.py                          # 默认组合
    python scripts/run_portfolio_backtest.py --allocator risk_parity  # 风险平价
    python scripts/run_portfolio_backtest.py --symbols RB,CU,IF       # 指定品种
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
from datetime import datetime
import pandas as pd
from loguru import logger

from src.data.futures_collector import FuturesDataCollector
from src.strategy.futures_strategy import DualMaCrossStrategy
from src.portfolio import (
    EqualWeightAllocator,
    RiskParityAllocator,
    FixedWeightAllocator,
    run_portfolio_backtest,
)

# ──────────── 品种参数 ────────────

PRODUCT_CONFIG = {
    "RB": {"name": "螺纹钢", "multiplier": 10, "margin_rate": 0.10,
           "commission_open": 0.0001, "commission_close": 0.0001,
           "commission_close_today": 0.0},
    "CU": {"name": "沪铜", "multiplier": 5, "margin_rate": 0.12,
           "commission_open": 0.00005, "commission_close": 0.00005,
           "commission_close_today": 0.0001},
    "IF": {"name": "沪深300股指", "multiplier": 300, "margin_rate": 0.12,
           "commission_open": 0.000023, "commission_close": 0.000023,
           "commission_close_today": 0.00023},
    "SC": {"name": "原油", "multiplier": 1000, "margin_rate": 0.15,
           "commission_open": 0.0001, "commission_close": 0.0001,
           "commission_close_today": 0.0},
    "P":  {"name": "棕榈油", "multiplier": 10, "margin_rate": 0.10,
           "commission_open": 0.0001, "commission_close": 0.0001,
           "commission_close_today": 0.0},
}

STRATEGY_PARAMS = {
    "fast_period": 10,
    "slow_period": 30,
    "atr_period": 14,
    "atr_multiplier": 2.0,
    "max_risk_pct": 0.02,
    "use_trailing_stop": True,
}

TOTAL_CAPITAL = 1_000_000
START_DATE = "2020-01-01"


def load_data(symbol: str) -> pd.DataFrame:
    """加载品种日线数据"""
    collector = FuturesDataCollector()
    df = collector.get_continuous_daily(f"{symbol}0")
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["date"] >= START_DATE]
    df = df.set_index("date")
    df.sort_index(inplace=True)
    return df


def main(symbols=None, allocator_name="equal"):
    """运行组合回测"""
    symbols = symbols or list(PRODUCT_CONFIG.keys())

    # 加载数据
    logger.info("加载数据...")
    data_dict = {}
    for s in symbols:
        df = load_data(s)
        if len(df) >= 60:
            data_dict[s] = df
            logger.info(f"  {s}: {len(df)} 行, {df.index[0].date()} ~ {df.index[-1].date()}")
        else:
            logger.warning(f"  {s}: 数据不足 ({len(df)}行), 跳过")

    if len(data_dict) < 1:
        logger.error("没有足够的数据")
        return

    symbols = list(data_dict.keys())

    # 创建策略（每个品种独立实例）
    strategies = {}
    for s in symbols:
        strategies[s] = DualMaCrossStrategy(params=dict(STRATEGY_PARAMS))

    # 分配策略
    allocator_map = {
        "equal": EqualWeightAllocator(),
        "risk_parity": RiskParityAllocator(window=60),
        "fixed": FixedWeightAllocator(
            {s: 1.0 / len(symbols) for s in symbols}
        ),
    }
    allocator = allocator_map.get(allocator_name, EqualWeightAllocator())

    # 运行组合回测
    result = run_portfolio_backtest(
        data_dict=data_dict,
        strategies=strategies,
        symbols=symbols,
        total_capital=TOTAL_CAPITAL,
        allocator=allocator,
        product_configs=PRODUCT_CONFIG,
        verbose=True,
    )

    return result


def compare_allocators(symbols=None):
    """对比不同分配策略"""
    allocators = ["equal", "risk_parity"]
    results = []

    for name in allocators:
        logger.info(f"\n{'='*60}")
        logger.info(f"分配策略: {name}")
        logger.info(f"{'='*60}")
        r = main(symbols, name)
        if r:
            results.append((name, r))

    if len(results) > 1:
        print("\n" + "=" * 60)
        print("            分配策略对比")
        print("=" * 60)
        print(f"{'策略':<16} {'收益率':>10} {'夏普':>8} {'最大回撤':>10} {'胜率':>8}")
        print("-" * 60)
        for name, r in results:
            print(f"{name:<16} {r.total_return:>10.2%} {r.sharpe_ratio:>8.2f} "
                  f"{r.max_drawdown:>10.2%} {r.win_rate:>8.2%}")
        print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="投资组合回测")
    parser.add_argument("--allocator", type=str, default=None,
                        choices=["equal", "risk_parity", "fixed", "compare"],
                        help="分配策略")
    parser.add_argument("--symbols", type=str, default=None,
                        help="品种列表，逗号分隔")
    args = parser.parse_args()

    symbol_list = args.symbols.split(",") if args.symbols else None

    if args.allocator == "compare":
        compare_allocators(symbol_list)
    else:
        main(symbol_list, args.allocator or "equal")
