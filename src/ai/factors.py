"""
量价因子计算模块。

提供 30 个 Alpha101 风格因子，涵盖动量、波动、量价关系、均值回归、时间序列五大类。
所有因子使用向后操作（rolling / ewm / diff / pct_change），零 look-ahead 风险。
"""
from typing import Dict, List, Optional
import pandas as pd
import numpy as np


_REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]


def _check_columns(df: pd.DataFrame):
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"缺少必要列: {missing}")


class FactorComputer:
    """量价因子计算器。

    用法:
        fc = FactorComputer()
        factor_df = fc.compute_all(ohlcv_df)
    """

    def __init__(self):
        self._cache: Dict[str, pd.Series] = {}

    # ──────────────────────── 动量类 (10) ────────────────────────

    def ROC5(self, df: pd.DataFrame) -> pd.Series:
        """5 期收益率"""
        return df["close"].pct_change(5)

    def ROC10(self, df: pd.DataFrame) -> pd.Series:
        """10 期收益率"""
        return df["close"].pct_change(10)

    def ROC20(self, df: pd.DataFrame) -> pd.Series:
        """20 期收益率"""
        return df["close"].pct_change(20)

    def SMA5_norm(self, df: pd.DataFrame) -> pd.Series:
        """收盘价 / SMA5 - 1"""
        sma = df["close"].rolling(5).mean()
        return df["close"] / sma - 1

    def SMA10_norm(self, df: pd.DataFrame) -> pd.Series:
        """收盘价 / SMA10 - 1"""
        sma = df["close"].rolling(10).mean()
        return df["close"] / sma - 1

    def SMA20_norm(self, df: pd.DataFrame) -> pd.Series:
        """收盘价 / SMA20 - 1"""
        sma = df["close"].rolling(20).mean()
        return df["close"] / sma - 1

    def mom_diff_5_20(self, df: pd.DataFrame) -> pd.Series:
        """短期动量与长期动量差值: ROC5 - ROC20"""
        return df["close"].pct_change(5) - df["close"].pct_change(20)

    def mom_diff_10_20(self, df: pd.DataFrame) -> pd.Series:
        """中期动量与长期动量差值: ROC10 - ROC20"""
        return df["close"].pct_change(10) - df["close"].pct_change(20)

    def close_vs_max5(self, df: pd.DataFrame) -> pd.Series:
        """收盘价 / 5 日最高价 - 1"""
        return df["close"] / df["high"].rolling(5).max() - 1

    def close_vs_min5(self, df: pd.DataFrame) -> pd.Series:
        """收盘价 / 5 日最低价 - 1"""
        return df["close"] / df["low"].rolling(5).min() - 1

    # ──────────────────────── 波动类 (5) ────────────────────────

    def ATR14(self, df: pd.DataFrame) -> pd.Series:
        """14 期 ATR（平均真实波幅）"""
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs(),
        ], axis=1).max(axis=1)
        return tr.rolling(14).mean()

    def bollinger_width(self, df: pd.DataFrame) -> pd.Series:
        """布林带宽度: (上轨 - 下轨) / 中轨"""
        sma = df["close"].rolling(20).mean()
        std = df["close"].rolling(20).std()
        upper = sma + 2 * std
        lower = sma - 2 * std
        return (upper - lower) / sma

    def volatility_ratio(self, df: pd.DataFrame) -> pd.Series:
        """波动率比率: 短期波动率 / 长期波动率"""
        short_vol = df["close"].pct_change().rolling(5).std()
        long_vol = df["close"].pct_change().rolling(20).std()
        return short_vol / long_vol.replace(0, np.nan)

    def daily_amplitude(self, df: pd.DataFrame) -> pd.Series:
        """日内振幅: (high - low) / close"""
        return (df["high"] - df["low"]) / df["close"]

    def CCI(self, df: pd.DataFrame) -> pd.Series:
        """商品通道指数 (CCI)"""
        tp = (df["high"] + df["low"] + df["close"]) / 3
        sma = tp.rolling(20).mean()
        mad = tp.rolling(20).apply(lambda x: np.abs(x - x.mean()).mean())
        return (tp - sma) / (0.015 * mad.replace(0, np.nan))

    # ──────────────────────── 量价类 (5) ────────────────────────

    def volume_price_trend(self, df: pd.DataFrame) -> pd.Series:
        """量价趋势: 累计 (成交量 × 价格变化率)"""
        ret = df["close"].pct_change()
        return (ret * df["volume"]).cumsum()

    def volume_weighted_price(self, df: pd.DataFrame) -> pd.Series:
        """量加权价格: (close * volume) 的滚动均值 / close"""
        vwp = (df["close"] * df["volume"]).rolling(20).sum() / df["volume"].rolling(20).sum()
        return vwp / df["close"]

    def volume_impact(self, df: pd.DataFrame) -> pd.Series:
        """量冲击: (close - close.shift(1)) / sqrt(volume)"""
        ret = df["close"].diff()
        return ret / np.sqrt(df["volume"]).replace(0, np.nan)

    def OBV(self, df: pd.DataFrame) -> pd.Series:
        """能量潮 (OBV) 的 10 期变化率"""
        obv = (df["volume"] * np.sign(df["close"].diff())).fillna(0).cumsum()
        return obv.pct_change(10)

    def volume_ratio(self, df: pd.DataFrame) -> pd.Series:
        """量比: 当前成交量 / 5 日均量"""
        return df["volume"] / df["volume"].rolling(5).mean().replace(0, np.nan)

    # ──────────────────────── 均值回归类 (5) ────────────────────────

    def bb_position(self, df: pd.DataFrame) -> pd.Series:
        """布林带位置: (close - 下轨) / (上轨 - 下轨)"""
        sma = df["close"].rolling(20).mean()
        std = df["close"].rolling(20).std()
        upper = sma + 2 * std
        lower = sma - 2 * std
        return (df["close"] - lower) / (upper - lower).replace(0, np.nan)

    def ma20_deviation(self, df: pd.DataFrame) -> pd.Series:
        """偏离 MA20 程度: (close - MA20) / MA20"""
        ma20 = df["close"].rolling(20).mean()
        return (df["close"] - ma20) / ma20

    def RSRS(self, df: pd.DataFrame) -> pd.Series:
        """相对强弱回归斜率: rolling 20 日 OLS 斜率"""
        x = np.arange(20)
        def _slope(y):
            if len(y) < 20 or np.isclose(y.std(), 0):
                return np.nan
            return np.polyfit(x, y, 1)[0]
        return df["close"].rolling(20).apply(_slope, raw=True)

    def bias(self, df: pd.DataFrame) -> pd.Series:
        """乖离率: (close - 均线) / 均线"""
        ma = df["close"].rolling(10).mean()
        return (df["close"] - ma) / ma

    def oi_change(self, df: pd.DataFrame) -> pd.Series:
        """持仓量变化率（如果有 hold 列）"""
        if "hold" not in df.columns:
            return pd.Series(0.0, index=df.index)
        return df["hold"].pct_change(5).fillna(0)

    # ──────────────────────── 时间序列类 (5) ────────────────────────

    def ar_residual(self, df: pd.DataFrame) -> pd.Series:
        """自回归残差: close - AR(1) 预测值"""
        lag1 = df["close"].shift(1)
        rolling_corr = df["close"].rolling(20).corr(lag1)
        rolling_std_ratio = (df["close"].rolling(20).std() /
                             lag1.rolling(20).std().replace(0, np.nan))
        beta = rolling_corr * rolling_std_ratio
        predicted = beta * lag1
        return df["close"] - predicted

    def consecutive_count(self, df: pd.DataFrame) -> pd.Series:
        """连续同向计数（涨 +1 / 跌 -1）"""
        direction = np.sign(df["close"].diff())
        result = np.zeros(len(direction))
        count = 0
        for i in range(1, len(direction)):
            if direction.iloc[i] == direction.iloc[i - 1] and direction.iloc[i] != 0:
                count += 1
            else:
                count = 1 if direction.iloc[i] > 0 else (-1 if direction.iloc[i] < 0 else 0)
            result[i] = count
        return pd.Series(result, index=df.index)

    def gap(self, df: pd.DataFrame) -> pd.Series:
        """缺口: (open - prev_close) / prev_close"""
        return (df["open"] - df["close"].shift(1)) / df["close"].shift(1)

    def price_acceleration(self, df: pd.DataFrame) -> pd.Series:
        """价格加速度: ROC5 的 5 期变化"""
        roc5 = df["close"].pct_change(5)
        return roc5.diff()

    def hh_ll_distance(self, df: pd.DataFrame) -> pd.Series:
        """距最近 N 日高低点的距离"""
        hh = df["high"].rolling(20).max()
        ll = df["low"].rolling(20).min()
        to_hh = (hh - df["close"]) / hh.replace(0, np.nan)
        to_ll = (df["close"] - ll) / ll.replace(0, np.nan)
        return to_hh - to_ll

    # ──────────────────────── 批量计算 ────────────────────────

    def compute_all(self, df: pd.DataFrame,
                    columns: Optional[List[str]] = None) -> pd.DataFrame:
        """计算所有（或指定）因子，返回 DataFrame。

        Args:
            df: OHLCV DataFrame，需含 open/high/low/close/volume
            columns: 因子名列表，None=全部

        Returns:
            因子 DataFrame，索引与 df 一致
        """
        _check_columns(df)
        self._cache.clear()

        factor_map = {
            "ROC5": self.ROC5,
            "ROC10": self.ROC10,
            "ROC20": self.ROC20,
            "SMA5_norm": self.SMA5_norm,
            "SMA10_norm": self.SMA10_norm,
            "SMA20_norm": self.SMA20_norm,
            "mom_diff_5_20": self.mom_diff_5_20,
            "mom_diff_10_20": self.mom_diff_10_20,
            "close_vs_max5": self.close_vs_max5,
            "close_vs_min5": self.close_vs_min5,
            "ATR14": self.ATR14,
            "bollinger_width": self.bollinger_width,
            "volatility_ratio": self.volatility_ratio,
            "daily_amplitude": self.daily_amplitude,
            "CCI": self.CCI,
            "volume_price_trend": self.volume_price_trend,
            "volume_weighted_price": self.volume_weighted_price,
            "volume_impact": self.volume_impact,
            "OBV": self.OBV,
            "volume_ratio": self.volume_ratio,
            "bb_position": self.bb_position,
            "ma20_deviation": self.ma20_deviation,
            "RSRS": self.RSRS,
            "bias": self.bias,
            "oi_change": self.oi_change,
            "ar_residual": self.ar_residual,
            "consecutive_count": self.consecutive_count,
            "gap": self.gap,
            "price_acceleration": self.price_acceleration,
            "hh_ll_distance": self.hh_ll_distance,
        }

        target = columns or list(factor_map.keys())
        results = {}
        for name in target:
            func = factor_map.get(name)
            if func is None:
                continue
            try:
                results[name] = func(df)
            except Exception:
                results[name] = pd.Series(np.nan, index=df.index)

        result_df = pd.DataFrame(results, index=df.index)
        # 防止 inf 值污染后续环节
        result_df = result_df.replace([np.inf, -np.inf], np.nan)
        return result_df
