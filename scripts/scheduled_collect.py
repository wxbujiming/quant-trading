"""
定时数据采集脚本
用法:
    python scripts/scheduled_collect.py              # 立即执行一次采集
    python scripts/scheduled_collect.py --daemon     # 启动守护进程，每天定时采集
    python scripts/scheduled_collect.py --incremental # 增量更新（只获取最新数据）

功能:
  1. 读取已缓存的股票列表，增量更新最新行情
  2. 自动识别交易日，非交易日跳过
  3. 采集完成后可选运行清洗+回测
  4. 失败重试 + 通知推送
"""
import sys
import time
import json
import argparse
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from loguru import logger

from src.core.logger import setup_logger
from src.core.config import get_config
from src.data.collector import DataCollector
from src.data.cleaner import DataCleaner


# ──────────────── 工具函数 ────────────────

def _is_trading_day(dt: date = None) -> bool:
    """
    粗略判断是否为交易日
    - 周一至周五
    - 排除法定节假日（简化版，只排除元旦、春节等主要节日的前后几天）
    """
    if dt is None:
        dt = date.today()

    # 周末
    if dt.weekday() >= 5:
        return False

    # 简化节假日判断：1月1日（元旦）、春节（农历正月初一附近，用1月底2月初近似）
    # 实际使用时建议接入交易日历API
    month, day = dt.month, dt.day
    if month == 1 and day == 1:
        return False
    if month == 5 and day in (1, 2, 3):
        return False
    if month == 10 and day in (1, 2, 3, 4, 5, 6, 7):
        return False

    return True


def _should_run_today(run_time: str = "16:00") -> bool:
    """判断今天是否需要运行"""
    now = datetime.now()

    # 非交易日跳过
    if not _is_trading_day(now.date()):
        logger.info(f"非交易日 ({now.date()})，跳过采集")
        return False

    # 如果是守护进程模式：在当前时间到达设定时间后才运行
    target_hour, target_min = map(int, run_time.split(":"))
    current_minutes = now.hour * 60 + now.minute
    target_minutes = target_hour * 60 + target_min

    # 如果在设定时间之前，跳过
    if current_minutes < target_minutes:
        return False

    return True


# ──────────────── 核心采集逻辑 ────────────────

def get_cached_symbols(collector: DataCollector) -> List[str]:
    """
    获取已缓存的股票列表

    Returns:
        已缓存股票的代码列表
    """
    symbols = []
    for f in Path(collector.raw_dir).glob("*.parquet"):
        stem = f.stem
        # 跳过指数文件
        if stem.startswith("index_"):
            continue
        symbols.append(stem)
    return sorted(symbols)


def get_incremental_dates(symbol: str, collector: DataCollector,
                          lookback_days: int = 10) -> tuple:
    """
    计算增量更新的日期范围

    Returns:
        (start_date, end_date) 字符串，或 (None, None) 表示全量
    """
    cached = collector.load_from_parquet(symbol)
    if cached.empty:
        return (None, None)  # 无缓存，全量采集

    last_date = pd.to_datetime(cached["date"].max())
    # 从最后日期的前一天开始（确保数据完整）
    start = (last_date - timedelta(days=1)).strftime("%Y%m%d")
    end = datetime.now().strftime("%Y%m%d")
    return (start, end)


def collect_single(symbol: str, collector: DataCollector,
                   incremental: bool = True,
                   force_full: bool = False) -> bool:
    """
    采集单只股票数据

    Returns:
        是否成功
    """
    try:
        if incremental and not force_full:
            start_date, end_date = get_incremental_dates(symbol, collector)
            if start_date and end_date:
                df = collector.get_stock_history(symbol, start_date=start_date, end_date=end_date)
            else:
                # 无缓存，全量采集
                df = collector.get_stock_history(symbol)
        else:
            df = collector.get_stock_history(symbol)

        if df is not None and not df.empty:
            return True
        return False
    except Exception as e:
        logger.error(f"[{symbol}] 采集失败: {e}")
        return False


def run_collection(symbols: List[str] = None, incremental: bool = True,
                   max_workers: int = 3, run_clean: bool = True,
                   run_backtest: bool = False) -> dict:
    """
    执行数据采集

    Args:
        symbols: 股票列表，None=全部已缓存股票
        incremental: 是否增量更新
        max_workers: 并发数
        run_clean: 采集后是否运行清洗
        run_backtest: 采集后是否运行回测

    Returns:
        采集结果统计
    """
    config = get_config()
    collector = DataCollector(raw_dir=config.data.raw_dir)

    # 确定采集列表
    if symbols is None:
        symbols = get_cached_symbols(collector)

    if not symbols:
        logger.warning("没有已缓存的股票，请先运行 scripts/collect_data.py 进行初始采集")
        return {"status": "error", "reason": "no_cached_symbols"}

    total = len(symbols)
    logger.info(f"开始采集 {total} 只股票 (增量={'是' if incremental else '否'})...")

    # 逐个采集（带限速，不真正并发）
    success_count = 0
    fail_count = 0
    fail_list = []

    for i, symbol in enumerate(symbols, 1):
        ok = collect_single(symbol, collector, incremental=incremental)
        if ok:
            success_count += 1
        else:
            fail_count += 1
            fail_list.append(symbol)

        if i % 10 == 0 or i == total:
            logger.info(f"进度: [{i}/{total}] 成功={success_count} 失败={fail_count}")

    # 采集后清洗
    if run_clean and success_count > 0:
        logger.info("采集完成，开始清洗数据...")
        cleaner = DataCleaner()
        for symbol in symbols:
            df = collector.load_from_parquet(symbol)
            if not df.empty:
                cleaner.clean(df, stock_code=symbol)

    result = {
        "status": "success",
        "total": total,
        "success": success_count,
        "fail": fail_count,
        "fail_list": fail_list,
        "incremental": incremental,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    logger.success(f"采集完成: 成功={success_count}/{total}, 失败={fail_count}")
    if fail_list:
        logger.warning(f"失败股票: {fail_list}")

    # 可选的回测
    if run_backtest and success_count > 0:
        logger.info("触发回测...")
        try:
            from scripts.run_backtest import run_all_strategies
            run_all_strategies()
        except Exception as e:
            logger.error(f"回测执行失败: {e}")

    return result


# ──────────────── 守护进程模式 ────────────────

def run_daemon(run_time: str = "16:00", check_interval: int = 60,
               incremental: bool = True, run_clean: bool = True,
               run_backtest: bool = False):
    """
    以守护进程方式运行，每天定时采集

    Args:
        run_time: 每日运行时间 HH:MM 格式
        check_interval: 检查间隔（秒）
    """
    logger.info(f"启动定时采集守护进程")
    logger.info(f"  运行时间: 每天 {run_time}")
    logger.info(f"  检查间隔: {check_interval}秒")
    logger.info(f"  增量模式: {'是' if incremental else '否'}")
    logger.info(f"  采集后清洗: {'是' if run_clean else '否'}")
    logger.info(f"  采集后回测: {'是' if run_backtest else '否'}")
    logger.info("=" * 50)

    # 记录上次运行日期，避免一天内重复运行
    last_run_date = None

    while True:
        now = datetime.now()

        # 判断是否应该运行
        if _should_run_today(run_time):
            today_str = now.strftime("%Y-%m-%d")

            if last_run_date != today_str:
                logger.info(f">>> 开始今日采集 ({today_str}) <<<")
                result = run_collection(
                    symbols=None,
                    incremental=incremental,
                    run_clean=run_clean,
                    run_backtest=run_backtest,
                )
                last_run_date = today_str

                # 失败通知
                if result.get("status") == "success" and result.get("fail", 0) > 0:
                    logger.warning(f"有 {result['fail']} 只股票采集失败")
            else:
                logger.debug(f"今日 {today_str} 已采集过，跳过")
        else:
            logger.debug(f"未到运行时间或非交易日，当前时间: {now.strftime('%H:%M')}")

        # 等待
        time.sleep(check_interval)


# ──────────────── 主入口 ────────────────

def main():
    parser = argparse.ArgumentParser(
        description="定时数据采集工具 - 每日收盘后自动更新行情数据"
    )
    parser.add_argument(
        "--daemon", action="store_true",
        help="以守护进程模式运行，每天定时采集"
    )
    parser.add_argument(
        "--incremental", action="store_true", default=True,
        help="增量更新（只获取最新数据，默认开启）"
    )
    parser.add_argument(
        "--full", action="store_true",
        help="全量更新（覆盖重新采集）"
    )
    parser.add_argument(
        "--symbols", type=str, nargs="*",
        help="指定采集的股票代码列表，不指定则采集所有已缓存的"
    )
    parser.add_argument(
        "--no-clean", action="store_true",
        help="采集后不执行数据清洗"
    )
    parser.add_argument(
        "--backtest", action="store_true",
        help="采集完成后运行回测"
    )
    parser.add_argument(
        "--run-time", type=str, default="16:00",
        help="守护进程模式下每天的运行时间 (默认16:00)"
    )
    parser.add_argument(
        "--list-cache", action="store_true",
        help="查看本地缓存状态"
    )

    args = parser.parse_args()
    setup_logger()
    config = get_config()

    # 查看缓存状态
    if args.list_cache:
        collector = DataCollector(raw_dir=config.data.raw_dir)
        info = collector.get_cache_info()
        print("\n" + "=" * 60)
        print("          本地数据缓存状态")
        print("=" * 60)
        if not info:
            print("   暂无缓存数据")
        else:
            print(f"   {'代码':<8} {'行数':<8} {'大小':<10} {'最后日期':<15}")
            print("-" * 45)
            for code, i in sorted(info.items()):
                print(f"   {code:<8} {i['rows']:<8} {i['size_kb']:<8}KB {i['last_date']:<15}")
            print(f"\n   共 {len(info)} 只股票")
        return

    # 守护进程模式
    if args.daemon:
        run_daemon(
            run_time=args.run_time,
            incremental=not args.full,
            run_clean=not args.no_clean,
            run_backtest=args.backtest,
        )
        return

    # 单次执行模式
    incremental = not args.full
    symbols = args.symbols

    # 如果没指定股票，从配置读取或自动检测
    if not symbols and config.schedule.collect_symbols:
        symbols = config.schedule.collect_symbols

    print("\n" + "=" * 60)
    print("          定时数据采集工具")
    print("=" * 60)
    print(f"  模式: {'增量' if incremental else '全量'}")
    print(f"  清洗: {'否' if args.no_clean else '是'}")
    print(f"  回测: {'是' if args.backtest else '否'}")
    print()

    result = run_collection(
        symbols=symbols,
        incremental=incremental,
        run_clean=not args.no_clean,
        run_backtest=args.backtest,
    )

    # 输出 JSON 格式结果（便于被其他程序调用）
    print("\n" + "-" * 40)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("-" * 40)

    # 非零退出码表示有失败
    if result.get("fail", 0) > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
