"""
定时任务调度启动脚本

集成了实盘引擎生命周期管理、数据采集、健康检查等任务。

用法:
    python scripts/scheduler.py                    # 查看任务列表
    python scripts/scheduler.py --daemon           # 启动守护进程
    python scripts/scheduler.py --list             # 查看所有任务
    python scripts/scheduler.py --run-task 开盘检查  # 手动执行单个任务

守护进程模式:
    — 08:30  开盘前检查 + 启动引擎
    — 09:30  盘中健康检查
    — 10:00  盘中健康检查
    — 11:00  盘中健康检查
    — 13:30  盘中健康检查
    — 14:00  盘中健康检查
    — 15:30  收盘处理(日报/状态持久化)
    — 16:00  数据采集(增量)
"""
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from src.core.logger import setup_logger
from src.core.config import get_config
from src.engine.scheduler import TaskScheduler
from src.data.collector import DataCollector


# ────────── 全局引擎引用（实盘模式延时初始化） ──────────

_engine = None


def get_engine():
    """获取全局引擎实例（首次调用时启动）"""
    global _engine
    if _engine is None:
        _engine = _init_engine()
    return _engine


def _init_engine():
    """初始化并启动实盘引擎"""
    from src.trade.ctp_gateway import CtpGateway
    from src.engine.live_engine import LiveEngine

    config = get_config()
    live_cfg = config.live

    if not live_cfg.symbols:
        logger.warning("未配置交易品种，跳过引擎初始化")
        return None

    gateway = CtpGateway(
        gateway_name=live_cfg.gateway_name,
        setting={
            "broker_id": live_cfg.broker_id,
            "user_id": live_cfg.user_id,
            "password": live_cfg.password,
            "app_id": live_cfg.app_id,
            "auth_code": live_cfg.auth_code,
            "environment": live_cfg.environment,
            "real_mode": live_cfg.real_mode,
            "reconnect_enabled": live_cfg.reconnect_enabled,
        },
    )

    from src.strategy.futures_strategy import DualMaCrossStrategy
    strategy = DualMaCrossStrategy(params=live_cfg.strategy_params or {})

    engine = LiveEngine(gateway=gateway, config=live_cfg)
    engine.run(strategy, live_cfg.symbols)
    return engine


# ────────── 任务回调定义 ──────────

def pre_market_check():
    """08:30 - 开盘前系统检查"""
    config = get_config()
    logger.info("【开盘前检查】开始")
    logger.info(f"  今日交易日: {datetime.now().strftime('%Y-%m-%d')}")
    logger.info(f"  品种: {config.live.symbols}")
    logger.info(f"  策略: {config.live.strategy_name}")

    # 检查数据是否完整
    collector = DataCollector()
    if config.live.symbols:
        for sym in config.live.symbols:
            df = collector.load_from_parquet(sym)
            if df.empty:
                logger.warning(f"  {sym}: 无缓存数据，开盘后将自动采集")
            else:
                last = df["date"].max()
                logger.info(f"  {sym}: 缓存到 {last}")

    # 仅在实盘模式启动引擎
    if config.live.real_mode:
        eng = get_engine()
        if eng:
            logger.success("开盘前检查完成，引擎已启动")
    else:
        logger.info("模拟模式，引擎待手动启动")
    logger.success("【开盘前检查】完成")


def health_check():
    """盘中健康检查（每 30 分钟）"""
    if _engine is None:
        return

    from src.engine.live_engine import EngineState
    state = _engine.state
    now = datetime.now().strftime("%H:%M:%S")

    if state == EngineState.ERROR:
        logger.warning(f"[{now}] 健康检查: 引擎异常状态")
    elif state == EngineState.RUNNING:
        positions = _engine.position_manager.get_all_positions()
        pos_count = len(positions)
        logger.info(f"[{now}] 健康检查: 引擎正常, {pos_count} 个持仓")
    else:
        logger.info(f"[{now}] 健康检查: 引擎状态={state.name}")


def post_market_report():
    """15:30 - 收盘后生成日报"""
    if _engine is None:
        logger.info("引擎未运行，跳过收盘处理")
        return

    _engine._save_state()
    logger.info("收盘后: 状态已保存")

    report_path = ""
    if _engine.alerter:
        try:
            report_path = _engine.alerter.generate_daily_report()
        except Exception as e:
            logger.error(f"生成日报失败: {e}")

    total_pnl = 0
    for pos in _engine.position_manager.get_all_positions():
        total_pnl += pos.pnl

    logger.success(f"【收盘】日报: {report_path or '未生成'}, "
                   f"当日累计盈亏: {total_pnl:+,.0f}")


def collect_data():
    """16:00 - 数据采集"""
    config = get_config()
    collector = DataCollector(raw_dir=config.data.raw_dir)
    symbols = config.schedule.collect_symbols or []

    if not symbols:
        symbols = _get_cached_symbols(collector)

    if not symbols:
        logger.info("无待采集品种，跳过")
        return

    logger.info(f"【数据采集】开始: {len(symbols)} 个品种")
    success = 0
    for sym in symbols:
        try:
            df = collector.get_stock_history(sym)
            if df is not None and not df.empty:
                success += 1
        except Exception as e:
            logger.error(f"  {sym} 采集失败: {e}")

    logger.success(f"【数据采集】完成: {success}/{len(symbols)}")


def _get_cached_symbols(collector) -> list:
    """获取已缓存的品种列表"""
    symbols = []
    for f in Path(collector.raw_dir).glob("*.parquet"):
        stem = f.stem
        if stem.startswith("index_"):
            continue
        symbols.append(stem)
    return sorted(symbols)


# ────────── 主入口 ──────────

def main():
    parser = argparse.ArgumentParser(description="定时任务调度器")
    parser.add_argument("--daemon", action="store_true", help="启动守护进程")
    parser.add_argument("--list", action="store_true", help="查看所有任务")
    parser.add_argument("--run-task", type=str, default=None, help="手动执行任务")
    args = parser.parse_args()

    setup_logger("INFO", "logs/scheduler.log")

    if args.list:
        scheduler = TaskScheduler()
        _register_all_tasks(scheduler)
        print(scheduler.summary())
        return

    if args.run_task:
        task_map = {
            "开盘检查": pre_market_check,
            "健康检查": health_check,
            "收盘处理": post_market_report,
            "数据采集": collect_data,
        }
        cb = task_map.get(args.run_task)
        if cb:
            cb()
        else:
            print(f"未知任务: {args.run_task}, 可选: {list(task_map.keys())}")
        return

    # 启动守护进程
    logger.info("=" * 50)
    logger.info("定时任务调度器启动 (守护进程模式)")
    logger.info("=" * 50)

    scheduler = TaskScheduler(trading_days_only=True, check_interval=10)
    _register_all_tasks(scheduler)

    scheduler.start()
    print(scheduler.summary())

    try:
        scheduler.wait()
    except KeyboardInterrupt:
        logger.info("收到中断信号")
    finally:
        scheduler.stop()
        if _engine:
            _engine.stop()
        logger.success("调度器已安全停止")


def _register_all_tasks(scheduler: TaskScheduler):
    """注册所有定时任务"""
    scheduler.daily("08:30", pre_market_check,
                    name="开盘检查", description="检查数据完整性和连接状态")
    scheduler.daily("09:30", health_check,
                    name="健康检查1", description="盘中健康检查")
    scheduler.daily("10:00", health_check,
                    name="健康检查2", description="盘中健康检查")
    scheduler.daily("11:00", health_check,
                    name="健康检查3", description="盘中健康检查")
    scheduler.daily("13:30", health_check,
                    name="健康检查4", description="盘中健康检查")
    scheduler.daily("14:00", health_check,
                    name="健康检查5", description="盘中健康检查")
    scheduler.daily("15:30", post_market_report,
                    name="收盘处理", description="生成日报+持久化状态")
    scheduler.daily("16:00", collect_data,
                    name="数据采集", description="增量更新行情数据")


if __name__ == "__main__":
    main()
