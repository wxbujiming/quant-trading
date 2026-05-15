"""
回测脚本
用法: python scripts/run_backtest.py

功能:
  1. 采集/加载数据
  2. 对5个策略逐个回测
  3. 生成HTML可视化报告
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.logger import setup_logger
from src.core.config import get_config
from src.data.collector import DataCollector
from src.backtest.engine import BacktestEngine
from src.backtest.visualizer import (
    plot_equity_curve, plot_trade_signals, plot_strategy_comparison,
    plot_drawdown_heatmap, generate_report,
)
from src.strategy.trend_strategy import SmaCrossStrategy, MACDStrategy
from src.strategy.mean_reversion_strategy import BollingerBandsStrategy, RSIStrategy, RSI2Strategy
from loguru import logger


def run_all_strategies():
    """运行所有策略回测并生成可视化报告"""
    setup_logger()
    config = get_config()

    print("\n" + "=" * 60)
    print("           策略回测工具 (带可视化)")
    print("=" * 60)

    # 1. 加载数据
    print("\n[1/3] 加载数据...")
    collector = DataCollector(raw_dir=config.data.raw_dir)
    symbol = "000001"
    df = collector.load_from_parquet(symbol)

    if df.empty:
        print(f"   本地无数据，正在采集 {symbol}...")
        df = collector.get_stock_history(symbol, start_date="20200101", end_date="20240528")
        if df.empty:
            print("   数据采集失败，退出")
            return

    data = df.set_index("date")

    # 标准化列名为英文
    col_map = {
        "开盘": "open", "收盘": "close", "最高": "high", "最低": "low",
        "成交量": "volume", "成交额": "amount", "振幅": "amplitude",
        "涨跌幅": "pct_change", "涨跌额": "change", "换手率": "turnover",
    }
    data.rename(columns={k: v for k, v in col_map.items() if k in data.columns}, inplace=True)

    print(f"   数据: {len(data)} 条 ({data.index[0].date()} ~ {data.index[-1].date()})")

    # 2. 定义所有策略
    all_strategies = [
        ("双均线(10,30)", SmaCrossStrategy, {"fast_period": 10, "slow_period": 30}),
        ("MACD(12,26,9)", MACDStrategy, {}),
        ("布林带(20,2)", BollingerBandsStrategy, {"period": 20, "std_dev": 2.0}),
        ("RSI(14,30/70)", RSIStrategy, {"period": 14, "oversold": 30, "overbought": 70}),
        ("RSI2短线反转", RSI2Strategy, {"period": 2, "oversold": 10, "overbought": 90}),
    ]

    # 3. 逐个回测
    print("\n[2/3] 运行回测...")
    engine = BacktestEngine(
        initial_cash=config.backtest.initial_cash,
        commission=config.backtest.commission,
        slippage=config.backtest.slippage,
    )

    results = []
    for name, strategy_cls, params in all_strategies:
        strategy = strategy_cls(params=params)
        result = engine.run(data.copy(), strategy, symbol=symbol)
        results.append((name, result))

    # 4. 打印结果对比
    print("\n[3/3] 生成可视化报告...")
    print("\n" + "=" * 70)
    print(f"{'策略':<20} {'总收益率':>10} {'年化':>10} {'最大回撤':>10} {'夏普':>8} {'胜率':>8} {'交易':>6}")
    print("-" * 70)
    for name, result in results:
        print(f"{name:<20} {result.total_return:>10.2%} {result.annual_return:>10.2%} "
              f"{result.max_drawdown:>10.2%} {result.sharpe_ratio:>8.2f} "
              f"{result.win_rate:>8.2%} {result.total_trades:>6}")
    print("=" * 70)

    # 5. 生成图表
    out_dir = Path("./reports")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 5a. 多策略资金曲线对比
    fig_compare = plot_strategy_comparison(results, title="多策略资金曲线对比")
    fig_compare.write_html(str(out_dir / "strategy_comparison.html"))
    logger.success(f"策略对比图: reports/strategy_comparison.html")

    # 5b. 每个策略生成独立报告
    for name, result in results:
        indicators = _get_indicators(data, name)
        # 清理策略名中的非法文件名字符
        safe_name = name.replace("/", "_").replace("\\", "_").replace(":", "_").replace("*", "_")
        generate_report(
            result, data.reset_index(),
            strategy_name=safe_name,
            indicators=indicators,
            output_dir=str(out_dir),
        )

    # 5c. 打印报告文件列表
    print("\n📁 生成的文件:")
    for f in sorted(out_dir.glob("*.html")):
        print(f"   {f}")

    print("\n✅ 回测完成！")


def _get_indicators(data, strategy_name: str):
    """计算策略相关指标线"""
    close = data["close"]

    if "均线" in strategy_name:
        fast = int(strategy_name.split("(")[1].split(",")[0])
        slow = int(strategy_name.split(",")[1].rstrip(")"))
        return [
            {"name": f"MA{fast}", "values": close.rolling(fast).mean(), "color": "#FF9800"},
            {"name": f"MA{slow}", "values": close.rolling(slow).mean(), "color": "#F44336"},
        ]

    if "MACD" in strategy_name:
        ema_fast = close.ewm(span=12).mean()
        ema_slow = close.ewm(span=26).mean()
        macd = ema_fast - ema_slow
        signal = macd.ewm(span=9).mean()
        return [
            {"name": "MACD", "values": macd, "color": "#2196F3"},
            {"name": "Signal", "values": signal, "color": "#FF9800"},
        ]

    if "布林带" in strategy_name:
        period = 20
        ma = close.rolling(period).mean()
        std = close.rolling(period).std()
        return [
            {"name": "中轨", "values": ma, "color": "#4CAF50"},
            {"name": "上轨", "values": ma + 2 * std, "color": "#F44336"},
            {"name": "下轨", "values": ma - 2 * std, "color": "#F44336"},
        ]

    if "RSI" in strategy_name:
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        period = 2 if "2" in strategy_name else 14
        avg_gain = gain.rolling(period).mean()
        avg_loss = loss.rolling(period).mean().replace(0, 1e-10)
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return [{"name": f"RSI({period})", "values": rsi, "color": "#9C27B0"}]

    return []


if __name__ == "__main__":
    run_all_strategies()
