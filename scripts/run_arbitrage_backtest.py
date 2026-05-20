"""
套利回测运行脚本

支持：
1. 跨期套利：同品种不同月份（如 RB2505 vs RB2510）
2. 跨品种套利：相关品种价差（如 RB vs HC）

用法：
    python scripts/run_arbitrage_backtest.py          # 运行所有示例
    python scripts/run_arbitrage_backtest.py --pair cross_period   # 仅跨期
    python scripts/run_arbitrage_backtest.py --pair cross_product  # 仅跨品种

数据来源：AKShare (自动从新浪获取期货数据)
"""
import sys
import os
from datetime import datetime, timedelta
from typing import Dict, Optional

# 确保能导入 src
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from loguru import logger

from src.data.futures_collector import FuturesDataCollector
from src.trade.contract_manager import PRODUCT_SPECS
from src.arbitrage import (
    SpreadBuilder,
    ArbitrageBacktestEngine,
    ZScoreArbitrageStrategy,
)


# ──────────── 品种参数 ────────────

def _spec(base: str) -> dict:
    """从 PRODUCT_SPECS 获取品种配置"""
    return PRODUCT_SPECS.get(base, {})


# ──────────── 数据加载 ────────────

def load_contract_data(contract: str, collector: FuturesDataCollector,
                       use_cache: bool = True) -> pd.DataFrame:
    """
    加载合约日线数据，优先从缓存读取。

    Args:
        contract: 合约代码 (如 RB2505, RB0)
        collector: 数据采集器
        use_cache: 是否使用本地缓存

    Returns:
        DataFrame with date/open/high/low/close/volume/hold/settle
    """
    cache_name = f"contract_{contract}"

    if use_cache:
        cached = collector.load_from_cache(cache_name)
        if not cached.empty:
            logger.info(f"[{contract}] 从缓存加载: {len(cached)} 条")
            return cached

    # 从 AKShare 获取
    df = collector.get_contract_daily(contract)
    if df.empty:
        raise ValueError(f"获取 {contract} 数据失败")

    if use_cache and not df.empty:
        collector.save_to_cache(df, cache_name)

    return df


# ──────────── 运行单次套利回测 ────────────

def run_arbitrage_backtest(
    leg1_contract: str,
    leg2_contract: str,
    leg1_base: str,
    leg2_base: str,
    spread_method: str = "price_diff",
    zscore_window: int = 20,
    entry_z: float = 2.0,
    exit_z: float = 0.5,
    stop_z: float = 3.5,
    trade_volume: int = 1,
    initial_capital: float = 500_000,
    use_cache: bool = True,
) -> dict:
    """
    运行套利回测。

    Args:
        leg1_contract: 腿1 合约代码
        leg2_contract: 腿2 合约代码
        leg1_base: 腿1 品种代码 (用于获取乘数/保证金等)
        leg2_base: 腿2 品种代码
        spread_method: 价差计算方法
        zscore_window: z-score 窗口
        entry_z: 入场阈值
        exit_z: 出场阈值
        stop_z: 止损阈值
        trade_volume: 交易手数
        initial_capital: 初始资金
        use_cache: 是否使用数据缓存

    Returns:
        {result: ArbitrageBacktestResult, spread_df: DataFrame}
    """
    collector = FuturesDataCollector()

    # 获取数据
    logger.info(f"获取数据: {leg1_contract} + {leg2_contract}")
    leg1_df = load_contract_data(leg1_contract, collector, use_cache)
    leg2_df = load_contract_data(leg2_contract, collector, use_cache)

    # 构建价差
    logger.info(f"构建价差: method={spread_method}, zscore_window={zscore_window}")
    builder = SpreadBuilder(leg1_df, leg2_df)
    spread_df = builder.build(
        method=spread_method,
        zscore_window=zscore_window,
    )

    stats = builder.get_spread_stats()
    logger.info(f"价差统计: mean={stats.get('mean', 0):.2f}, "
                f"std={stats.get('std', 0):.2f}")

    # 获取品种规格
    spec1 = _spec(leg1_base)
    spec2 = _spec(leg2_base)

    # 初始化引擎
    logger.info(f"初始化引擎: 资金={initial_capital:,.0f}")
    engine = ArbitrageBacktestEngine(
        initial_capital=initial_capital,
        leg1_symbol=leg1_base,
        leg1_multiplier=spec1.get("multiplier", 10),
        leg1_margin_rate=spec1.get("margin_rate", 0.10),
        leg1_commission_open=spec1.get("commission_open", 0.0001),
        leg1_commission_close=spec1.get("commission_close", 0.0001),
        leg1_commission_close_today=spec1.get("commission_close_today"),
        leg1_name=leg1_contract,
        leg2_symbol=leg2_base,
        leg2_multiplier=spec2.get("multiplier", 10),
        leg2_margin_rate=spec2.get("margin_rate", 0.10),
        leg2_commission_open=spec2.get("commission_open", 0.0001),
        leg2_commission_close=spec2.get("commission_close", 0.0001),
        leg2_commission_close_today=spec2.get("commission_close_today"),
        leg2_name=leg2_contract,
    )

    # 策略
    strategy = ZScoreArbitrageStrategy(params={
        "entry_z": entry_z,
        "exit_z": exit_z,
        "stop_z": stop_z,
        "trade_volume": trade_volume,
    })

    # 运行回测
    result = engine.run(spread_df, strategy)
    engine.print_result(result, strategy_name="Z-Score 套利策略")

    return {"result": result, "spread_df": spread_df}


# ──────────── 示例：跨期套利 ────────────

def run_cross_period():
    """
    跨期套利示例：RB2505 vs RB2510 (螺纹钢主力 vs 次主力)
    """
    print("\n" + "█" * 60)
    print("  示例 1: 跨期套利 — RB2505 vs RB2510")
    print("█" * 60)

    return run_arbitrage_backtest(
        leg1_contract="RB2505",
        leg2_contract="RB2510",
        leg1_base="RB",
        leg2_base="RB",
        spread_method="price_diff",
        zscore_window=20,
        entry_z=2.0,
        exit_z=0.5,
        stop_z=3.5,
        trade_volume=2,
        initial_capital=500_000,
    )


# ──────────── 示例：跨品种套利 ────────────

def run_cross_product():
    """
    跨品种套利示例：RB (螺纹钢) vs HC (热轧卷板)

    螺纹钢和热轧卷板均在上期所交易，乘数=10，保证金=10%，
    两者价格高度相关，适合价差套利。
    """
    print("\n" + "█" * 60)
    print("  示例 2: 跨品种套利 — RB0 vs HC0 (螺纹钢 vs 热卷)")
    print("█" * 60)

    return run_arbitrage_backtest(
        leg1_contract="RB0",
        leg2_contract="HC0",
        leg1_base="RB",
        leg2_base="HC",
        spread_method="price_diff",
        zscore_window=20,
        entry_z=2.0,
        exit_z=0.5,
        stop_z=3.5,
        trade_volume=2,
        initial_capital=500_000,
    )


# ──────────── 多参数扫描 ────────────

def run_param_sweep():
    """
    参数扫描：测试不同 entry_z 和 exit_z 的效果
    """
    print("\n" + "█" * 60)
    print("  参数扫描: RB vs HC 不同入口/出口阈值")
    print("█" * 60)

    collector = FuturesDataCollector()
    leg1_df = load_contract_data("RB0", collector)
    leg2_df = load_contract_data("HC0", collector)

    builder = SpreadBuilder(leg1_df, leg2_df)
    spread_df = builder.build(method="price_diff", zscore_window=20)
    spec = _spec("RB")

    results = []
    entry_values = [1.5, 2.0, 2.5]
    exit_values = [0.3, 0.5, 0.8]

    for entry_z in entry_values:
        for exit_z in exit_values:
            engine = ArbitrageBacktestEngine(
                initial_capital=500_000,
                leg1_symbol="RB", leg1_multiplier=10, leg1_margin_rate=0.10,
                leg2_symbol="HC", leg2_multiplier=10, leg2_margin_rate=0.10,
                leg1_name="RB", leg2_name="HC",
            )
            strategy = ZScoreArbitrageStrategy(params={
                "entry_z": entry_z, "exit_z": exit_z,
                "stop_z": 3.5, "trade_volume": 2,
            })
            result = engine.run(spread_df, strategy)
            results.append({
                "entry_z": entry_z, "exit_z": exit_z,
                "return": result.total_return,
                "sharpe": result.sharpe_ratio,
                "max_dd": result.max_drawdown,
                "trades": result.total_trades,
                "win_rate": result.win_rate,
            })
            logger.info(f"  entry_z={entry_z}, exit_z={exit_z} → "
                        f"收益={result.total_return:.2%}, "
                        f"夏普={result.sharpe_ratio:.2f}")

    print("\n参数扫描结果:")
    print(f"{'entry_z':<10} {'exit_z':<10} {'收益率':>10} {'夏普':>8} "
          f"{'最大回撤':>10} {'交易次数':>8} {'胜率':>8}")
    print("-" * 64)
    for r in results:
        print(f"{r['entry_z']:<10} {r['exit_z']:<10} "
              f"{r['return']:>10.2%} {r['sharpe']:>8.2f} "
              f"{r['max_dd']:>10.2%} {r['trades']:>8} "
              f"{r['win_rate']:>8.2%}")

    return results


# ──────────── 主入口 ────────────

def main():
    """主入口"""
    print("=" * 60)
    print("        期货套利回测系统")
    print("=" * 60)

    # 解析命令行参数
    pair = "all"
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if arg.startswith("--pair="):
                pair = arg.split("=")[1]
            elif arg == "--sweep":
                pair = "sweep"

    if pair in ("all", "cross_period"):
        try:
            run_cross_period()
        except Exception as e:
            logger.error(f"跨期套利失败: {e}")

    if pair in ("all", "cross_product"):
        try:
            run_cross_product()
        except Exception as e:
            logger.error(f"跨品种套利失败: {e}")

    if pair == "sweep":
        try:
            run_param_sweep()
        except Exception as e:
            logger.error(f"参数扫描失败: {e}")

    print("\n完成。")


if __name__ == "__main__":
    main()
