"""
数据采集模块
使用AKShare采集A股数据
"""
from typing import List, Optional
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import akshare as ak
from loguru import logger


class DataCollector:
    """A股数据采集器"""
    
    def __init__(self, raw_dir: str = "./data/raw"):
        """
        初始化数据采集器
        
        Args:
            raw_dir: 原始数据存储目录
        """
        self.raw_dir = Path(raw_dir)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"数据采集器初始化完成，数据目录: {self.raw_dir}")
        
    def get_stock_list(self) -> pd.DataFrame:
        """
        获取A股股票列表
        
        Returns:
            包含股票代码、名称等信息的DataFrame
        """
        logger.info("正在获取A股股票列表...")
        try:
            df = ak.stock_zh_a_spot_em()
            logger.info(f"成功获取 {len(df)} 只股票")
            return df
        except Exception as e:
            logger.error(f"获取股票列表失败: {e}")
            raise
    
    def get_stock_history(
        self,
        symbol: str,
        start_date: str = None,
        end_date: str = None,
        adjust: str = "qfq"
    ) -> pd.DataFrame:
        """
        获取单只股票历史数据
        
        Args:
            symbol: 股票代码 (如 "000001")
            start_date: 开始日期 (如 "20200101")
            end_date: 结束日期 (如 "20231231")
            adjust: 复权类型 qfq-前复权 hfq-后复权 None-不复权
            
        Returns:
            包含日期、开盘价、收盘价等信息的DataFrame
        """
        logger.info(f"正在获取 {symbol} 历史数据...")
        
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=365*3)).strftime("%Y%m%d")
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")
            
        try:
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
            )
            # 重命名列
            df.columns = ['date', 'open', 'close', 'high', 'low', 'volume', 'amount', 'amplitude', 'pct_change', 'change', 'turnover']
            df['symbol'] = symbol
            df['date'] = pd.to_datetime(df['date'])
            
            logger.info(f"成功获取 {symbol} 数据 {len(df)} 条")
            return df
        except Exception as e:
            logger.error(f"获取 {symbol} 数据失败: {e}")
            return pd.DataFrame()
    
    def get_stock_history_batch(
        self,
        symbols: List[str],
        start_date: str = None,
        end_date: str = None,
        save: bool = True,
    ) -> dict:
        """
        批量获取股票历史数据
        
        Args:
            symbols: 股票代码列表
            start_date: 开始日期
            end_date: 结束日期
            save: 是否保存到文件
            
        Returns:
            字典，key为股票代码，value为DataFrame
        """
        results = {}
        total = len(symbols)
        
        logger.info(f"开始批量获取 {total} 只股票数据...")
        
        for i, symbol in enumerate(symbols, 1):
            logger.info(f"进度: [{i}/{total}] 正在获取 {symbol}")
            
            df = self.get_stock_history(symbol, start_date, end_date)
            if not df.empty:
                results[symbol] = df
                
                if save:
                    self._save_to_parquet(df, symbol)
        
        logger.success(f"批量获取完成，成功 {len(results)}/{total}")
        return results
    
    def _save_to_parquet(self, df: pd.DataFrame, symbol: str):
        """保存为Parquet格式"""
        file_path = self.raw_dir / f"{symbol}.parquet"
        df.to_parquet(file_path, index=False)
        logger.debug(f"数据已保存到 {file_path}")
    
    def load_from_parquet(self, symbol: str) -> pd.DataFrame:
        """从Parquet加载数据"""
        file_path = self.raw_dir / f"{symbol}.parquet"
        if file_path.exists():
            return pd.read_parquet(file_path)
        logger.warning(f"文件不存在: {file_path}")
        return pd.DataFrame()
    
    def get_index_history(
        self,
        index_code: str = "000001",
        start_date: str = None,
        end_date: str = None,
    ) -> pd.DataFrame:
        """
        获取指数历史数据
        
        Args:
            index_code: 指数代码 (000001-上证指数, 399001-深证成指, 399006-创业板指)
            start_date: 开始日期
            end_date: 结束日期
        """
        logger.info(f"正在获取指数 {index_code} 历史数据...")
        
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=365*5)).strftime("%Y%m%d")
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")
            
        try:
            df = ak.index_zh_a_hist(
                symbol=index_code,
                period="daily",
                start_date=start_date,
                end_date=end_date,
            )
            df.columns = ['date', 'open', 'close', 'high', 'low', 'volume', 'amount']
            df['date'] = pd.to_datetime(df['date'])
            
            logger.info(f"成功获取指数数据 {len(df)} 条")
            return df
        except Exception as e:
            logger.error(f"获取指数数据失败: {e}")
            return pd.DataFrame()
    
    def get_realtime_quote(self, symbols: List[str] = None) -> pd.DataFrame:
        """
        获取实时行情
        
        Args:
            symbols: 股票代码列表，为None时获取全部
        """
        logger.info("正在获取实时行情...")
        try:
            df = ak.stock_zh_a_spot_em()
            if symbols:
                df = df[df['代码'].isin(symbols)]
            logger.info(f"获取实时行情 {len(df)} 条")
            return df
        except Exception as e:
            logger.error(f"获取实时行情失败: {e}")
            return pd.DataFrame()
