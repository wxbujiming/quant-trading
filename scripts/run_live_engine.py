"""
实盘策略引擎启动脚本

用法:
    python scripts/run_live_engine.py --symbol RB2410               # 指定品种
    python scripts/run_live_engine.py --symbol RB2410 --simulate    # 模拟模式
    python scripts/run_live_engine.py --symbol RB2410 --daemon      # 守护进程模式
    python scripts/run_live_engine.py --strategy SimpleTrendStrategy
"""
import sys
import time
import argparse
import json
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from src.core.logger import setup_logger
from src.core.config import get_config
from src.trade.ctp_gateway import CtpGateway
from src.trade.risk_manager import RiskManager
from src.engine.live_engine import LiveEngine, EngineState
from src.strategy.futures_strategy import (
    DualMaCrossStrategy,
    SimpleTrendStrategy,
)


STRATEGY_MAP = {
    "DualMaCrossStrategy": DualMaCrossStrategy,
    "SimpleTrendStrategy": SimpleTrendStrategy,
}


def create_strategy(name: str, params: dict = None):
    """策略工厂"""
    cls = STRATEGY_MAP.get(name)
    if not cls:
        raise ValueError(f"未知策略: {name}, 可选: {list(STRATEGY_MAP.keys())}")
    return cls(params=params or {})


def run_simulate_demo(engine: LiveEngine, interval: float = 2.0):
    """
    模拟成交辅助线程

    在 --simulate 模式下自动填充挂单，模拟成交流程。
    """
    while engine.state not in (EngineState.STOPPED, EngineState.ERROR):
        if engine.state == EngineState.RUNNING:
            for soid, info in list(engine._pending_orders.items()):
                if info.status == "pending" and hasattr(engine.gateway, "simulate_trade"):
                    fill_price = info.price * 1.001 if "long" in info.direction else info.price * 0.999
                    engine.gateway.simulate_trade(
                        info.engine_order_id,
                        price=round(fill_price, 2),
                        volume=info.volume,
                    )
                    time.sleep(interval)
        time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description="期货实盘策略引擎")
    parser.add_argument("--symbol", type=str, nargs="+", help="品种代码列表 (如 RB2410 CU2409)")
    parser.add_argument("--strategy", type=str, default="DualMaCrossStrategy", help="策略名称")
    parser.add_argument("--params", type=str, default=None, help="策略参数JSON (如 '{\"fast_period\": 10}')")
    parser.add_argument("--daemon", action="store_true", help="守护进程模式")
    parser.add_argument("--real", action="store_true", help="真实模式 (连接SimNow)")
    parser.add_argument("--simulate", action="store_true", help="模拟模式 (自动成交)")
    parser.add_argument("--bar-interval", type=int, default=1, help="K线周期 (分钟)")
    parser.add_argument("--capital", type=float, default=None, help="初始资金")
    args = parser.parse_args()

    # 初始化日志
    setup_logger("DEBUG", "logs/live_engine.log")
    logger.info("=" * 50)
    logger.info("实盘策略引擎启动")
    logger.info("=" * 50)

    # 加载配置
    config = get_config()
    live_cfg = config.live

    # CLI 参数覆盖
    if args.symbol:
        live_cfg.symbols = args.symbol
    if args.bar_interval:
        live_cfg.bar_interval_minutes = args.bar_interval
    if args.capital:
        live_cfg.initial_capital = args.capital

    if not live_cfg.symbols:
        print("错误: 未指定品种代码 (使用 --symbol)")
        sys.exit(1)

    # 策略参数
    strategy_params = {}
    if args.params:
        strategy_params = json.loads(args.params)
    elif live_cfg.strategy_params:
        strategy_params = live_cfg.strategy_params

    # 创建网关
    real_mode = args.real or live_cfg.real_mode
    gateway = CtpGateway(
        gateway_name=live_cfg.gateway_name,
        setting={
            "broker_id": live_cfg.broker_id,
            "user_id": live_cfg.user_id,
            "password": live_cfg.password,
            "app_id": live_cfg.app_id,
            "auth_code": live_cfg.auth_code,
            "environment": live_cfg.environment,
            "real_mode": real_mode,
            # 断线重连配置
            "reconnect_enabled": live_cfg.reconnect_enabled,
            "reconnect_initial_delay": live_cfg.reconnect_initial_delay,
            "reconnect_max_delay": live_cfg.reconnect_max_delay,
            "reconnect_max_attempts": live_cfg.reconnect_max_attempts,
        },
    )

    # 创建引擎
    engine = LiveEngine(gateway=gateway, config=live_cfg)

    # 创建策略
    strategy = create_strategy(args.strategy, strategy_params)
    logger.info(f"策略: {args.strategy}, 参数: {strategy_params}")

    # 模拟成交线程
    sim_thread = None
    if args.simulate:
        logger.info("模拟模式: 自动成交已启用")
        sim_thread = threading.Thread(
            target=run_simulate_demo,
            args=(engine,),
            daemon=True,
        )
        sim_thread.start()

    # 启动引擎
    try:
        engine.run(strategy, live_cfg.symbols)

        if args.daemon:
            logger.info("守护进程模式运行中...")
            try:
                while engine.state not in (EngineState.STOPPED, EngineState.ERROR):
                    time.sleep(10)
            except KeyboardInterrupt:
                logger.info("收到中断信号")
        else:
            logger.info("引擎运行中 (按 Ctrl+C 停止)...")
            try:
                while engine.state not in (EngineState.STOPPED, EngineState.ERROR):
                    time.sleep(1)
            except KeyboardInterrupt:
                logger.info("收到中断信号")

    finally:
        engine.stop()
        engine.risk_manager.print_system_summary()
        logger.success("实盘引擎已安全停止")


if __name__ == "__main__":
    main()
