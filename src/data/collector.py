"""
数据采集模块
使用AKShare采集A股数据
数据源: 腾讯证券 (stock_zh_a_hist_tx) - 备用连接
备用源: 新浪财经 (stock_zh_a_daily)
支持自动重试、熔断、限速、本地缓存
"""
import time
import random
from typing import List, Callable
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import akshare as ak
from loguru import logger


_CITY_MAP = {"sh": "1", "sz": "0"}


class CircuitBreaker:
    """熔断器 - 防止频繁重试失败接口"""

    def __init__(self, name: str, max_failures: int = 3, reset_seconds: int = 60):
        self.name = name
        self.max_failures = max_failures
        self.reset_seconds = reset_seconds
        self._fail_count = 0
        self._last_fail_time = None
        self._state = "closed"

    def record_success(self):
        self._fail_count = 0
        if self._state == "half_open":
            logger.info(f"[熔断器:{self.name}] 半开状态测试成功，恢复关闭")
        self._state = "closed"

    def record_failure(self):
        self._fail_count += 1
        self._last_fail_time = datetime.now()
        if self._fail_count >= self.max_failures:
            self._state = "open"
            logger.warning(f"[熔断器:{self.name}] 触发熔断! 失败{self._fail_count}次，熔断{self.reset_seconds}秒")

    def can_try(self) -> bool:
        if self._state == "closed":
            return True
        if self._state == "open":
            elapsed = (datetime.now() - self._last_fail_time).total_seconds()
            if elapsed >= self.reset_seconds:
                self._state = "half_open"
                logger.info(f"[熔断器:{self.name}] 熔断已过{elapsed:.0f}秒，进入半开")
                return True
            return False
        return True

    def __str__(self):
        return f"[{self.name}] state={self._state}, fail={self._fail_count}/{self.max_failures}"


class RateLimiter:
    """请求限速器"""

    def __init__(self, min_interval: float = 1.0):
        self.min_interval = min_interval
        self._last_call_time = 0

    def wait(self):
        now = time.time()
        elapsed = now - self._last_call_time
        if elapsed < self.min_interval:
            wait_time = self.min_interval - elapsed + random.uniform(0, 0.3)
            time.sleep(wait_time)
        self._last_call_time = time.time()


def _symbol_to_market(symbol: str) -> str:
    """将纯数字代码转为带市场前缀的格式
    000001 -> sz000001 (深交所)
    600000 -> sh600001 (上交所)
    """
    symbol = symbol.strip()
    if symbol.startswith(("sh", "sz", "bj")):
        return symbol
    code_num = int(symbol[:3])
    if code_num >= 600:
        return f"sh{symbol}"
    elif code_num >= 200:
        return f"sz{symbol}"
    elif code_num < 200:
        return f"sz{symbol}"
    return f"sz{symbol}"


class DataCollector:
    """A股数据采集器 - 数据源: 腾讯证券"""

    def __init__(self, raw_dir: str = "./data/raw"):
        self.raw_dir = Path(raw_dir)
        self.raw_dir.mkdir(parents=True, exist_ok=True)

        self._circuit_breakers = {
            "stock_list": CircuitBreaker("股票列表"),
            "stock_history": CircuitBreaker("历史数据"),
            "index_history": CircuitBreaker("指数数据"),
            "realtime": CircuitBreaker("实时行情"),
        }
        self._rate_limiter = RateLimiter(min_interval=1.0)
        logger.info(f"数据采集器初始化完成, 数据目录: {self.raw_dir}")
        logger.info(f"数据源: 腾讯证券 (stock_zh_a_hist_tx)")

    def _request(self, cb_name: str, func: Callable, *args, max_retries: int = 2, **kwargs):
        """带熔断和重试的请求包装，指数退避 + 随机抖动"""
        cb = self._circuit_breakers.get(cb_name)

        for attempt in range(1, max_retries + 1):
            if not cb.can_try():
                logger.warning(f"[{cb_name}] 熔断中，跳过请求")
                return None

            self._rate_limiter.wait()

            try:
                result = func(*args, **kwargs)
                cb.record_success()
                return result
            except Exception as e:
                cb.record_failure()
                if attempt < max_retries and cb.can_try():
                    wait_time = (2 ** (attempt - 1)) + random.uniform(0, 1)
                    logger.warning(
                        f"[{cb_name}] 第{attempt}/{max_retries}次失败: {e}. 等待{wait_time:.1f}秒后重试..."
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(f"[{cb_name}] 重试{attempt}次后放弃: {e}")
                    return None
        return None

    def get_stock_list(self) -> pd.DataFrame:
        """获取A股股票列表（通过 stock_info_a_code_name 备用源）"""
        logger.info("正在获取A股股票列表...")

        result = self._request("stock_list", ak.stock_info_a_code_name)
        if result is not None and not result.empty:
            result = result.rename(columns={"code": "代码", "name": "名称"})
            logger.success(f"成功获取 {len(result)} 只股票")
            return result

        logger.error("获取股票列表失败!")
        return pd.DataFrame()

    def get_stock_history(self, symbol: str, start_date: str = None,
                          end_date: str = None, adjust: str = "qfq") -> pd.DataFrame:
        """
        获取单只股票历史数据
        主源: 腾讯证券 stock_zh_a_hist_tx
        备用源: 新浪财经 stock_zh_a_daily
        """
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=365 * 3)).strftime("%Y%m%d")
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")

        # 检查本地缓存
        cached = self.load_from_parquet(symbol)
        if not cached.empty:
            last_date = cached["date"].max()
            cache_days = (datetime.now() - pd.Timestamp(last_date).to_pydatetime()).days
            if cache_days <= 1:
                logger.debug(f"[{symbol}] 使用本地缓存 (最后更新: {last_date.date()})")
                return cached

        # 转市场前缀
        market_symbol = _symbol_to_market(symbol)

        def _normalize_tx(df):
            """腾讯数据列归一化"""
            if df is None or df.empty:
                return df
            df = df.rename(columns={
                "date": "date", "open": "open", "close": "close",
                "high": "high", "low": "low", "volume": "volume", "amount": "amount",
            })
            df["symbol"] = symbol
            df["date"] = pd.to_datetime(df["date"])
            return df

        def _normalize_sina(df):
            """新浪数据列归一化"""
            if df is None or df.empty:
                return df
            # 新浪返回的列是 date, open, high, low, close, volume, amount
            col_map = {
                "date": "date", "open": "open", "close": "close",
                "high": "high", "low": "low",
            }
            df = df.rename(columns=col_map)
            df["symbol"] = symbol
            df["date"] = pd.to_datetime(df["date"])
            return df

        def _fetch_tx():
            df = ak.stock_zh_a_hist_tx(
                symbol=market_symbol,
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
            )
            return _normalize_tx(df)

        def _fetch_sina():
            df = ak.stock_zh_a_daily(
                symbol=market_symbol,
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
            )
            return _normalize_sina(df)

        logger.info(f"正在获取 {symbol}({market_symbol}) 历史数据 [{start_date} -> {end_date}]...")

        # 主源: 腾讯
        df = self._request("stock_history", _fetch_tx)
        if df is not None and not df.empty:
            logger.success(f"[{symbol}] 腾讯源成功: {len(df)} 条")
            self._save_to_parquet(df, symbol)
            return df

        # 备用源: 新浪
        logger.info(f"[{symbol}] 腾讯源失败，尝试新浪财经...")
        time.sleep(1)
        df = self._request("stock_history", _fetch_sina)
        if df is not None and not df.empty:
            logger.success(f"[{symbol}] 新浪源成功: {len(df)} 条")
            self._save_to_parquet(df, symbol)
            return df

        # 返回本地缓存
        if not cached.empty:
            logger.warning(f"[{symbol}] 网络请求失败，返回本地缓存 ({len(cached)} 条)")
            return cached
        return pd.DataFrame()

    def get_stock_history_batch(self, symbols: List[str], start_date: str = None,
                                end_date: str = None, save: bool = True) -> dict:
        """批量获取（带限速）"""
        results = {}
        total = len(symbols)
        logger.info(f"开始批量获取 {total} 只股票数据...")

        for i, symbol in enumerate(symbols, 1):
            df = self.get_stock_history(symbol, start_date, end_date)
            if not df.empty:
                results[symbol] = df
                if save:
                    self._save_to_parquet(df, symbol)
            if i % 10 == 0:
                logger.info(f"批量进度: [{i}/{total}] 成功 {len(results)}")
            if i < total:
                time.sleep(random.uniform(1.0, 1.5))

        logger.success(f"批量获取完成，成功 {len(results)}/{total}")
        return results

    def _save_to_parquet(self, df: pd.DataFrame, symbol: str):
        file_path = self.raw_dir / f"{symbol}.parquet"
        df.to_parquet(file_path, index=False)
        logger.debug(f"[{symbol}] 已保存到 {file_path}")

    def load_from_parquet(self, symbol: str) -> pd.DataFrame:
        file_path = self.raw_dir / f"{symbol}.parquet"
        if file_path.exists():
            return pd.read_parquet(file_path)
        return pd.DataFrame()

    def get_index_history(self, index_code: str = "000001",
                          start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """获取指数历史数据（使用腾讯或新浪）"""
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=365 * 5)).strftime("%Y%m%d")
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")

        mkt_symbol = _symbol_to_market(index_code)

        def _fetch():
            df = ak.stock_zh_a_hist_tx(
                symbol=mkt_symbol,
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            )
            if df is not None and not df.empty:
                df["symbol"] = index_code
                df["date"] = pd.to_datetime(df["date"])
            return df

        logger.info(f"正在获取指数 {index_code} 数据...")
        df = self._request("index_history", _fetch)
        if df is not None and not df.empty:
            logger.success(f"指数 {index_code}: {len(df)} 条")
        return df if df is not None else pd.DataFrame()

    def get_realtime_quote(self, symbols: List[str] = None) -> pd.DataFrame:
        """获取实时行情（从东方财富备用源 stock_info_a_code_name 仅获取列表信息）"""
        logger.info("实时行情接口暂不可用（东方财富连接受限）")
        return pd.DataFrame()

    def get_cache_info(self) -> dict:
        info = {}
        for f in self.raw_dir.glob("*.parquet"):
            try:
                df = pd.read_parquet(f)
                info[f.stem] = {
                    "rows": len(df),
                    "size_kb": round(f.stat().st_size / 1024, 1),
                    "last_date": str(df["date"].max()) if "date" in df.columns else "N/A",
                }
            except:
                pass
        return info
