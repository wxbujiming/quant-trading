"""
数据采集脚本
用法: python scripts/collect_data.py
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.logger import setup_logger
from src.core.config import get_config
from src.data.collector import DataCollector
from loguru import logger


def main():
    # 初始化
    setup_logger()
    config = get_config()
    
    print("\n" + "=" * 60)
    print("           A股数据采集工具")
    print("=" * 60)
    
    # 创建采集器
    collector = DataCollector(raw_dir=config.data.raw_dir)
    
    # 1. 获取股票列表
    print("\n[1/3] 获取股票列表...")
    stock_list = collector.get_stock_list()
    print(f"   共获取 {len(stock_list)} 只股票")
    
    # 2. 选择要采集的股票 (示例：采集上证50成分股前10只)
    print("\n[2/3] 选择股票...")
    # 可以自定义股票列表
    symbols = ["000001", "600000", "600036", "600519", "601318", 
               "601398", "601939", "600276", "601166", "600887"]
    print(f"   将采集股票: {symbols}")
    
    # 3. 批量采集历史数据
    print("\n[3/3] 开始批量采集...")
    results = collector.get_stock_history_batch(
        symbols=symbols,
        start_date="20220101",
        end_date="20241231",
        save=True,
    )
    
    # 4. 获取指数数据
    print("\n[补充] 获取主要指数...")
    indices = [
        ("000001", "上证指数"),
        ("399001", "深证成指"),
        ("399006", "创业板指"),
    ]
    
    for code, name in indices:
        df = collector.get_index_history(code)
        if not df.empty:
            file_path = Path(config.data.raw_dir) / f"index_{code}.parquet"
            df.to_parquet(file_path, index=False)
            print(f"   {name}({code}): {len(df)} 条")
    
    # 打印结果
    print("\n" + "=" * 60)
    print("数据采集完成！")
    print(f"数据目录: {config.data.raw_dir}")
    print(f"成功采集: {len(results)} 只股票")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
