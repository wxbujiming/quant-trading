"""
策略参数优化器

支持:
  1. 网格搜索 (Grid Search) — 暴力枚举参数组合
  2. Walk-forward 分析 — 滚动窗口验证防过拟合

用法:
    python scripts/optimize.py --strategy DualMaCrossStrategy --param-grid '{"fast_period": [5,10,20], "slow_period": [20,30,40]}'
    python scripts/optimize.py --symbol RB --strategy DualMaCrossStrategy --grid
    python scripts/optimize.py --symbol RB --walk-forward --windows 4
    python scripts/optimize.py --report                          # 查看历史结果
"""
import sys
import json
import time
import argparse
import itertools
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
from loguru import logger

from src.core.logger import setup_logger
from src.data.futures_collector import FuturesDataCollector
from src.backtest.futures_engine import FuturesBacktestEngine


# ────────── 品种参数（复用 run_futures_backtest.py） ──────────

PRODUCT_CONFIG = {
    "RB": {"name": "螺纹钢", "multiplier": 10, "margin_rate": 0.10,
           "commission_open": 0.0001, "commission_close": 0.0001,
           "commission_close_today": 0.0, "tick_size": 1, "min_move_value": 10},
    "CU": {"name": "沪铜", "multiplier": 5, "margin_rate": 0.12,
           "commission_open": 0.00005, "commission_close": 0.00005,
           "commission_close_today": 0.0001, "tick_size": 10, "min_move_value": 50},
    "IF": {"name": "沪深300股指", "multiplier": 300, "margin_rate": 0.12,
           "commission_open": 0.000023, "commission_close": 0.000023,
           "commission_close_today": 0.00023, "tick_size": 0.2, "min_move_value": 60},
    "SC": {"name": "原油", "multiplier": 1000, "margin_rate": 0.15,
           "commission_open": 0.0001, "commission_close": 0.0001,
           "commission_close_today": 0.0, "tick_size": 0.1, "min_move_value": 100},
    "P": {"name": "棕榈油", "multiplier": 10, "margin_rate": 0.10,
          "commission_open": 0.0001, "commission_close": 0.0001,
          "commission_close_today": 0.0, "tick_size": 2, "min_move_value": 20},
}

# 默认参数搜索范围
DEFAULT_GRID_MA = {
    "fast_period": [5, 10, 15, 20],
    "slow_period": [20, 30, 40, 60],
    "atr_multiplier": [1.5, 2.0, 2.5, 3.0],
}

DEFAULT_GRID_TREND = {
    "channel_period": [10, 20, 30, 40],
    "atr_period": [7, 14, 21],
    "atr_multiplier": [1.5, 2.0, 2.5],
}


@dataclass
class OptimizeResult:
    """参数优化结果"""
    params: dict
    total_return: float
    annual_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    total_trades: int
    score: float  # 综合评分


def get_strategy_class(name: str):
    """策略工厂"""
    from src.strategy.futures_strategy import DualMaCrossStrategy, SimpleTrendStrategy
    mapping = {
        "DualMaCrossStrategy": DualMaCrossStrategy,
        "SimpleTrendStrategy": SimpleTrendStrategy,
        "双均线CTA": DualMaCrossStrategy,
        "趋势通道": SimpleTrendStrategy,
    }
    cls = mapping.get(name)
    if not cls:
        raise ValueError(f"未知策略: {name}")
    return cls


def load_data(symbol: str, start_date: str = "2020-01-01",
              end_date: str = None) -> pd.DataFrame:
    """加载品种数据"""
    collector = FuturesDataCollector()
    df = collector.get_continuous_daily(f"{symbol}0")
    if df.empty:
        raise ValueError(f"获取 {symbol} 数据失败")

    df["date"] = pd.to_datetime(df["date"])
    if start_date:
        df = df[df["date"] >= start_date]
    if end_date:
        df = df[df["date"] <= end_date]

    df = df.set_index("date")
    return df


def run_backtest(df: pd.DataFrame, strategy_cls, params: dict,
                 config: dict, capital: float = 1_000_000) -> Optional[object]:
    """运行单次回测"""
    try:
        engine = FuturesBacktestEngine(
            initial_capital=capital,
            contract_multiplier=config["multiplier"],
            margin_rate=config["margin_rate"],
            commission_open=config["commission_open"],
            commission_close=config["commission_close"],
            commission_close_today=config.get("commission_close_today"),
            slippage=0.0001,
        )
        strategy = strategy_cls(params=params)
        result = engine.run(df, strategy, config.get("name", ""))
        return result
    except Exception as e:
        logger.debug(f"回测失败 params={params}: {e}")
        return None


def compute_score(result) -> float:
    """综合评分（夏普 + 收益率 - 回撤/2 + 胜率/10）"""
    score = 0.0
    if result.sharpe_ratio > 0:
        score += result.sharpe_ratio * 3
    if result.total_return > 0:
        score += result.total_return * 2
    score -= abs(result.max_drawdown) * 2
    score += result.win_rate * 0.5
    if result.profit_factor > 1:
        score += min(result.profit_factor, 5) * 0.5
    return score


# ────────── 网格搜索 ──────────

def grid_search(symbol: str, strategy_name: str,
                param_grid: Dict[str, list],
                start_date: str = "2020-01-01", end_date: str = None,
                top_n: int = 10) -> List[OptimizeResult]:
    """
    网格搜索最优参数组合

    Args:
        symbol: 品种代码 (RB, CU, ...)
        strategy_name: 策略名称
        param_grid: 参数网格 {param_name: [values]}
        start_date: 回测起始日期
        end_date: 回测截止日期
        top_n: 显示前N个结果

    Returns:
        按评分降序排列的结果列表
    """
    config = PRODUCT_CONFIG.get(symbol)
    if not config:
        logger.error(f"未知品种: {symbol}")
        return []

    strategy_cls = get_strategy_class(strategy_name)
    df = load_data(symbol, start_date, end_date)

    # 生成所有参数组合
    keys = list(param_grid.keys())
    values = list(param_grid.values())
    combinations = list(itertools.product(*values))

    logger.info(f"网格搜索开始: {symbol} {strategy_name}")
    logger.info(f"  参数空间: {dict(zip(keys, [len(v) for v in values]))}")
    logger.info(f"  组合总数: {len(combinations)}")
    logger.info(f"  数据范围: {df.index[0].date()} ~ {df.index[-1].date()}")
    logger.info(f"  数据条数: {len(df)}")
    logger.info("=" * 50)

    results: List[OptimizeResult] = []
    start = time.time()

    for idx, combo in enumerate(combinations, 1):
        params = dict(zip(keys, combo))
        result = run_backtest(df, strategy_cls, params, config)

        if result:
            score = compute_score(result)
            results.append(OptimizeResult(
                params=params,
                total_return=result.total_return,
                annual_return=result.annual_return,
                sharpe_ratio=result.sharpe_ratio,
                max_drawdown=result.max_drawdown,
                win_rate=result.win_rate,
                profit_factor=result.profit_factor,
                total_trades=result.total_trades,
                score=score,
            ))

        if idx % 20 == 0 or idx == len(combinations):
            elapsed = time.time() - start
            rate = idx / elapsed if elapsed > 0 else 0
            logger.info(f"  进度: [{idx}/{len(combinations)}] "
                        f"耗时: {elapsed:.0f}s, 速率: {rate:.1f}次/s")

    # 按评分降序排列
    results.sort(key=lambda r: r.score, reverse=True)

    # 打印结果
    elapsed = time.time() - start
    logger.success(f"网格搜索完成: {len(results)} 个有效结果, 耗时 {elapsed:.0f}s")

    print(f"\n{'=' * 100}")
    print(f"  {symbol} {strategy_name} — 最优参数 Top{min(top_n, len(results))}")
    print(f"{'=' * 100}")
    header = f"  {'排名':<4} {'综合评分':>8} {'收益率':>8} {'年化':>8} {'夏普':>8} {'回撤':>8} {'胜率':>7} {'盈亏比':>8} {'交易':>5}  参数"
    print(header)
    print("  " + "-" * 96)
    for i, r in enumerate(results[:top_n], 1):
        param_str = " ".join(f"{k}={v}" for k, v in r.params.items())
        print(f"  {i:<4} {r.score:>8.2f} {r.total_return:>8.2%} {r.annual_return:>8.2%} "
              f"{r.sharpe_ratio:>8.2f} {r.max_drawdown:>8.2%} {r.win_rate:>7.2%} "
              f"{r.profit_factor:>8.2f} {r.total_trades:>5}  {param_str}")
    print(f"{'=' * 100}")

    return results


def run_grid_from_cli(args):
    """从 CLI 参数运行网格搜索"""
    param_grid = None
    if args.param_grid:
        param_grid = json.loads(args.param_grid)
    elif args.strategy == "DualMaCrossStrategy":
        param_grid = DEFAULT_GRID_MA
    elif args.strategy == "SimpleTrendStrategy":
        param_grid = DEFAULT_GRID_TREND

    if not param_grid:
        logger.error("请提供 --param-grid 或使用默认网格")
        return

    grid_search(args.symbol, args.strategy, param_grid,
                start_date=args.start_date, end_date=args.end_date)


# ────────── Walk-forward 分析 ──────────

@dataclass
class WfWindow:
    """Walk-forward 窗口"""
    train_start: str
    train_end: str
    test_start: str
    test_end: str


def build_walk_forward_windows(total_start: str, total_end: str,
                                window_years: float = 1.0,
                                step_years: float = 0.25) -> List[WfWindow]:
    """
    构建 Walk-forward 滚动窗口

    Args:
        total_start: 总起始日期
        total_end: 总截止日期
        window_years: 每个窗口的训练集长度（年）
        step_years: 滚动步长（年）

    Returns:
        窗口列表
    """
    first_start = pd.Timestamp(total_start)
    end_dt = pd.Timestamp(total_end)
    windows = []

    window_days = int(window_years * 252)
    step_days = int(step_years * 252)

    # 锚定法: 训练集始于总起始日期，末端逐步滚动
    train_end_dt = first_start + pd.Timedelta(days=window_days)

    while train_end_dt < end_dt:
        test_end_dt = min(train_end_dt + pd.Timedelta(days=step_days), end_dt)
        windows.append(WfWindow(
            train_start=first_start.strftime("%Y-%m-%d"),
            train_end=train_end_dt.strftime("%Y-%m-%d"),
            test_start=train_end_dt.strftime("%Y-%m-%d"),
            test_end=test_end_dt.strftime("%Y-%m-%d"),
        ))
        train_end_dt = test_end_dt

    return windows


def walk_forward(symbol: str, strategy_name: str,
                 param_grid: Dict[str, list],
                 start_date: str = "2018-01-01", end_date: str = None,
                 window_years: float = 1.0, step_years: float = 0.25):
    """
    Walk-forward 分析

    滚动窗口: 训练集寻优 → 测试集验证 → 汇总所有测试集结果

    Args:
        symbol: 品种代码
        strategy_name: 策略名称
        param_grid: 参数搜索空间
        start_date: 数据起始日期
        end_date: 数据截止日期
        window_years: 训练窗口大小（年）
        step_years: 滚动步长（年）
    """
    config = PRODUCT_CONFIG.get(symbol)
    if not config:
        logger.error(f"未知品种: {symbol}")
        return

    strategy_cls = get_strategy_class(strategy_name)
    df = load_data(symbol, start_date, end_date)
    windows = build_walk_forward_windows(
        df.index[0].strftime("%Y-%m-%d"),
        df.index[-1].strftime("%Y-%m-%d"),
        window_years, step_years,
    )

    if not windows:
        logger.error("数据不足以构建 walk-forward 窗口")
        return

    logger.info(f"Walk-forward 分析: {symbol} {strategy_name}")
    logger.info(f"  窗口数: {len(windows)}")
    logger.info(f"  参数组合: {len(list(itertools.product(*param_grid.values())))}")
    logger.info(f"  总数据: {len(df)} 条, "
                f"{df.index[0].date()} ~ {df.index[-1].date()}")
    logger.info("=" * 50)

    all_test_trades = 0
    all_test_returns = []

    for i, w in enumerate(windows, 1):
        # 训练集 = 寻参
        train_df = df.loc[w.train_start:w.train_end]
        test_df = df.loc[w.test_start:w.test_end]

        if len(train_df) < 50 or len(test_df) < 20:
            logger.warning(f"  窗口{i}: 数据不足，跳过")
            continue

        # 在训练集上网格搜索
        best_score = -999
        best_params = None
        best_result = None

        for combo in itertools.product(*param_grid.values()):
            params = dict(zip(param_grid.keys(), combo))
            result = run_backtest(train_df, strategy_cls, params, config)
            if result:
                score = compute_score(result)
                if score > best_score:
                    best_score = score
                    best_params = params
                    best_result = result

        # 在测试集上验证
        test_result = run_backtest(test_df, strategy_cls, best_params, config)

        train_ret = best_result.total_return if best_result else 0
        train_sharpe = best_result.sharpe_ratio if best_result else 0
        test_ret = test_result.total_return if test_result else 0
        test_sharpe = test_result.sharpe_ratio if test_result else 0

        print(f"  窗口{i}: "
              f"训练 {w.train_start}~{w.train_end} ({len(train_df)}条) "
              f"→ 测试 {w.test_start}~{w.test_end} ({len(test_df)}条)")
        print(f"    最优参数: {best_params}")
        print(f"    训练集: 收益率={train_ret:.2%} 夏普={train_sharpe:.2f}")
        print(f"    测试集: 收益率={test_ret:.2%} 夏普={test_sharpe:.2f}")

        if test_result:
            all_test_trades += test_result.total_trades
            all_test_returns.append(test_ret)

    # Walk-forward 汇总
    if all_test_returns:
        avg_return = np.mean(all_test_returns)
        positive_windows = sum(1 for r in all_test_returns if r > 0)
        print(f"\n{'=' * 50}")
        print(f"  Walk-forward 汇总")
        print(f"{'=' * 50}")
        print(f"  测试窗口数: {len(all_test_returns)}")
        print(f"  平均测试收益率: {avg_return:.2%}")
        print(f"  正向窗口: {positive_windows}/{len(all_test_returns)}")
        print(f"  总交易次数: {all_test_trades}")
        print(f"{'=' * 50}")


# ────────── 结果持久化与报表 ──────────

RESULTS_FILE = Path("./data/optimize_results.json")


def save_results(symbol: str, strategy: str, results: List[OptimizeResult]):
    """保存优化结果到 JSON"""
    data = []
    for r in results:
        data.append({
            "params": r.params,
            "total_return": r.total_return,
            "annual_return": r.annual_return,
            "sharpe_ratio": r.sharpe_ratio,
            "max_drawdown": r.max_drawdown,
            "win_rate": r.win_rate,
            "profit_factor": r.profit_factor,
            "total_trades": r.total_trades,
            "score": r.score,
        })

    record = {
        "timestamp": datetime.now().isoformat(),
        "symbol": symbol,
        "strategy": strategy,
        "results": data[:20],  # 只保存 Top20
    }

    if RESULTS_FILE.exists():
        try:
            existing = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            existing = []
        existing.append(record)
        # 只保留最近 50 条记录
        if len(existing) > 50:
            existing = existing[-50:]
    else:
        existing = [record]

    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_FILE.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(f"结果已保存: {RESULTS_FILE}")


def show_report():
    """显示历史优化报告"""
    if not RESULTS_FILE.exists():
        print("暂无历史优化记录")
        return

    try:
        records = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"读取结果失败: {e}")
        return

    if not records:
        print("暂无历史优化记录")
        return

    print(f"\n{'=' * 80}")
    print(f"  历史优化结果 ({len(records)} 条)")
    print(f"{'=' * 80}")
    for i, rec in enumerate(reversed(records[-20:]), 1):
        ts = rec.get("timestamp", "?")[:19]
        sym = rec.get("symbol", "?")
        strat = rec.get("strategy", "?")
        best = rec["results"][0] if rec.get("results") else None
        if best:
            print(f"  {i:<3} [{ts}] {sym}/{strat}: "
                  f"score={best['score']:.1f} 收益率={best['total_return']:.2%} "
                  f"夏普={best['sharpe_ratio']:.2f} 参数={best['params']}")
    print(f"{'=' * 80}")


# ────────── 主入口 ──────────

def main():
    parser = argparse.ArgumentParser(description="策略参数优化器")
    parser.add_argument("--symbol", type=str, default="RB", help="品种代码")
    parser.add_argument("--strategy", type=str, default="DualMaCrossStrategy",
                        help="策略名称")
    parser.add_argument("--param-grid", type=str, default=None,
                        help='参数网格JSON, 如 \'{"fast_period": [5,10]}\'')
    parser.add_argument("--grid", action="store_true", help="运行网格搜索")
    parser.add_argument("--walk-forward", action="store_true", help="运行 Walk-forward")
    parser.add_argument("--start-date", type=str, default="2020-01-01",
                        help="回测起始日期")
    parser.add_argument("--end-date", type=str, default=None,
                        help="回测截止日期")
    parser.add_argument("--top-n", type=int, default=10, help="显示前N个结果")
    parser.add_argument("--window-years", type=float, default=1.0,
                        help="Walk-forward 训练窗口（年）")
    parser.add_argument("--step-years", type=float, default=0.25,
                        help="Walk-forward 步长（年）")
    parser.add_argument("--report", action="store_true", help="查看历史结果")
    args = parser.parse_args()

    setup_logger("INFO", "logs/optimize.log")

    if args.report:
        show_report()
        return

    if args.walk_forward:
        param_grid = None
        if args.param_grid:
            param_grid = json.loads(args.param_grid)
        elif args.strategy == "DualMaCrossStrategy":
            param_grid = DEFAULT_GRID_MA
        elif args.strategy == "SimpleTrendStrategy":
            param_grid = DEFAULT_GRID_TREND
        if not param_grid:
            logger.error("请提供 --param-grid 或使用默认网格")
            return
        walk_forward(args.symbol, args.strategy, param_grid,
                     args.start_date, args.end_date,
                     args.window_years, args.step_years)
        return

    # 默认：网格搜索
    param_grid = None
    if args.param_grid:
        param_grid = json.loads(args.param_grid)
    elif args.strategy == "DualMaCrossStrategy":
        param_grid = DEFAULT_GRID_MA
    elif args.strategy == "SimpleTrendStrategy":
        param_grid = DEFAULT_GRID_TREND

    if not param_grid:
        logger.error("请指定 --param-grid 或使用默认网格")
        print("\n默认网格:")
        print(f"  DualMaCrossStrategy: {DEFAULT_GRID_MA}")
        print(f"  SimpleTrendStrategy:  {DEFAULT_GRID_TREND}")
        return

    results = grid_search(args.symbol, args.strategy, param_grid,
                          args.start_date, args.end_date, args.top_n)
    if results:
        save_results(args.symbol, args.strategy, results)


if __name__ == "__main__":
    main()
