"""
AI 策略回测脚本。

用法:
    python scripts/run_ai_backtest.py --symbol RB --model-path data/models/RB_xgb_20260520.joblib
    python scripts/run_ai_backtest.py --symbol RB --model-path ... --threshold 0.7
    python scripts/run_ai_backtest.py --list-models   # 查看可用的模型
"""
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Windows GBK 控制台兼容
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from loguru import logger
import pandas as pd

from src.core.logger import setup_logger
from src.data.futures_collector import FuturesDataCollector
from src.backtest.futures_engine import FuturesBacktestEngine
from src.strategy.ai_strategy import MLTradingStrategy
from src.ai.models import ModelManager

# 品种参数（复用 optimize.py 的配置）
PRODUCT_CONFIG = {
    "RB": {"name": "螺纹钢", "multiplier": 10, "margin_rate": 0.10,
           "commission_open": 0.0001, "commission_close": 0.0001,
           "commission_close_today": 0.0, "tick_size": 1},
    "CU": {"name": "沪铜", "multiplier": 5, "margin_rate": 0.12,
           "commission_open": 0.00005, "commission_close": 0.00005,
           "commission_close_today": 0.0001, "tick_size": 10},
    "IF": {"name": "沪深300股指", "multiplier": 300, "margin_rate": 0.12,
           "commission_open": 0.000023, "commission_close": 0.000023,
           "commission_close_today": 0.00023, "tick_size": 0.2},
    "SC": {"name": "原油", "multiplier": 1000, "margin_rate": 0.15,
           "commission_open": 0.0001, "commission_close": 0.0001,
           "commission_close_today": 0.0, "tick_size": 0.1},
    "P": {"name": "棕榈油", "multiplier": 10, "margin_rate": 0.10,
          "commission_open": 0.0001, "commission_close": 0.0001,
          "commission_close_today": 0.0, "tick_size": 2},
}


def load_data(symbol: str, start_date: str = "2020-01-01",
              end_date: str = None) -> pd.DataFrame:
    """加载连续合约日线数据。"""
    collector = FuturesDataCollector()
    df = collector.get_continuous_daily(f"{symbol}0")
    if df.empty:
        raise ValueError(f"获取 {symbol} 数据失败")

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")

    if start_date:
        df = df[df["date"] >= start_date]
    if end_date:
        df = df[df["date"] <= end_date]

    df = df.set_index("date")
    return df


def print_backtest_result(result, strategy_name: str):
    """打印回测结果。"""
    print(f"\n{'=' * 50}")
    print(f"  {strategy_name}")
    print(f"{'=' * 50}")
    print(f"  初始资金:    ¥{result.initial_capital:>12,.2f}")
    print(f"  最终资金:    ¥{result.final_capital:>12,.2f}")
    print(f"  总收益率:    {result.total_return:>12.2%}")
    print(f"  年化收益:    {result.annual_return:>12.2%}")
    print(f"  夏普比率:    {result.sharpe_ratio:>12.2f}")
    print(f"  最大回撤:    {result.max_drawdown:>12.2%}")
    print(f"  总交易:      {result.total_trades:>12}")
    print(f"  胜率:        {result.win_rate:>12.2%}")
    print(f"  盈亏比:      {result.profit_factor:>12.2f}")
    print(f"  总手续费:    ¥{result.total_commission:>12,.2f}")
    print(f"{'=' * 50}")


def main():
    parser = argparse.ArgumentParser(description="AI 策略回测")
    parser.add_argument("--symbol", type=str, default="RB", help="品种代码")
    parser.add_argument("--model-path", type=str, default=None,
                        help="模型 .joblib 文件路径")
    parser.add_argument("--threshold", type=float, default=0.6,
                        help="信号概率阈值")
    parser.add_argument("--capital", type=float, default=1_000_000,
                        help="初始资金")
    parser.add_argument("--start", type=str, default="2022-01-01",
                        help="回测起始日期")
    parser.add_argument("--end", type=str, default=None, help="回测截止日期")
    parser.add_argument("--model-dir", type=str, default="./models",
                        help="模型目录（配合 --list-models 使用）")
    parser.add_argument("--list-models", action="store_true",
                        help="列出可用模型")
    args = parser.parse_args()

    setup_logger("INFO", "logs/ai_backtest.log")

    if args.list_models:
        mgr = ModelManager(model_dir=args.model_dir)
        models = mgr.list_models()
        if not models:
            print("暂无可用模型，请先运行 train_model.py")
            return
        print(f"\n可用模型:")
        for m in models:
            score = f"{m['score']:.4f}" if m['score'] else "?"
            print(f"  {m['filename']}  [{m['symbol']}]  score={score}")
        return

    if not args.model_path:
        print("请指定 --model-path 或使用 --list-models 查看可用模型")
        return

    # 加载数据
    logger.info(f"加载 {args.symbol} 数据...")
    df = load_data(args.symbol, args.start, args.end)
    logger.info(f"数据量: {len(df)} 条")

    # 品种配置
    config = PRODUCT_CONFIG.get(args.symbol)
    if not config:
        logger.error(f"未知品种: {args.symbol}")
        return

    # 创建引擎
    engine = FuturesBacktestEngine(
        initial_capital=args.capital,
        contract_multiplier=config["multiplier"],
        margin_rate=config["margin_rate"],
        commission_open=config["commission_open"],
        commission_close=config["commission_close"],
        commission_close_today=config.get("commission_close_today"),
        slippage=0.0001,
    )

    # 策略
    strategy = MLTradingStrategy(params={
        "model_path": args.model_path,
        "score_threshold": args.threshold,
        "lookback": 60,
    })

    # 运行
    logger.info(f"开始回测: {args.symbol} / {args.model_path}")
    result = engine.run(df, strategy, config.get("name", args.symbol))
    print_backtest_result(result, f"AI 策略 ({args.symbol})")


if __name__ == "__main__":
    main()
