"""
测试布林带和RSI策略回测
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.collector import DataCollector
from src.backtest.engine import BacktestEngine
from src.strategy.mean_reversion_strategy import BollingerBandsStrategy, RSIStrategy, RSI2Strategy
from src.strategy.trend_strategy import SmaCrossStrategy  # 作为对比

def test_strategy(name, strategy_cls, params):
    """测试单个策略"""
    print(f"\n{'=' * 60}")
    print(f"测试策略: {name}")
    print(f"{'=' * 60}")
    
    # 采集数据
    collector = DataCollector()
    df = collector.get_stock_history("000001", start_date="20200101", end_date="20240528")
    
    if df.empty:
        print("数据获取失败!")
        return None
    
    data = df.set_index('date')
    print(f"数据范围: {data.index[0].date()} ~ {data.index[-1].date()}, {len(data)} 条")
    
    # 回测
    engine = BacktestEngine(
        initial_cash=100000,
        commission=0.0003,
        slippage=0.0001,
        stamp_duty=0.001,
    )
    
    strategy = strategy_cls(params=params)
    result = engine.run(data, strategy, symbol="000001")
    engine.print_result(result)
    return result


if __name__ == "__main__":
    results = {}
    
    # 1. 布林带策略
    r = test_strategy("布林带均值回归", BollingerBandsStrategy, {
        "period": 20, "std_dev": 2.0, "exit_std_dev": 0.5, "stop_loss": 0.05
    })
    if r: results["布林带"] = r
    
    # 2. RSI策略
    r = test_strategy("RSI超买超卖", RSIStrategy, {
        "period": 14, "oversold": 30, "overbought": 70, "stop_loss": 0.05
    })
    if r: results["RSI"] = r
    
    # 3. RSI2短线策略
    r = test_strategy("RSI2短线反转", RSI2Strategy, {
        "period": 2, "oversold": 10, "overbought": 90, "stop_loss": 0.03
    })
    if r: results["RSI2"] = r
    
    # 4. 双均线对比
    r = test_strategy("双均线(对比)", SmaCrossStrategy, {
        "fast_period": 10, "slow_period": 30
    })
    if r: results["双均线"] = r
    
    # 总结
    if results:
        print("\n" + "=" * 60)
        print("                    策略对比总结")
        print("=" * 60)
        print(f"{'策略':<16} {'总收益率':>10} {'年化':>10} {'最大回撤':>10} {'夏普':>8} {'胜率':>8} {'交易':>6}")
        print("-" * 60)
        for name, r in results.items():
            print(f"{name:<16} {r.total_return:>10.2%} {r.annual_return:>10.2%} {r.max_drawdown:>10.2%} {r.sharpe_ratio:>8.2f} {r.win_rate:>8.2%} {r.total_trades:>6}")
        print("=" * 60)
