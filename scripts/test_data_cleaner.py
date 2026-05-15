"""
数据清洗模块测试
用法: python scripts/test_data_cleaner.py

测试内容:
  1. 从Parquet加载真实数据
  2. 注入缺失值和异常值
  3. 执行全流程清洗
  4. 打印质量报告
  5. 生成前后对比图
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
from loguru import logger

from src.core.logger import setup_logger
from src.core.config import get_config
from src.data.collector import DataCollector
from src.data.cleaner import DataCleaner


def test_basic_cleaning():
    """测试基本清洗流程"""
    print("\n" + "=" * 60)
    print("          测试1: 基础清洗流程")
    print("=" * 60)

    config = get_config()
    collector = DataCollector(raw_dir=config.data.raw_dir)
    cleaner = DataCleaner()

    # 加载数据
    symbol = "000001"
    df = collector.load_from_parquet(symbol)

    if df.empty:
        print("   本地无数据，尝试采集...")
        df = collector.get_stock_history(symbol, start_date="20200101", end_date="20240528")

    if df.empty:
        print("   无法获取数据，跳过测试")
        return

    print(f"   原始数据: {len(df)} 行, {list(df.columns)}")

    # 生成质量报告（清洗前）
    print("\n   ── 清洗前质量报告 ──")
    before_report = cleaner.quality_report(df)
    for k, v in before_report.items():
        if isinstance(v, dict):
            print(f"     {k}:")
            for sk, sv in v.items():
                print(f"       {sk}: {sv}")
        else:
            print(f"     {k}: {v}")

    # 执行清洗
    cleaned = cleaner.clean(df, stock_code=symbol)

    # 打印清洗报告
    cleaner.print_report()

    # 生成质量报告（清洗后）
    print("\n   ── 清洗后质量报告 ──")
    after_report = cleaner.quality_report(cleaned)
    print(f"     总行数: {after_report['总行数']}")
    print(f"     缺失值总数: {after_report['缺失值总数']}")
    print(f"     重复日期数: {after_report.get('重复日期数', 0)}")

    return df, cleaned


def test_dirty_data():
    """测试脏数据处理"""
    print("\n" + "=" * 60)
    print("          测试2: 脏数据处理")
    print("=" * 60)

    # 构造脏数据
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=100, freq="D")
    data = {
        "date": dates,
        "open": np.random.uniform(10, 11, 100).cumsum() % 5 + 10,
        "close": np.random.uniform(10, 11, 100).cumsum() % 5 + 10,
        "high": np.random.uniform(10, 12, 100).cumsum() % 5 + 11,
        "low": np.random.uniform(9, 10, 100).cumsum() % 5 + 9,
        "volume": np.random.randint(10000, 1000000, 100),
    }
    df = pd.DataFrame(data)
    df["symbol"] = "000001"

    # 注入问题
    df.loc[5, "close"] = np.nan  # 缺失值
    df.loc[10, "volume"] = 0     # 零成交
    df.loc[15, "close"] = -1     # 异常价格
    df.loc[20:22, "volume"] = 0  # 连续停牌
    df.loc[25, "high"] = 999     # 异常值

    # 插入重复日期
    dup_row = df.loc[30:31].copy()
    df = pd.concat([df, dup_row], ignore_index=True)

    print(f"   构造脏数据: {len(df)} 行 (含缺失值/零成交/异常价格/连续停牌/重复行)")

    cleaner = DataCleaner()

    # 清洗前质量报告
    print("\n   ── 清洗前质量报告 ──")
    for k, v in cleaner.quality_report(df).items():
        if isinstance(v, dict):
            print(f"     {k}:")
            for sk, sv in v.items():
                print(f"       {sk}: {sv}")
        else:
            print(f"     {k}: {v}")

    # 清洗
    cleaned = cleaner.clean(df, stock_code="TEST")

    # 清洗报告
    cleaner.print_report()

    # 验证
    assert len(cleaned) < len(df), "清洗后行数应减少"
    assert cleaned["close"].isnull().sum() == 0, "不应有缺失收盘价"
    assert (cleaned["close"] > 0).all(), "收盘价应全为正数"
    assert cleaned["volume"].isnull().sum() == 0, "不应有缺失成交量"

    print("   [OK] 所有断言通过")
    return df, cleaned


def test_batch_clean():
    """测试批量清洗"""
    print("\n" + "=" * 60)
    print("          测试3: 批量清洗")
    print("=" * 60)

    config = get_config()
    collector = DataCollector(raw_dir=config.data.raw_dir)
    cleaner = DataCleaner()

    # 加载多只股票
    symbols = ["000001", "600000", "600036"]
    data_dict = {}
    for sym in symbols:
        df = collector.load_from_parquet(sym)
        if not df.empty:
            data_dict[sym] = df
            print(f"   {sym}: {len(df)} 行")

    if not data_dict:
        print("   无本地数据，跳过测试")
        return

    # 批量清洗
    results = cleaner.clean_batch(data_dict)

    print(f"\n   批量清洗完成: {len(results)}/{len(symbols)} 只")
    for code, df in results.items():
        print(f"   {code}: {len(df)} 行")


def main():
    setup_logger()

    print("=" * 60)
    print("          数据清洗模块测试")
    print("=" * 60)

    test_basic_cleaning()
    test_dirty_data()
    test_batch_clean()

    print("\n" + "=" * 60)
    print("          所有测试完成！")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
