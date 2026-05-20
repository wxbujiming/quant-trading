"""
价差数据合成模块

将两个合约的日线数据对齐并计算价差序列，支持：
- 价格差 (price_diff)
- 对数收益率差 (log_return_diff)
- 价格比 (ratio)
- 滚动 z-score 和布林带
- 滚动 OLS 对冲比
"""
from typing import Dict, Optional, Tuple
import pandas as pd
import numpy as np
from loguru import logger


class SpreadBuilder:
    """
    价差数据合成器

    将两个合约的 DataFrame 对齐、计算价差序列，
    输出包含 leg1/leg2 价格 + 价差 + z-score + 布林带的统一 DataFrame。

    Usage:
        builder = SpreadBuilder(leg1_df, leg2_df)
        spread_df = builder.build(method="price_diff", zscore_window=20)
    """

    # 需要从输入 DataFrame 中保留的 OHLCV 列
    PRICE_COLUMNS = ["open", "high", "low", "close", "settle", "volume", "hold"]

    def __init__(self, leg1_df: pd.DataFrame, leg2_df: pd.DataFrame):
        """
        Args:
            leg1_df: 腿1 的日线数据，需含 date,open,high,low,close,settle,volume,hold
            leg2_df: 腿2 的日线数据，同上
        """
        self._leg1_raw = leg1_df.copy()
        self._leg2_raw = leg2_df.copy()
        self._aligned: Optional[pd.DataFrame] = None

    # ──────────────── 数据对齐 ────────────────

    def align_data(self, date_col: str = "date") -> pd.DataFrame:
        """
        将两个 DataFrame 按日期做 inner join，
        列名加上 leg1_ / leg2_ 前缀。

        Args:
            date_col: 日期列名

        Returns:
            对齐后的 DataFrame, index=date
        """
        df1, df2 = self._leg1_raw.copy(), self._leg2_raw.copy()

        # 确保 date 列是 datetime 并设为 index
        for df in (df1, df2):
            if date_col in df.columns:
                df[date_col] = pd.to_datetime(df[date_col])
                df.set_index(date_col, inplace=True)
            elif not isinstance(df.index, pd.DatetimeIndex):
                raise ValueError(f"DataFrame 必须包含 '{date_col}' 列或 DatetimeIndex")

        # 只保留价格列
        cols = [c for c in self.PRICE_COLUMNS if c in df1.columns]
        df1 = df1[cols]
        cols = [c for c in self.PRICE_COLUMNS if c in df2.columns]
        df2 = df2[cols]

        # 列重命名
        df1 = df1.rename(columns=lambda c: f"leg1_{c}")
        df2 = df2.rename(columns=lambda c: f"leg2_{c}")

        # inner join
        aligned = df1.join(df2, how="inner")
        aligned.sort_index(inplace=True)
        aligned.index.name = "date"

        # 检查空值
        n_before = len(aligned)
        aligned = aligned.dropna()
        n_dropped = n_before - len(aligned)
        if n_dropped > 0:
            logger.warning(f"对齐后丢弃 {n_dropped} 行包含 NaN 的数据")

        if aligned.empty:
            raise ValueError("对齐后数据为空，两个合约可能没有重叠的交易日")

        self._aligned = aligned
        logger.info(f"数据对齐完成: {len(aligned)} 行, "
                    f"{aligned.index[0].date()} ~ {aligned.index[-1].date()}")
        return aligned

    # ──────────────── 价差计算 ────────────────

    def compute_spread(self, method: str = "price_diff",
                       hedge_ratio: Optional[float] = None) -> pd.DataFrame:
        """
        计算价差序列。

        Args:
            method: 计算方法
                - "price_diff": leg1_close - leg2_close * hedge_ratio
                - "log_return_diff": ln(leg1_close) - ln(leg2_close) * hedge_ratio
                - "ratio": leg1_close / leg2_close
            hedge_ratio: 对冲比。None 默认为 1.0

        Returns:
            含 spread 列的 DataFrame
        """
        if self._aligned is None:
            raise RuntimeError("请先调用 align_data()")

        df = self._aligned.copy()
        hr = hedge_ratio if hedge_ratio is not None else 1.0

        if method == "price_diff":
            df["spread"] = df["leg1_close"] - df["leg2_close"] * hr
        elif method == "log_return_diff":
            df["spread"] = np.log(df["leg1_close"]) - np.log(df["leg2_close"]) * hr
        elif method == "ratio":
            df["spread"] = df["leg1_close"] / df["leg2_close"]
        else:
            raise ValueError(f"未知价差计算方法: {method}，支持 price_diff/log_return_diff/ratio")

        df["hedge_ratio"] = hr
        self._aligned = df
        logger.debug(f"价差计算完成: method={method}, hedge_ratio={hr:.4f}")
        return df

    # ──────────────── Z-Score ────────────────

    def compute_zscore(self, window: int = 20) -> pd.DataFrame:
        """
        计算价差的滚动 z-score。

        zscore = (spread - rolling_mean) / rolling_std

        Args:
            window: 滚动窗口

        Returns:
            含 zscore / spread_ma / spread_std 列的 DataFrame
        """
        if self._aligned is None or "spread" not in self._aligned.columns:
            raise RuntimeError("请先调用 compute_spread()")

        df = self._aligned.copy()
        df["spread_ma"] = df["spread"].rolling(window=window).mean()
        df["spread_std"] = df["spread"].rolling(window=window).std()
        df["zscore"] = (df["spread"] - df["spread_ma"]) / df["spread_std"].replace(0, np.nan)

        self._aligned = df
        logger.debug(f"Z-score 计算完成: window={window}")
        return df

    # ──────────────── 布林带 ────────────────

    def compute_bollinger_bands(self, window: int = 20,
                                num_std: float = 2.0) -> pd.DataFrame:
        """
        计算价差的布林带。

        Args:
            window: 滚动窗口
            num_std: 标准差倍数

        Returns:
            含 bb_upper / bb_middle / bb_lower 列的 DataFrame
        """
        if self._aligned is None or "spread" not in self._aligned.columns:
            raise RuntimeError("请先调用 compute_spread()")

        df = self._aligned.copy()
        df["bb_middle"] = df["spread"].rolling(window=window).mean()
        rolling_std = df["spread"].rolling(window=window).std()
        df["bb_upper"] = df["bb_middle"] + num_std * rolling_std
        df["bb_lower"] = df["bb_middle"] - num_std * rolling_std

        self._aligned = df
        logger.debug(f"布林带计算完成: window={window}, num_std={num_std}")
        return df

    # ──────────────── 滚动对冲比 ────────────────

    def compute_hedge_ratio_rolling(self, window: int = 60) -> pd.DataFrame:
        """
        滚动 OLS 回归计算动态对冲比 (leg1_close ~ leg2_close)。

        使用 numpy.polyfit 在每个窗口回归，更新 spread 和 z-score。

        Args:
            window: 回归窗口

        Returns:
            含 hedge_ratio 列的 DataFrame
        """
        if self._aligned is None:
            raise RuntimeError("请先调用 align_data()")

        df = self._aligned.copy()

        # 滚动回归
        def _rolling_beta(s: pd.Series) -> float:
            y = df.loc[s.index, "leg1_close"]
            x = df.loc[s.index, "leg2_close"]
            if len(x) < 5 or x.std() < 1e-10:
                return 1.0
            coeffs = np.polyfit(x, y, 1)
            return coeffs[0]  # 斜率

        df["hedge_ratio"] = np.nan
        for i in range(window, len(df) + 1):
            idx_slice = df.index[i - window:i]
            hr = _rolling_beta(df.loc[idx_slice])
            df.loc[idx_slice[-1], "hedge_ratio"] = hr

        # 前 window 个值用全局回归填充
        valid_mask = df["hedge_ratio"].notna()
        if valid_mask.any():
            fill_val = df.loc[valid_mask, "hedge_ratio"].iloc[0]
            df["hedge_ratio"] = df["hedge_ratio"].ffill().bfill()
        else:
            df["hedge_ratio"] = 1.0

        # 用动态对冲比重新计算 spread
        df["spread"] = df["leg1_close"] - df["leg2_close"] * df["hedge_ratio"]

        # 同时更新 z-score 和布林带（需要它们时再调用对应方法）
        # 这里只标记更新，不自动重算

        n_changed = len(df)
        self._aligned = df
        hr_range = (df["hedge_ratio"].min(), df["hedge_ratio"].max())
        logger.info(f"滚动对冲比计算完成: window={window}, "
                    f"范围=[{hr_range[0]:.4f}, {hr_range[1]:.4f}]")
        return df

    # ──────────────── 便捷方法 ────────────────

    def build(self, method: str = "price_diff",
              zscore_window: int = 20,
              bb_window: int = 20,
              bb_num_std: float = 2.0,
              hedge_ratio: Optional[float] = None) -> pd.DataFrame:
        """
        一键构建：对齐 → 价差 → z-score → 布林带。

        Args:
            method: 价差计算方法
            zscore_window: Z-score 窗口
            bb_window: 布林带窗口
            bb_num_std: 布林带标准差倍数
            hedge_ratio: 对冲比（None=1.0）

        Returns:
            完整价差 DataFrame
        """
        self.align_data()
        self.compute_spread(method=method, hedge_ratio=hedge_ratio)
        self.compute_zscore(window=zscore_window)
        self.compute_bollinger_bands(window=bb_window, num_std=bb_num_std)

        n_cols = len(self._aligned.columns)
        logger.info(f"价差数据构建完成: {len(self._aligned)} 行, {n_cols} 列")
        return self._aligned

    # ──────────────── 工具方法 ────────────────

    def get_spread_df(self) -> pd.DataFrame:
        """获取构建完成的数据"""
        if self._aligned is None:
            raise RuntimeError("尚未构建价差数据，请先调用 build()")
        return self._aligned.copy()

    def get_spread_stats(self) -> Dict[str, float]:
        """获取价差描述统计"""
        if self._aligned is None or "spread" not in self._aligned.columns:
            return {}
        s = self._aligned["spread"].dropna()
        return {
            "mean": float(s.mean()),
            "std": float(s.std()),
            "min": float(s.min()),
            "max": float(s.max()),
            "current": float(s.iloc[-1]) if len(s) > 0 else 0.0,
        }
