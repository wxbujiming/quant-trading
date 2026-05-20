"""
策略自动筛选系统

多品种 × 多策略 × 多参数自动遍历 → TopN 榜单 + 参数稳定性分析。

功能:
  1. 遍历多个品种、多种策略、多个参数组合
  2. 输出全局 TopN 榜单 + 按品种/策略汇总
  3. 参数稳定性分析（灵敏度测试）
  4. 结果持久化到 JSON

用法:
    python scripts/strategy_screener.py                          # 全量筛选
    python scripts/strategy_screener.py --symbols RB,CU          # 指定品种
    python scripts/strategy_screener.py --strategies DualMaCross  # 指定策略
    python scripts/strategy_screener.py --sensitivity            # 启稳定性分析
    python scripts/strategy_screener.py --top-n 30               # 自定义 TopN
    python scripts/strategy_screener.py --report                 # 查看历史结果
"""
import sys
import json
import time
import itertools
import argparse
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Type

# 修复 Windows 终端中文编码
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
from loguru import logger

from src.core.logger import setup_logger
from src.data.futures_collector import FuturesDataCollector
from src.backtest.futures_engine import FuturesBacktestEngine


# ══════════════════════════════════════════════
#  配置区
# ══════════════════════════════════════════════

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

DEFAULT_SYMBOLS = list(PRODUCT_CONFIG.keys())
DEFAULT_CAPITAL = 1_000_000
DEFAULT_START_DATE = "2020-01-01"
RESULTS_FILE = Path("./data/screener_results.json")


# ── 策略与参数网格定义 ──

# DualMaCrossStrategy 参数网格
GRID_DUAL_MA = {
    "fast_period": [5, 10, 15, 20],
    "slow_period": [20, 30, 40, 60],
    "atr_multiplier": [1.5, 2.0, 2.5, 3.0],
}

# SimpleTrendStrategy 参数网格
GRID_SIMPLE_TREND = {
    "channel_period": [10, 20, 30, 40],
    "atr_period": [7, 14, 21],
    "atr_multiplier": [1.5, 2.0, 2.5],
}

# WeeklyFilteredMaStrategy 参数网格（增加周线参数）
GRID_WEEKLY_MA = {
    "fast_period": [5, 10, 15],
    "slow_period": [20, 30, 40],
    "atr_multiplier": [1.5, 2.0, 2.5],
    "weekly_sma_fast": [10, 20],
    "weekly_sma_slow": [30, 40],
}

# TripleTimeframeStrategy 参数网格
GRID_TRIPLE_TF = {
    "atr_multiplier": [1.5, 2.0, 2.5],
    "daily_sma_period": [15, 20, 25],
    "rsi_period": [10, 14, 20],
}

# 策略注册表：name -> (class, param_grid, display_name)
def _get_strategy_registry() -> dict:
    """延迟导入避免启动时循环依赖"""
    from src.strategy.futures_strategy import DualMaCrossStrategy, SimpleTrendStrategy
    from src.strategy.mtf_strategies import WeeklyFilteredMaStrategy, TripleTimeframeStrategy

    return {
        "DualMaCross": (DualMaCrossStrategy, GRID_DUAL_MA, "双均线CTA"),
        "SimpleTrend": (SimpleTrendStrategy, GRID_SIMPLE_TREND, "趋势通道"),
        "WeeklyFilteredMa": (WeeklyFilteredMaStrategy, GRID_WEEKLY_MA, "周线过滤+均线"),
        "TripleTimeframe": (TripleTimeframeStrategy, GRID_TRIPLE_TF, "三时间框架"),
    }


@dataclass
class ScreenerResult:
    """筛选单条结果"""
    symbol: str
    strategy: str          # 内部名称
    strategy_label: str    # 显示名称
    params: dict
    total_return: float
    annual_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    total_trades: int
    score: float


# ══════════════════════════════════════════════
#  核心函数
# ══════════════════════════════════════════════

def compute_score(result) -> float:
    """综合评分（同 optimize.py）"""
    # 无交易的结果直接给最低分
    if result.total_trades == 0:
        return -999

    score = 0.0
    if result.sharpe_ratio > 0:
        score += result.sharpe_ratio * 3
    if result.total_return > 0:
        score += result.total_return * 2
    score -= abs(result.max_drawdown) * 2
    score += result.win_rate * 0.5
    if result.profit_factor > 1 and np.isfinite(result.profit_factor):
        score += min(result.profit_factor, 5) * 0.5
    return score


def load_data(symbol: str, start_date: str = DEFAULT_START_DATE,
              end_date: Optional[str] = None) -> pd.DataFrame:
    """加载品种连续合约数据"""
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
                 config: dict) -> Optional[object]:
    """运行单次回测（复用 optimize.py 模式）"""
    try:
        engine = FuturesBacktestEngine(
            initial_capital=DEFAULT_CAPITAL,
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
        logger.debug(f"回测失败 {params}: {e}")
        return None


def run_screener(
    symbols: List[str] = DEFAULT_SYMBOLS,
    strategy_names: Optional[List[str]] = None,
    start_date: str = DEFAULT_START_DATE,
    end_date: Optional[str] = None,
    top_n: int = 20,
    verbose: bool = True,
) -> List[ScreenerResult]:
    """
    运行策略筛选：遍历 symbol × strategy × param_grid。

    Args:
        symbols: 品种代码列表
        strategy_names: 策略名称列表（None=全部）
        start_date: 回测起始日期
        end_date: 回测截止日期
        top_n: TopN 显示数量
        verbose: 是否打印进度

    Returns:
        按评分降序排列的结果列表
    """
    registry = _get_strategy_registry()
    if strategy_names is None:
        strategy_names = list(registry.keys())

    all_results: List[ScreenerResult] = []
    total_combos = 0
    total_start = time.time()

    # 预加载所有品种数据
    data_cache: Dict[str, pd.DataFrame] = {}
    for sym in symbols:
        try:
            df = load_data(sym, start_date, end_date)
            if not df.empty:
                data_cache[sym] = df
                if verbose:
                    logger.info(f"[{sym}] 数据: {len(df)} 条, "
                                f"{df.index[0].date()} ~ {df.index[-1].date()}")
        except Exception as e:
            logger.warning(f"[{sym}] 数据加载失败: {e}")

    if not data_cache:
        logger.error("没有可用的品种数据")
        return []

    # 计算总组合数
    for sn in strategy_names:
        if sn not in registry:
            logger.warning(f"未知策略: {sn}, 跳过")
            continue
        _, grid, _ = registry[sn]
        total_combos += len(data_cache) * len(list(itertools.product(*grid.values())))

    if verbose:
        logger.info("=" * 60)
        logger.info(f"策略筛选开始")
        logger.info(f"  品种: {', '.join(data_cache.keys())}")
        logger.info(f"  策略: {', '.join(strategy_names)}")
        logger.info(f"  总组合数: {total_combos}")
        logger.info(f"  数据范围: {start_date} ~ {end_date or '至今'}")
        logger.info("=" * 60)

    done = 0
    for sym, df in data_cache.items():
        config = PRODUCT_CONFIG.get(sym, {})
        for sn in strategy_names:
            if sn not in registry:
                continue
            strategy_cls, param_grid, label = registry[sn]
            keys = list(param_grid.keys())
            values = list(param_grid.values())
            combinations = list(itertools.product(*values))

            for combo in combinations:
                params = dict(zip(keys, combo))
                result = run_backtest(df, strategy_cls, params, config)

                if result:
                    score = compute_score(result)
                    all_results.append(ScreenerResult(
                        symbol=sym,
                        strategy=sn,
                        strategy_label=label,
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

                done += 1
                if verbose and done % 50 == 0:
                    elapsed = time.time() - total_start
                    rate = done / elapsed if elapsed > 0 else 0
                    eta = (total_combos - done) / rate if rate > 0 else 0
                    logger.info(f"  进度: [{done}/{total_combos}] "
                                f"耗时: {elapsed:.0f}s, {eta:.0f}s 剩余")

    # 排序
    all_results.sort(key=lambda r: r.score, reverse=True)

    total_elapsed = time.time() - total_start
    if verbose:
        positive = sum(1 for r in all_results if r.total_return > 0)
        logger.success(f"筛选完成: {len(all_results)} 个有效结果 "
                       f"(正向 {positive}/{len(all_results)}), "
                       f"耗时 {total_elapsed:.0f}s")

    return all_results


# ══════════════════════════════════════════════
#  输出
# ══════════════════════════════════════════════

def print_ranking(results: List[ScreenerResult], top_n: int = 20):
    """打印 TopN 榜单 + 品种/策略汇总"""
    if not results:
        print("无有效结果")
        return

    # ── TopN 榜单 ──
    print(f"\n{'=' * 120}")
    print(f"  策略筛选 TopN 榜单 (综评 Top {min(top_n, len(results))})")
    print(f"{'=' * 120}")

    header = (f"  {'排名':<4} {'品种':<5} {'策略':<14} {'综评':>7} "
              f"{'收益率':>8} {'年化':>8} {'夏普':>7} {'回撤':>7} "
              f"{'胜率':>6} {'盈亏比':>7} {'交易':>5}  {'参数'}")
    print(header)
    print(f"  {'-' * 116}")

    for i, r in enumerate(results[:top_n], 1):
        param_str = " ".join(f"{k}={v}" for k, v in r.params.items())
        # 截断过长的参数字符串
        if len(param_str) > 35:
            param_str = param_str[:32] + "..."
        print(f"  {i:<4} {r.symbol:<5} {r.strategy_label:<14} "
              f"{r.score:>7.2f} "
              f"{r.total_return:>8.2%} {r.annual_return:>8.2%} "
              f"{r.sharpe_ratio:>7.2f} {r.max_drawdown:>7.2%} "
              f"{r.win_rate:>6.2%} {r.profit_factor:>7.2f} "
              f"{r.total_trades:>5}  {param_str}")
    print(f"{'=' * 120}")

    # ── 按品种汇总 ──
    print(f"\n{'=' * 70}")
    print(f"  按品种汇总 (各品种最佳策略)")
    print(f"{'=' * 70}")
    print(f"  {'品种':<5} {'最佳策略':<14} {'综评':>7} {'收益率':>8} "
          f"{'夏普':>7} {'回撤':>7} {'交易':>5}")
    print(f"  {'-' * 66}")
    for sym in sorted(set(r.symbol for r in results)):
        sym_results = [r for r in results if r.symbol == sym]
        best = max(sym_results, key=lambda r: r.score)
        print(f"  {sym:<5} {best.strategy_label:<14} {best.score:>7.2f} "
              f"{best.total_return:>8.2%} {best.sharpe_ratio:>7.2f} "
              f"{best.max_drawdown:>7.2%} {best.total_trades:>5}")

    # ── 按策略汇总 ──
    print(f"\n{'=' * 70}")
    print(f"  按策略汇总 (各策略最佳品种)")
    print(f"{'=' * 70}")
    print(f"  {'策略':<14} {'最佳品种':<5} {'综评':>7} {'收益率':>8} "
          f"{'夏普':>7} {'回撤':>7} {'交易':>5}")
    print(f"  {'-' * 66}")
    for strat in sorted(set(r.strategy_label for r in results)):
        strat_results = [r for r in results if r.strategy_label == strat]
        best = max(strat_results, key=lambda r: r.score)
        print(f"  {strat:<14} {best.symbol:<5} {best.score:>7.2f} "
              f"{best.total_return:>8.2%} {best.sharpe_ratio:>7.2f} "
              f"{best.max_drawdown:>7.2%} {best.total_trades:>5}")

    print()


# ══════════════════════════════════════════════
#  参数稳定性分析
# ══════════════════════════════════════════════

@dataclass
class StabilityResult:
    """单条稳定性分析结果"""
    rank: int
    symbol: str
    strategy_label: str
    base_params: dict
    base_score: float
    base_return: float
    base_sharpe: float
    return_range: Tuple[float, float]
    sharpe_range: Tuple[float, float]
    return_volatility: float   # 收益率波动 (标准差)
    sharpe_volatility: float   # 夏普波动
    rating: str                # 高/中/低


def sensitivity_analysis(results: List[ScreenerResult], top_n: int = 5) -> List[StabilityResult]:
    """
    对 TopN 候选进行参数稳定性分析。

    对每个参数分别微调 ±1 档（相邻值），
    记录收益率和夏普的变化范围。
    """
    data_cache: Dict[str, pd.DataFrame] = {}

    def _get_data(sym: str) -> Optional[pd.DataFrame]:
        if sym not in data_cache:
            try:
                data_cache[sym] = load_data(sym)
            except Exception as e:
                logger.warning(f"  数据加载失败 {sym}: {e}")
                return None
        return data_cache[sym]

    def _find_neighbors(grid: dict, param_name: str, current_val) -> List:
        """找参数的相邻值"""
        values = sorted(grid.get(param_name, []))
        if current_val not in values:
            # 不在网格中，推断相邻
            candidates = sorted(set(values + [current_val]))
            idx = candidates.index(current_val)
            neighbors = []
            if idx > 0:
                neighbors.append(candidates[idx - 1])
            if idx < len(candidates) - 1:
                neighbors.append(candidates[idx + 1])
            return neighbors
        idx = values.index(current_val)
        neighbors = []
        if idx > 0:
            neighbors.append(values[idx - 1])
        if idx < len(values) - 1:
            neighbors.append(values[idx + 1])
        return neighbors

    registry = _get_strategy_registry()
    stability_results = []

    logger.info("=" * 60)
    logger.info(f"参数稳定性分析开始 (Top {top_n})")
    logger.info("=" * 60)

    for rank, r in enumerate(results[:top_n], 1):
        df = _get_data(r.symbol)
        if df is None:
            continue

        config = PRODUCT_CONFIG.get(r.symbol, {})
        strategy_cls, param_grid, label = registry.get(r.strategy, (None, None, None))
        if strategy_cls is None:
            continue

        all_returns = [r.total_return]
        all_sharpes = [r.sharpe_ratio]
        variations = []

        # 对每个参数逐个微调
        for param_name in r.params:
            neighbors = _find_neighbors(param_grid, param_name, r.params[param_name])
            for nv in neighbors:
                test_params = dict(r.params)
                test_params[param_name] = nv
                test_result = run_backtest(df, strategy_cls, test_params, config)
                if test_result:
                    all_returns.append(test_result.total_return)
                    all_sharpes.append(test_result.sharpe_ratio)
                    variations.append({
                        "param": param_name,
                        "base_value": r.params[param_name],
                        "test_value": nv,
                        "return": test_result.total_return,
                        "sharpe": test_result.sharpe_ratio,
                    })

        if len(all_returns) < 2:
            continue

        ret_min, ret_max = min(all_returns), max(all_returns)
        sharpe_min, sharpe_max = min(all_sharpes), max(all_sharpes)
        ret_vol = np.std(all_returns)
        sharpe_vol = np.std(all_sharpes)

        # 稳定性评级
        ret_spread = ret_max - ret_min
        if ret_spread < 0.05:
            rating = "高"
        elif ret_spread < 0.10:
            rating = "中"
        else:
            rating = "低"

        stability_results.append(StabilityResult(
            rank=rank,
            symbol=r.symbol,
            strategy_label=r.strategy_label,
            base_params=r.params,
            base_score=r.score,
            base_return=r.total_return,
            base_sharpe=r.sharpe_ratio,
            return_range=(ret_min, ret_max),
            sharpe_range=(sharpe_min, sharpe_max),
            return_volatility=ret_vol,
            sharpe_volatility=sharpe_vol,
            rating=rating,
        ))

        logger.info(f"  #{rank} {r.symbol}/{r.strategy_label}: "
                    f"收益=[{ret_min:.2%}~{ret_max:.2%}], "
                    f"夏普=[{sharpe_min:.2f}~{sharpe_max:.2f}], "
                    f"稳定性={rating}")

    # 打印表格
    if stability_results:
        print(f"\n{'=' * 100}")
        print(f"  参数稳定性分析 (Top {len(stability_results)})")
        print(f"{'=' * 100}")
        print(f"  {'排名':<4} {'品种':<6} {'策略':<14} "
              f"{'收益范围':<22} {'夏普范围':<20} {'稳定性':<6}")
        print(f"  {'-' * 96}")
        for sr in stability_results:
            ret_str = f"{sr.return_range[0]:.2%}~{sr.return_range[1]:.2%}"
            sharpe_str = f"{sr.sharpe_range[0]:.2f}~{sr.sharpe_range[1]:.2f}"
            print(f"  {sr.rank:<4} {sr.symbol:<6} {sr.strategy_label:<14} "
                  f"{ret_str:<22} {sharpe_str:<20} {sr.rating:<6}")
        print(f"{'=' * 100}")

    return stability_results


# ══════════════════════════════════════════════
#  持久化
# ══════════════════════════════════════════════

def save_screener_results(
    results: List[ScreenerResult],
    symbols: List[str],
    strategy_names: List[str],
    start_date: str,
    stability: Optional[List[StabilityResult]] = None,
):
    """保存筛选结果到 JSON"""
    top20 = results[:20]
    data = []
    for r in top20:
        data.append({
            "symbol": r.symbol,
            "strategy": r.strategy,
            "strategy_label": r.strategy_label,
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

    stability_data = None
    if stability:
        stability_data = []
        for s in stability:
            stability_data.append({
                "rank": s.rank,
                "symbol": s.symbol,
                "strategy": s.strategy_label,
                "base_params": s.base_params,
                "base_score": s.base_score,
                "return_range": list(s.return_range),
                "sharpe_range": list(s.sharpe_range),
                "return_volatility": s.return_volatility,
                "rating": s.rating,
            })

    record = {
        "timestamp": datetime.now().isoformat(),
        "config": {
            "symbols": symbols,
            "strategies": strategy_names,
            "start_date": start_date,
        },
        "results_count": len(results),
        "results": data,
        "stability": stability_data,
    }

    if RESULTS_FILE.exists():
        try:
            existing = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            existing = []
        existing.append(record)
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
    """显示历史筛选报告"""
    if not RESULTS_FILE.exists():
        print("暂无历史筛选记录")
        return

    try:
        records = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"读取结果失败: {e}")
        return

    if not records:
        print("暂无历史筛选记录")
        return

    print(f"\n{'=' * 90}")
    print(f"  历史筛选结果 ({len(records)} 条)")
    print(f"{'=' * 90}")
    for i, rec in enumerate(reversed(records[-20:]), 1):
        ts = rec.get("timestamp", "?")[:19]
        cfg = rec.get("config", {})
        syms = ",".join(cfg.get("symbols", []))
        strats = ",".join(cfg.get("strategies", []))
        count = rec.get("results_count", 0)
        best = rec["results"][0] if rec.get("results") else {}
        if best:
            print(f"  {i:<3} [{ts}] 品种={syms} 策略={strats} "
                  f"有效={count}: "
                  f"#{best['symbol']}/{best['strategy_label']} "
                  f"score={best['score']:.1f} "
                  f"收益={best['total_return']:.2%} "
                  f"夏普={best['sharpe_ratio']:.2f}")
    print(f"{'=' * 90}")


# ══════════════════════════════════════════════
#  主入口
# ══════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="策略自动筛选系统")
    parser.add_argument("--symbols", type=str, default=None,
                        help="品种列表，逗号分隔 (默认全部)")
    parser.add_argument("--strategies", type=str, default=None,
                        help="策略列表，逗号分隔 (默认全部)")
    parser.add_argument("--start-date", type=str, default=DEFAULT_START_DATE,
                        help="回测起始日期")
    parser.add_argument("--end-date", type=str, default=None,
                        help="回测截止日期")
    parser.add_argument("--top-n", type=int, default=20,
                        help="TopN 显示数量")
    parser.add_argument("--sensitivity", action="store_true",
                        help="启参数稳定性分析")
    parser.add_argument("--no-save", action="store_true",
                        help="不保存结果到 JSON")
    parser.add_argument("--report", action="store_true",
                        help="查看历史筛选结果")
    args = parser.parse_args()

    setup_logger("INFO", "logs/screener.log")

    if args.report:
        show_report()
        return

    # 解析品种列表
    if args.symbols and args.symbols.lower() != "all":
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
        symbols = [s for s in symbols if s in PRODUCT_CONFIG]
        if not symbols:
            logger.error("没有有效的品种代码")
            return
    else:
        symbols = DEFAULT_SYMBOLS

    # 解析策略列表
    registry = _get_strategy_registry()
    if args.strategies and args.strategies.lower() != "all":
        strategy_names = [s.strip() for s in args.strategies.split(",")]
        strategy_names = [s for s in strategy_names if s in registry]
        if not strategy_names:
            logger.error(f"没有有效的策略名称。可用: {list(registry.keys())}")
            return
    else:
        strategy_names = list(registry.keys())

    # 运行筛选
    results = run_screener(
        symbols=symbols,
        strategy_names=strategy_names,
        start_date=args.start_date,
        end_date=args.end_date,
        top_n=args.top_n,
    )

    if not results:
        logger.warning("筛选无有效结果")
        return

    # 打印 TopN 榜单
    print_ranking(results, top_n=args.top_n)

    # 稳定性分析
    stability = None
    if args.sensitivity:
        stability = sensitivity_analysis(results, top_n=min(5, len(results)))

    # 保存
    if not args.no_save:
        save_screener_results(results, symbols, strategy_names,
                              args.start_date, stability)

    logger.success("筛选完成")


if __name__ == "__main__":
    main()
