"""
投资组合回测与聚合

提供:
  - PortfolioResult 数据类 — 组合级别的回测结果
  - aggregate_results() — 聚合多个品种的回测结果
  - run_portfolio_backtest() — 一键运行组合回测
"""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import pandas as pd
import numpy as np
from loguru import logger

from src.backtest.futures_engine import (
    FuturesBacktestEngine,
    FuturesBacktestResult,
)
from src.portfolio.allocator import AllocationStrategy, EqualWeightAllocator


@dataclass
class PortfolioResult:
    """组合回测结果"""
    initial_capital: float
    final_capital: float
    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe_ratio: float
    total_trades: int
    win_rate: float
    profit_factor: float
    by_symbol: Dict[str, FuturesBacktestResult] = field(default_factory=dict)
    daily_equity: pd.Series = field(default_factory=pd.Series)
    daily_returns: pd.Series = field(default_factory=pd.Series)


def aggregate_results(
    symbol_results: Dict[str, FuturesBacktestResult],
    initial_capital: float,
    daily_equity: Optional[pd.Series] = None,
) -> PortfolioResult:
    """
    聚合多个品种的回测结果为组合结果。

    Args:
        symbol_results: {symbol: FuturesBacktestResult}
        initial_capital: 组合初始资金
        daily_equity: 组合每日权益序列（如无可自动计算）

    Returns:
        PortfolioResult
    """
    results = list(symbol_results.values())
    if not results:
        return PortfolioResult(
            initial_capital=initial_capital,
            final_capital=initial_capital,
            total_return=0.0,
            annual_return=0.0,
            max_drawdown=0.0,
            sharpe_ratio=0.0,
            total_trades=0,
            win_rate=0.0,
            profit_factor=0.0,
            by_symbol=dict(symbol_results),
        )

    # 组合指标
    final_capital = sum(r.final_capital for r in results)
    total_trades = sum(r.total_trades for r in results)
    total_wins = sum(r.total_trades * r.win_rate for r in results)
    win_rate = total_wins / max(total_trades, 1)
    total_return = (final_capital / initial_capital) - 1

    # 年化收益（取各品种中最长周期）
    years = max(
        ((r.final_capital / r.initial_capital) - 1) / max(r.total_return, 0.001) * max(r.total_return, 0)
        if r.total_return != 0 else 1.0
        for r in results
    )
    # 简略年化
    annual_return = (1 + total_return) ** (1 / max(years, 1)) - 1 if years > 0 else 0.0

    # 最大回撤和夏普基于合并后的权益序列
    if daily_equity is not None and len(daily_equity) > 1:
        equity = daily_equity
    else:
        equity = _merge_daily_equity(symbol_results, initial_capital)

    max_dd = _calc_max_drawdown(equity) if len(equity) > 1 else 0.0

    daily_ret = equity.pct_change().dropna()
    sharpe = 0.0
    if len(daily_ret) > 1 and daily_ret.std() > 0:
        sharpe = daily_ret.mean() / daily_ret.std() * np.sqrt(252)

    # 盈亏比
    profit_factor = 0.0
    gross_profit = sum(max(0, r.total_return * r.initial_capital) for r in results)
    gross_loss = sum(max(0, -r.total_return * r.initial_capital) for r in results)
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss

    return PortfolioResult(
        initial_capital=initial_capital,
        final_capital=final_capital,
        total_return=total_return,
        annual_return=annual_return,
        max_drawdown=max_dd,
        sharpe_ratio=sharpe,
        total_trades=total_trades,
        win_rate=win_rate,
        profit_factor=profit_factor,
        by_symbol=dict(symbol_results),
        daily_equity=equity,
        daily_returns=daily_ret if len(daily_ret) > 1 else pd.Series(dtype=float),
    )


def _merge_daily_equity(
    symbol_results: Dict[str, FuturesBacktestResult],
    initial_capital: float,
) -> pd.Series:
    """合并各品种的每日权益序列"""
    all_equities = []
    for symbol, r in symbol_results.items():
        if r.settlements and len(r.settlements) > 1:
            dates = [s.date for s in r.settlements]
            equities = [s.total_equity for s in r.settlements]
            s = pd.Series(equities, index=pd.DatetimeIndex(dates), name=symbol)
            all_equities.append(s)

    if not all_equities:
        return pd.Series(dtype=float)

    # 合并（各品种按日期相加）
    merged = pd.concat(all_equities, axis=1).sum(axis=1)
    # 减去重复计算的初始资金，加上组合初始资金
    overlapping_capital = sum(
        r.initial_capital for r in symbol_results.values()
    )
    merged = merged - overlapping_capital + initial_capital
    return merged


def _calc_max_drawdown(equity: pd.Series) -> float:
    """计算最大回撤"""
    rolling_max = equity.expanding().max()
    drawdowns = (equity - rolling_max) / rolling_max
    return float(abs(drawdowns.min())) if len(drawdowns) > 0 else 0.0


def run_portfolio_backtest(
    data_dict: Dict[str, pd.DataFrame],
    strategies: Dict[str, object],
    symbols: List[str],
    total_capital: float = 1_000_000,
    allocator: Optional[AllocationStrategy] = None,
    product_configs: Optional[Dict[str, dict]] = None,
    verbose: bool = True,
) -> PortfolioResult:
    """
    一键运行组合回测。

    每个品种独立运行回测（使用分配的独立资金），然后聚合结果。
    不处理品种间的交叉保证金或再平衡（后续扩展）。

    Args:
        data_dict: {symbol: DataFrame}
        strategies: {symbol: strategy_instance}
        symbols: 品种列表（决定顺序）
        total_capital: 组合总资金
        allocator: 资金分配策略（默认等权）
        product_configs: 品种参数配置（同 PRODUCT_CONFIG 格式）
        verbose: 是否打印进度

    Returns:
        PortfolioResult
    """
    from src.portfolio.allocator import EqualWeightAllocator

    allocator = allocator or EqualWeightAllocator()
    product_configs = product_configs or {}

    # 分配资金
    allocations = allocator.allocate(symbols, total_capital, data_dict)

    if verbose:
        logger.info("=" * 50)
        logger.info("组合回测开始")
        logger.info(f"总资金: {total_capital:,.0f}")
        logger.info(f"分配策略: {allocator.__class__.__name__}")
        for s in symbols:
            logger.info(f"  {s}: {allocations.get(s, 0):,.0f}")
        logger.info("=" * 50)

    symbol_results = {}
    for symbol in symbols:
        data = data_dict.get(symbol)
        strategy = strategies.get(symbol)
        capital = allocations.get(symbol, 0)

        if data is None or strategy is None or capital <= 0:
            if verbose:
                logger.warning(f"  跳过 {symbol}: 数据={data is not None}, "
                               f"策略={strategy is not None}, 资金={capital:.0f}")
            continue

        config = product_configs.get(symbol, {})
        engine = FuturesBacktestEngine(
            initial_capital=capital,
            contract_multiplier=config.get("multiplier", 10),
            margin_rate=config.get("margin_rate", 0.10),
            commission_open=config.get("commission_open", 0.0001),
            commission_close=config.get("commission_close", 0.0001),
            commission_close_today=config.get("commission_close_today"),
            slippage=0.0001,
        )

        if verbose:
            logger.info(f"  回测 {symbol}: 资金={capital:,.0f}")
        result = engine.run(data, strategy, symbol)
        symbol_results[symbol] = result

    # 聚合
    portfolio = aggregate_results(symbol_results, total_capital)

    if verbose:
        logger.success(f"组合回测完成: "
                       f"收益率={portfolio.total_return:.2%}, "
                       f"夏普={portfolio.sharpe_ratio:.2f}, "
                       f"最大回撤={portfolio.max_drawdown:.2%}")
        print()
        print(f"{'品种':<8} {'收益率':>10} {'夏普':>8} {'最大回撤':>10} {'胜率':>8} {'交易':>6}")
        print("-" * 55)
        for s, r in portfolio.by_symbol.items():
            print(f"{s:<8} {r.total_return:>10.2%} {r.sharpe_ratio:>8.2f} "
                  f"{r.max_drawdown:>10.2%} {r.win_rate:>8.2%} {r.total_trades:>6}")
        print("-" * 55)
        print(f"{'组合':<8} {portfolio.total_return:>10.2%} {portfolio.sharpe_ratio:>8.2f} "
              f"{portfolio.max_drawdown:>10.2%} {portfolio.win_rate:>8.2%} "
              f"{portfolio.total_trades:>6}")

    return portfolio
