"""
多时间框架回测脚本

对比单时间框架 vs 多时间框架策略在同一品种上的表现。

用法:
    python scripts/run_mtf_backtest.py                          # 全品种对比
    python scripts/run_mtf_backtest.py --symbol RB              # 单品种
    python scripts/run_mtf_backtest.py --strategy triple        # 仅三TF策略
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
from datetime import datetime
import pandas as pd
from loguru import logger

from src.data.futures_collector import FuturesDataCollector
from src.backtest.futures_engine import FuturesBacktestEngine
from src.strategy.futures_strategy import DualMaCrossStrategy
from src.strategy.mtf_strategies import (
    WeeklyFilteredMaStrategy,
    TripleTimeframeStrategy,
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

CAPITAL = 1_000_000
START_DATE = "2020-01-01"

STRATEGY_FACTORIES = {
    "双均线CTA": lambda: DualMaCrossStrategy(params={
        "fast_period": 10, "slow_period": 30, "atr_period": 14,
        "atr_multiplier": 2.0, "max_risk_pct": 0.02, "use_trailing_stop": True,
    }),
    "周线过滤+均线": lambda: WeeklyFilteredMaStrategy(params={
        "fast_period": 10, "slow_period": 30, "atr_period": 14,
        "atr_multiplier": 2.0, "max_risk_pct": 0.02, "use_trailing_stop": True,
        "weekly_sma_fast": 20, "weekly_sma_slow": 40,
    }),
    "三时间框架": lambda: TripleTimeframeStrategy(params={
        "atr_multiplier": 2.0, "max_risk_pct": 0.02, "use_trailing_stop": True,
        "daily_sma_period": 20, "rsi_period": 14,
    }),
}


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


def run_single(symbol: str, strategy_name: str, strategy):
    """运行单次回测"""
    config = PRODUCT_CONFIG.get(symbol)
    if not config:
        return None

    data = load_data(symbol)
    if len(data) < 60:
        logger.warning(f"{symbol}: 数据不足 ({len(data)}行)")
        return None

    engine = FuturesBacktestEngine(
        initial_capital=CAPITAL,
        contract_multiplier=config["multiplier"],
        margin_rate=config["margin_rate"],
        commission_open=config["commission_open"],
        commission_close=config["commission_close"],
        commission_close_today=config.get("commission_close_today"),
        slippage=0.0001,
    )
    result = engine.run(data, strategy, symbol)
    return result


def run_comparison(symbols=None, strategies=None):
    """运行多策略对比回测"""
    all_results = []

    target_symbols = symbols or list(PRODUCT_CONFIG.keys())
    target_strategies = strategies or list(STRATEGY_FACTORIES.keys())

    for symbol in target_symbols:
        config = PRODUCT_CONFIG.get(symbol)
        if not config:
            continue

        for sname in target_strategies:
            factory = STRATEGY_FACTORIES.get(sname)
            if not factory:
                continue

            logger.info(f"回测: {config['name']}({symbol}) × {sname}")
            strategy = factory()
            result = run_single(symbol, sname, strategy)
            if result:
                all_results.append((symbol, config["name"], sname, result))

    # 打印对比表
    print_table(all_results)
    return all_results


def print_table(results):
    """打印多策略对比表"""
    if not results:
        print("无回测结果")
        return

    print("\n" + "=" * 120)
    print("           多时间框架策略对比回测")
    print("=" * 120)
    header = f"{'品种':<12} {'策略':<20} {'收益率':>10} {'夏普':>8} {'最大回撤':>10} {'胜率':>8} {'交易次数':>8}"
    print(header)
    print("-" * 120)

    for symbol, name, sname, r in results:
        print(f"{symbol:<6}({name:<4}) {sname:<20} "
              f"{r.total_return:>10.2%} {r.sharpe_ratio:>8.2f} "
              f"{r.max_drawdown:>10.2%} {r.win_rate:>8.2%} "
              f"{r.total_trades:>8}")

    # 按品种分组对比
    print("\n" + "-" * 120)
    print("          同品种 MTF vs 单TF 差异")
    print("-" * 120)
    by_symbol = {}
    for symbol, name, sname, r in results:
        by_symbol.setdefault(symbol, []).append((sname, r))

    for symbol, runs in by_symbol.items():
        base_ret = None
        for sname, r in runs:
            if sname == "双均线CTA":
                base_ret = r.total_return
        if base_ret is not None:
            for sname, r in runs:
                if sname != "双均线CTA":
                    diff = r.total_return - base_ret
                    arrow = "▲" if diff > 0 else "▼"
                    print(f"  {symbol}: {sname} vs 双均线CTA → {arrow} {diff:+.2%}")

    print("=" * 120)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="多时间框架回测")
    parser.add_argument("--symbol", type=str, default=None, help="品种代码")
    parser.add_argument("--strategy", type=str, default=None,
                        choices=list(STRATEGY_FACTORIES.keys()),
                        help="策略名称")
    args = parser.parse_args()

    symbols = [args.symbol] if args.symbol else None
    strategies = [args.strategy] if args.strategy else None
    run_comparison(symbols, strategies)
