"""
期货策略模拟回放脚本

从 akshare 获取历史日线数据，生成合成 Tick 驱动实盘引擎运行。
用法:
    python scripts/run_simulation.py --symbol RB --days 30
    python scripts/run_simulation.py --symbol RB --days 30 --strategy DualMaCrossStrategy
    python scripts/run_simulation.py --symbol RB --days 30 --fast 5 --slow 20
"""
import sys
import time
import argparse
import random
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import akshare as ak
from loguru import logger

from src.core.logger import setup_logger
from src.core.config import get_config, LiveConfig
from src.trade.ctp_gateway import CtpGateway
from src.trade.gateway import TickData, OrderDirection
from src.engine.live_engine import LiveEngine, EngineState
from src.strategy.futures_strategy import DualMaCrossStrategy, SimpleTrendStrategy

STRATEGY_MAP = {
    "DualMaCrossStrategy": DualMaCrossStrategy,
    "SimpleTrendStrategy": SimpleTrendStrategy,
}


def fetch_rb_daily(symbol: str = "RB", days: int = 60) -> pd.DataFrame:
    """获取螺纹钢连续日线数据"""
    logger.info(f"获取 {symbol} 连续合约日线数据 (最近 {days} 天)...")
    try:
        df = ak.futures_main_sina(symbol=f"{symbol}0")
        df.columns = ["date", "open", "high", "low", "close", "volume", "hold", "settle"]
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").tail(days)
        logger.info(f"获取 {len(df)} 条日线数据: {df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()}")
        return df
    except Exception as e:
        logger.error(f"获取数据失败: {e}")
        # 如果没有网络，生成随机模拟数据
        logger.warning("使用随机生成的数据进行本地模拟")
        return _generate_fake_data(days)


def _generate_fake_data(days: int) -> pd.DataFrame:
    """生成随机模拟日线数据"""
    records = []
    price = 3200.0
    base = pd.Timestamp.now().normalize() - timedelta(days=days)
    for i in range(days):
        change = random.gauss(0, 20)
        open_p = round(price, 1)
        high = round(open_p + abs(random.gauss(0, 15)) + 2, 1)
        low = round(open_p - abs(random.gauss(0, 15)) - 2, 1)
        close = round(open_p + change, 1)
        close = max(low + 1, min(high - 1, close))
        volume = int(random.gauss(800000, 200000))
        records.append({
            "date": base + timedelta(days=i),
            "open": open_p, "high": high, "low": low, "close": close,
            "volume": volume, "hold": int(volume * 2.5), "settle": close,
        })
        price = close
    return pd.DataFrame(records).sort_values("date")


def generate_ticks_from_daily(row: pd.Series, n_ticks: int = 300,
                                start_hour: int = 9, start_minute: int = 1) -> list:
    """
    从日线 OHLC 生成合成 Tick（日内随机游走）。
    生成约 n_ticks 个 tick，分布于一天内。
    """
    o, h, l, c = row["open"], row["high"], row["low"], row["close"]
    volume = int(row.get("volume", 800000))
    date = row["date"]

    ticks = []
    price = o

    # 生成价格序列：从 open 开始，收盘回到 close，期间在 [low, high] 内波动
    prices = [o]
    mid = (h + l) / 2
    for _ in range(n_ticks - 1):
        drift = (c - prices[-1]) / max(n_ticks - len(prices), 1)
        noise = random.gauss(0, (h - l) / 10)
        next_p = prices[-1] + drift * 0.3 + noise
        next_p = max(l, min(h, next_p))
        prices.append(round(next_p, 1))
    prices[-1] = c

    # 构建 tick 时间线（日盘 9:00~15:00）
    day_start = pd.Timestamp(date).replace(hour=9, minute=0, second=0)
    day_end = pd.Timestamp(date).replace(hour=15, minute=0, second=0)
    time_points = pd.date_range(day_start, day_end, periods=n_ticks)

    # 午休过滤 (11:30~13:30 停止生成)
    filtered = []
    for i, tp in enumerate(time_points):
        t = tp.hour * 100 + tp.minute
        if 1130 <= t < 1330:
            continue
        filtered.append((tp, prices[i]))
    if not filtered:
        filtered = [(tp, prices[i]) for i, tp in enumerate(time_points)]

    # 生成 TickData
    for tp, p in filtered:
        spread = max(round(p * 0.0002, 1), 0.5)
        tick = TickData(
            symbol=row.get("symbol", "RB2610"),
            exchange="SHFE",
            last_price=p,
            volume=max(1, int(volume / len(filtered))),
            open_interest=0,
            bid_price_1=round(p - spread, 1),
            bid_volume_1=random.randint(10, 200),
            ask_price_1=round(p + spread, 1),
            ask_volume_1=random.randint(10, 200),
            datetime=tp.to_pydatetime(),
            gateway_name="SimNow",
        )
        ticks.append(tick)
    return ticks


def main():
    parser = argparse.ArgumentParser(description="期货策略模拟回放")
    parser.add_argument("--symbol", type=str, default="RB", help="品种代码 (默认 RB)")
    parser.add_argument("--contract", type=str, default="RB2610", help="合约代码")
    parser.add_argument("--days", type=int, default=30, help="回放天数")
    parser.add_argument("--strategy", type=str, default="DualMaCrossStrategy",
                        help="策略名称")
    parser.add_argument("--fast", type=int, default=10, help="快线周期")
    parser.add_argument("--slow", type=int, default=30, help="慢线周期")
    parser.add_argument("--capital", type=float, default=20000000.0, help="初始资金")
    parser.add_argument("--speed", type=float, default=10.0,
                        help="回放速度倍速 (默认 10x, 0=瞬间完成)")
    args = parser.parse_args()

    setup_logger("INFO", "logs/simulation.log")

    # ── 1. 获取日线数据 ──
    daily = fetch_rb_daily(args.symbol, args.days)
    if daily.empty:
        logger.error("无数据，退出")
        return
    logger.info(f"\n{daily[['date','open','high','low','close','volume']].tail(10).to_string(index=False)}")

    # ── 2. 创建引擎 ──
    config = get_config()
    live_cfg = config.live
    live_cfg.initial_capital = args.capital
    live_cfg.symbols = [args.contract]
    live_cfg.bar_interval_minutes = 1
    live_cfg.oi_tracker_enabled = False  # 模拟环境关闭 OI 追踪
    live_cfg.cancel_monitor_enabled = False
    live_cfg.auto_reduce_enabled = False

    gateway = CtpGateway(gateway_name="SimNow", setting={"real_mode": False})
    engine = LiveEngine(gateway=gateway, config=live_cfg)

    strategy_params = {"fast_period": args.fast, "slow_period": args.slow,
                       "atr_multiplier": 2.0, "max_risk_pct": 0.02}
    strategy_class = STRATEGY_MAP.get(args.strategy)
    if not strategy_class:
        logger.error(f"未知策略: {args.strategy}")
        return
    strategy = strategy_class(params=strategy_params)
    logger.info(f"策略: {args.strategy}, 参数: {strategy_params}")

    engine.run(strategy, live_cfg.symbols)
    time.sleep(0.5)

    if engine.state != EngineState.RUNNING:
        logger.error("引擎启动失败")
        return

    # ── 3. Tick 回放 ──
    total_days = len(daily)
    logger.info(f"开始回放 {total_days} 个交易日...")

    for idx, (_, day_row) in enumerate(daily.iterrows()):
        if engine.state == EngineState.STOPPED:
            break

        day_row["symbol"] = args.contract
        ticks = generate_ticks_from_daily(day_row, n_ticks=200)

        logger.info(f"[{idx+1}/{total_days}] 回放 {day_row['date'].date()} "
                    f"O={day_row['open']} H={day_row['high']} "
                    f"L={day_row['low']} C={day_row['close']} "
                    f"({len(ticks)} ticks)")

        for tick in ticks:
            if engine.state == EngineState.STOPPED:
                break
            engine._on_tick(tick)
            if args.speed > 0:
                time.sleep(1.0 / (200 / 240) / args.speed)  # 模拟240分钟交易时段

        # 强制刷新 K 线
        engine._flush_bars()

    # ── 4. 收盘报告 ──
    engine._save_state()

    logger.info("=" * 50)
    logger.info("模拟回放完成")
    logger.info("=" * 50)

    # 打印持仓
    positions = engine.position_manager.get_all_positions()
    if positions:
        logger.info("最终持仓:")
        for pos in positions:
            logger.info(f"  {pos.symbol} {'多' if pos.direction == OrderDirection.BUY else '空'} "
                        f"{pos.volume}手 @ {pos.price}, PnL={pos.pnl:+,.0f}")
    else:
        logger.info("最终持仓: 无")

    account = engine.position_manager.get_account()
    if account:
        total_pnl = account.balance - live_cfg.initial_capital
        logger.info(f"账户: 余额={account.balance:,.0f}, "
                    f"可用={account.available:,.0f}, "
                    f"总盈亏={total_pnl:+,.0f}")

    # 打印交易统计
    try:
        engine.risk_manager.print_system_summary()
    except Exception:
        pass

    engine.stop()


if __name__ == "__main__":
    main()
