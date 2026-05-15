"""
回测脚本
用法: python scripts/run_backtest.py
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.logger import setup_logger
from src.core.config import get_config
from src.data.collector import DataCollector
from src.backtest.engine import BacktestEngine
from src.strategy.trend_strategy import SmaCrossStrategy, MACDStrategy
from loguru import logger


def run_backtest_example():
    """运行回测示例"""
    # 初始化
    setup_logger()
    config = get_config()
    
    print("\n" + "=" * 60)
    print("           策略回测工具")
    print("=" * 60)
    
    # 1. 加载数据
    print("\n[1/3] 加载数据...")
    collector = DataCollector(raw_dir=config.data.raw_dir)
    
    # 尝试加载已采集的数据，如果不存在则采集
    symbol = "000001"
    df = collector.load_from_parquet(symbol)
    
    if df.empty:
        print(f"   本地无数据，正在采集 {symbol}...")
        df = collector.get_stock_history(symbol, start_date="20200101", end_date="20241231")
        if df.empty:
            print("   数据采集失败，退出")
            return
    
    # 设置日期索引
    df = df.set_index('date')
    print(f"   加载数据: {len(df)} 条 ({df.index[0].date()} ~ {df.index[-1].date()})")
    
    # 2. 创建策略
    print("\n[2/3] 创建策略...")
    strategy = SmaCrossStrategy(params={
        'fast_period': 10,
        'slow_period': 30
    })
    print(f"   策略: {strategy.__class__.__name__}")
    
    # 3. 运行回测
    print("\n[3/3] 运行回测...")
    engine = BacktestEngine(
        initial_cash=config.backtest.initial_cash,
        commission=config.backtest.commission,
        slippage=config.backtest.slippage,
    )
    
    result = engine.run(df, strategy, symbol=symbol)
    
    # 4. 打印结果
    engine.print_result(result)
    
    return result


def compare_strategies():
    """比较不同策略"""
    setup_logger()
    config = get_config()
    
    print("\n" + "=" * 60)
    print("           策略对比")
    print("=" * 60)
    
    # 加载数据
    collector = DataCollector(raw_dir=config.data.raw_dir)
    symbol = "000001"
    df = collector.load_from_parquet(symbol)
    
    if df.empty:
        df = collector.get_stock_history(symbol, start_date="20200101", end_date="20241231")
    
    df = df.set_index('date')
    
    # 测试不同策略
    strategies = [
        ("双均线(10,30)", SmaCrossStrategy, {'fast_period': 10, 'slow_period': 30}),
        ("双均线(5,20)", SmaCrossStrategy, {'fast_period': 5, 'slow_period': 20}),
        ("MACD", MACDStrategy, {}),
    ]
    
    results = []
    for name, strategy_class, params in strategies:
        engine = BacktestEngine(initial_cash=100000)
        strategy = strategy_class(params=params)
        result = engine.run(df, strategy, symbol=symbol)
        results.append((name, result))
    
    # 打印对比
    print("\n{:<20} {:>12} {:>12} {:>12} {:>12}".format(
        "策略", "总收益率", "年化收益", "最大回撤", "夏普比率"
    ))
    print("-" * 70)
    
    for name, result in results:
        print("{:<20} {:>12.2%} {:>12.2%} {:>12.2%} {:>12.2f}".format(
            name, result.total_return, result.annual_return, 
            result.max_drawdown, result.sharpe_ratio
        ))
    
    print("=" * 70 + "\n")


if __name__ == "__main__":
    # 运行单个回测
    run_backtest_example()
    
    # 对比不同策略 (可选)
    # compare_strategies()
