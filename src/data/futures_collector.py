"""
期货数据采集模块
数据源: AKShare (新浪/腾讯期货接口)
功能:
  1. 连续合约数据获取（主力合约拼接）
  2. 单个合约明细获取
  3. 主力合约识别（基于持仓量）
  4. 合约换月数据拼接（生成自定义连续合约）
  5. 本地Parquet缓存管理
"""
import time
import random
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import numpy as np
import akshare as ak
from loguru import logger


class FuturesContractHelper:
    """
    期货合约工具类
    
    处理合约代码解析、主力合约识别、换月拼接等
    """
    
    # 各交易所代码前缀
    EXCHANGE_MAP = {
        "shfe": "上海期货交易所",
        "dce": "大连商品交易所",
        "czce": "郑州商品交易所",
        "cffex": "中国金融期货交易所",
        "ine": "上海国际能源交易中心",
        "gfex": "广州期货交易所",
    }
    
    # 每个品种的交易时间（用于判断是否夜盘）
    NIGHT_SESSION_SYMBOLS = {
        "CU", "AL", "ZN", "PB", "NI", "SN", "AU", "AG", "RB", "HC",
        "RU", "BU", "FU", "SC", "NR", "LU", "BC",
        "M", "Y", "P", "L", "PP", "V", "EG", "EB", "PG", "RR", "B", "I", "JM", "J",
        "TA", "MA", "SR", "CF", "OI", "RM", "ZC", "FG",
    }

    @staticmethod
    def parse_symbol(symbol: str) -> dict:
        """
        解析期货合约代码
        
        Args:
            symbol: 合约代码 (如 RB2505, RB0, IF0)
            
        Returns:
            dict: {品种, 年份, 月份, 是否连续}
        """
        symbol = symbol.upper()
        
        if symbol.endswith("0"):
            # 连续合约: RB0, IF0, CU0
            base = symbol.rstrip("0")
            return {
                "base": base,
                "contract": symbol,
                "year": None,
                "month": None,
                "is_continuous": True,
            }
        
        # 单个合约: RB2505, IF2506
        base = symbol.rstrip("0123456789")
        num_part = symbol[len(base):]
        
        if len(num_part) == 4:
            year = int("20" + num_part[:2])
            month = int(num_part[2:])
        elif len(num_part) == 3:
            year = int("20" + num_part[0])
            month = int(num_part[1:])
        else:
            year = None
            month = None
        
        return {
            "base": base,
            "contract": symbol,
            "year": year,
            "month": month,
            "is_continuous": False,
        }

    @staticmethod
    def get_main_contract(symbol: str) -> pd.DataFrame:
        """
        获取全市场主力合约信息
        
        Returns:
            DataFrame: symbol, exchange, name
        """
        return ak.futures_display_main_sina()

    @staticmethod
    def list_all_contracts(base: str) -> pd.DataFrame:
        """
        获取某品种下所有合约信息
        
        Args:
            base: 品种代码 (如 RB, CU, IF)
            
        Returns:
            DataFrame: 包含合约代码、交易所、到期日等信息
        """
        try:
            df = ak.futures_comm_info()
            # 过滤品种前缀
            df = df[df["合约代码"].str.startswith(base)].reset_index(drop=True)
            return df
        except Exception as e:
            logger.error(f"获取{base}合约列表失败: {e}")
            return pd.DataFrame()


class FuturesDataCollector:
    """
    期货数据采集器
    
    支持:
    - 连续合约日线数据（新浪数据源）
    - 单个合约明细数据
    - 主力合约自动识别（基于持仓量）
    - 自定义换月拼接
    - 本地Parquet缓存
    """

    def __init__(self, raw_dir: str = "./data/futures/raw"):
        """
        初始化期货采集器
        
        Args:
            raw_dir: 数据存储目录
        """
        self.raw_dir = Path(raw_dir)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.helper = FuturesContractHelper()
        logger.info(f"期货数据采集器初始化, 存储目录: {self.raw_dir}")

    # ──────────────── 数据获取 ────────────────

    def get_continuous_daily(self, symbol: str) -> pd.DataFrame:
        """
        获取连续合约日线数据（新浪源）
        
        连续合约代码规则:
        - 品种代码 + '0' (如 RB0, IF0, CU0, SC0, P0)
        
        Args:
            symbol: 连续合约代码 (如 RB0, IF0)
            
        Returns:
            DataFrame: date, open, high, low, close, volume, hold(持仓量), settle(结算价)
        """
        try:
            df = ak.futures_zh_daily_sina(symbol=symbol)
            if df is not None and not df.empty:
                df["symbol"] = symbol
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date").reset_index(drop=True)
                logger.debug(f"[{symbol}] 连续合约数据: {len(df)} 条, "
                             f"{df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()}")
                return df
        except Exception as e:
            logger.warning(f"[{symbol}] 获取连续合约数据失败: {e}")
        
        return pd.DataFrame()

    def get_contract_daily(self, contract: str) -> pd.DataFrame:
        """
        获取单个合约的日线数据
        
        Args:
            contract: 具体合约代码 (如 RB2505, IF2506)
            
        Returns:
            DataFrame: date, open, high, low, close, volume, hold, settle
        """
        return self.get_continuous_daily(contract)

    def get_all_contracts_for_base(self, base: str,
                                    start_date: str = None,
                                    end_date: str = None) -> Dict[str, pd.DataFrame]:
        """
        获取某品种所有合约的日线数据（用于自定义换月拼接）
        
        Args:
            base: 品种代码 (如 RB, CU, IF)
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            {合约代码: DataFrame}
        """
        # 获取该品种所有合约信息
        contract_info = self.helper.list_all_contracts(base)
        if contract_info.empty:
            logger.warning(f"[{base}] 没有找到合约信息")
            return {}
        
        contracts = contract_info["合约代码"].tolist()
        logger.info(f"[{base}] 共找到 {len(contracts)} 个合约，开始获取明细数据...")
        
        results = {}
        for i, ct in enumerate(contracts, 1):
            try:
                df = self.get_contract_daily(ct)
                if not df.empty:
                    results[ct] = df
                if i % 20 == 0:
                    logger.info(f"[{base}] 进度: [{i}/{len(contracts)}] 已获取 {len(results)} 个合约")
                if i < len(contracts):
                    time.sleep(random.uniform(0.3, 0.8))
            except Exception as e:
                logger.warning(f"[{base}] {ct} 获取失败: {e}")
        
        logger.info(f"[{base}] 合约明细获取完成: {len(results)}/{len(contracts)}")
        return results

    def get_main_contract_series(self, base: str, lookback_days: int = 30) -> pd.DataFrame:
        """
        基于持仓量识别主力合约，生成主力合约序列
        
        方法: 滚动窗口内取持仓量最大的合约作为主力合约
        
        Args:
            base: 品种代码 (如 RB, CU)
            lookback_days: 判断主力的持仓量对比窗口（天）
            
        Returns:
            DataFrame: 包含每日期的主力合约、价格、持仓量等信息
        """
        parsed = self.helper.parse_symbol(f"{base}0")
        if parsed["is_continuous"]:
            # 直接使用新浪的连续合约数据
            df = self.get_continuous_daily(f"{base}0")
            if not df.empty:
                df["main_contract"] = df["symbol"]
                return df
        
        # 获取所有合约明细
        all_contracts = self.get_all_contracts_for_base(base)
        if not all_contracts:
            return pd.DataFrame()
        
        logger.info(f"[{base}] 正在识别主力合约序列 (窗口={lookback_days}天)...")
        
        # 合并所有合约数据
        combined = []
        for contract, df in all_contracts.items():
            if "hold" in df.columns and df["hold"].notna().any():
                # 只保留有持仓量的数据
                df_valid = df[df["hold"] > 0].copy()
                if not df_valid.empty:
                    df_valid["contract"] = contract
                    combined.append(df_valid)
        
        if not combined:
            logger.warning(f"[{base}] 没有合约有持仓量数据")
            return pd.DataFrame()
        
        all_data = pd.concat(combined, ignore_index=True)
        all_data = all_data.sort_values("date").reset_index(drop=True)
        
        # 逐日识别主力合约
        results = []
        for date, grp in all_data.groupby("date"):
            if grp.empty:
                continue
            
            # 按持仓量排序取最大
            top = grp.sort_values("hold", ascending=False)
            main = top.iloc[0]
            
            results.append({
                "date": date,
                "main_contract": main["contract"],
                "open": main["open"],
                "high": main["high"],
                "low": main["low"],
                "close": main["close"],
                "volume": main["volume"],
                "hold": main["hold"],
                "settle": main.get("settle", 0),
                "symbol": f"{base}0",
            })
        
        result_df = pd.DataFrame(results)
        result_df = result_df.sort_values("date").reset_index(drop=True)
        logger.success(f"[{base}] 主力合约序列识别完成: {len(result_df)} 条, "
                       f"{result_df['date'].iloc[0].date()} ~ {result_df['date'].iloc[-1].date()}")
        return result_df

    # ──────────────── 换月拼接 ────────────────

    def _detect_roll_points_via_all_contracts(self, base: str) -> pd.DataFrame:
        """
        通过获取各合约明细，基于持仓量识别换月点（更精确的方法）
        
        Returns:
            DataFrame: 主力合约序列（含具体合约名），每行含换月标记
        """
        # 获取所有合约明细
        all_contracts = self.get_all_contracts_for_base(base)
        if not all_contracts:
            return pd.DataFrame()
        
        # 合并所有合约数据
        combined = []
        for contract, df in all_contracts.items():
            if "hold" in df.columns and df["hold"].notna().any():
                df_valid = df[df["hold"] > 0].copy()
                if not df_valid.empty:
                    df_valid["contract"] = contract
                    combined.append(df_valid)
        
        if not combined:
            return pd.DataFrame()
        
        all_data = pd.concat(combined, ignore_index=True)
        all_data = all_data.sort_values("date").reset_index(drop=True)
        
        # 逐日识别主力合约
        results = []
        prev_contract = None
        for date, grp in all_data.groupby("date"):
            if grp.empty:
                continue
            top = grp.sort_values("hold", ascending=False)
            main = top.iloc[0]
            contract_name = main["contract"]
            
            is_roll = (prev_contract is not None and contract_name != prev_contract)
            
            results.append({
                "date": date,
                "main_contract": contract_name,
                "open": main["open"],
                "high": main["high"],
                "low": main["low"],
                "close": main["close"],
                "volume": main["volume"],
                "hold": main["hold"],
                "settle": main.get("settle", 0),
                "symbol": f"{base}0",
                "is_roll_date": is_roll,
                "prev_contract": prev_contract or contract_name,
            })
            prev_contract = contract_name
        
        result_df = pd.DataFrame(results)
        result_df = result_df.sort_values("date").reset_index(drop=True)
        roll_count = result_df["is_roll_date"].sum()
        logger.info(f"[{base}] 通过逐合约识别: {len(result_df)} 条, 换月点 {roll_count} 个")
        return result_df

    def build_continuous_series(self, base: str,
                                roll_method: str = "open_adj",
                                use_all_contracts: bool = False) -> pd.DataFrame:
        """
        构建自定义的连续合约序列（处理换月跳空）
        
        Args:
            base: 品种代码 (如 RB, CU, IF)
            roll_method: 换月处理方式
                - "open_adj": 价差调整（默认，消除跳空）
                - "ratio_adj": 比例调整
                - "no_adj": 不调整
            use_all_contracts: 如果True，通过获取所有合约明细来精确识别换月
                              如果False（默认），使用新浪连续合约的主力持仓量判断
            
        Returns:
            DataFrame: 连续合约序列
        """
        logger.info(f"[{base}] 开始构建连续合约序列 (换月方法={roll_method})...")
        
        if use_all_contracts:
            # 精确方法：获取各合约明细识别换月
            main_series = self._detect_roll_points_via_all_contracts(base)
            if main_series.empty:
                logger.warning(f"[{base}] 逐合约识别失败，回退到连续合约法")
                main_series = self.get_main_contract_series(base)
                if main_series.empty:
                    return pd.DataFrame()
                main_series["is_roll_date"] = False
                main_series["prev_contract"] = main_series["main_contract"]
        else:
            # 简易方法：使用新浪连续合约中的持仓量变化判断换月
            main_series = self.get_main_contract_series(base)
            if main_series.empty:
                return pd.DataFrame()
            
            # 用持仓量变化检测换月：持仓量骤降后回升 => 换月
            main_series["hold_change"] = main_series["hold"].pct_change()
            # 换月特征：持仓量单日下降 > 20% 且 次日持仓量回升
            main_series["hold_drop_sharp"] = main_series["hold_change"] < -0.20
            # 取这些点作为换月点
            roll_idx = main_series[main_series["hold_drop_sharp"]].index
            main_series["is_roll_date"] = False
            if len(roll_idx) > 0:
                main_series.loc[roll_idx, "is_roll_date"] = True
            main_series["prev_contract"] = main_series["main_contract"]
            logger.info(f"[{base}] 持仓量换月检测: {len(roll_idx)} 个候选点")
        
        roll_points = main_series[main_series["is_roll_date"]].index
        roll_count = len(roll_points)
        
        if roll_count == 0:
            logger.info(f"[{base}] 没有发现换月点，返回原始序列")
            if "is_roll_date" not in main_series.columns:
                main_series["is_roll_date"] = False
            if "adjustment" not in main_series.columns:
                main_series["adjustment"] = 0.0
            return main_series
        
        logger.info(f"[{base}] 发现 {roll_count} 个换月点")
        
        # 价差调整法
        if roll_method == "open_adj":
            cum_adj = 0.0
            adj_prices = []
            
            for idx, row in main_series.iterrows():
                if idx in roll_points:
                    old_close = main_series.loc[idx - 1, "close"]
                    new_open = row["open"]
                    roll_gap = new_open - old_close
                    cum_adj -= roll_gap
                
                adj_prices.append({
                    "date": row["date"],
                    "open": row["open"] + cum_adj,
                    "high": row["high"] + cum_adj,
                    "low": row["low"] + cum_adj,
                    "close": row["close"] + cum_adj,
                    "volume": row["volume"],
                    "hold": row["hold"],
                    "settle": row["settle"] + cum_adj if row["settle"] != 0 else 0,
                    "main_contract": row["main_contract"],
                    "symbol": f"{base}0",
                    "adjustment": cum_adj,
                    "is_roll_date": idx in roll_points,
                })
            
            result_df = pd.DataFrame(adj_prices)
            logger.success(f"[{base}] 连续合约构建完成: {len(result_df)} 条")
            return result_df
        
        # 不调整
        if roll_method == "no_adj":
            main_series["adjustment"] = 0.0
            return main_series
        
        logger.warning(f"[{base}] 未知换月方法: {roll_method}, 返回原始序列")
        main_series["adjustment"] = 0.0
        return main_series
    
    # ──────────────── 缓存管理 ────────────────
    
    def save_to_cache(self, df: pd.DataFrame, name: str):
        """保存到本地缓存"""
        file_path = self.raw_dir / f"{name}.parquet"
        df.to_parquet(file_path, index=False)
        logger.debug(f"[{name}] 已缓存到 {file_path}")
    
    def load_from_cache(self, name: str) -> pd.DataFrame:
        """从本地缓存加载"""
        file_path = self.raw_dir / f"{name}.parquet"
        if file_path.exists():
            try:
                df = pd.read_parquet(file_path)
                logger.debug(f"[{name}] 从缓存加载: {len(df)} 条")
                return df
            except Exception as e:
                logger.warning(f"[{name}] 缓存读取失败: {e}")
        return pd.DataFrame()
    
    def get_cache_info(self) -> Dict[str, dict]:
        """查看所有缓存信息"""
        info = {}
        for f in self.raw_dir.glob("*.parquet"):
            try:
                df = pd.read_parquet(f)
                info[f.stem] = {
                    "rows": len(df),
                    "size_kb": round(f.stat().st_size / 1024, 1),
                    "columns": list(df.columns),
                    "date_range": (
                        f"{df['date'].min().date()} ~ {df['date'].max().date()}"
                        if "date" in df.columns else "N/A"
                    ),
                }
            except Exception:
                pass
        return info
    
    # ──────────────── 品种信息 ────────────────
    
    def get_product_info(self, base: str) -> dict:
        """
        获取品种基础信息（合约乘数、最小变动价位、交易时间等）
        
        Args:
            base: 品种代码
            
        Returns:
            dict: 品种信息
        """
        try:
            # 从期货合约信息中提取
            df = ak.futures_comm_info()
            product_df = df[df["合约代码"].str.startswith(base)]
            if not product_df.empty:
                row = product_df.iloc[0]
                return {
                    "base": base,
                    "name": row.get("合约名称", ""),
                    "exchange": row.get("交易所名称", ""),
                    "margin_buy": row.get("保证金-买开", 0),
                    "margin_sell": row.get("保证金-卖开", 0),
                    "commission_open_pct": row.get("手续费标准-开仓-万分之", 0),
                    "commission_open_fix": row.get("手续费标准-开仓-元", 0),
                    "commission_today_pct": row.get("手续费标准-平今-万分之", 0),
                    "commission_today_fix": row.get("手续费标准-平今-元", 0),
                    "price_tick": row.get("每跳毛利", 0),
                }
        except Exception as e:
            logger.warning(f"[{base}] 获取品种信息失败: {e}")
        
        return {"base": base}


# ──────────────── 便捷函数 ────────────────

def get_futures_daily(symbol: str) -> pd.DataFrame:
    """
    快捷获取期货日线数据
    
    Args:
        symbol: 合约代码 (RB0, IF0, RB2505 等)
    
    Returns:
        DataFrame
    """
    collector = FuturesDataCollector()
    return collector.get_continuous_daily(symbol)


def list_main_contracts() -> pd.DataFrame:
    """获取全市场主力合约列表"""
    return FuturesContractHelper.get_main_contract("")
