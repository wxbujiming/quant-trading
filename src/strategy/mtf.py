"""
多时间框架工具模块

提供:
  - 日线数据重采样为更高时间框架（周线/月线/N日）
  - 在更高时间框架上计算技术指标
  - 将更高TF指标值映射回日线
  - MultiTimeframeMixin 混入类

用法:
    class MyStrategy(MultiTimeframeMixin, DualMaCrossStrategy):
        def on_start(self):
            super().on_start()
            self.setup_mtf(self.data, timeframes=['weekly', 'monthly'])
            self.mtf.compute_indicators('weekly', sma=[20, 40])
            self.mtf.compute_indicators('monthly', sma=[12])

        def on_bar(self, bar):
            weekly_sma20 = self.mtf.get('weekly', bar['date'], 'sma_20')
            if weekly_sma20 and bar['close'] > weekly_sma20:
                pass  # 趋势向上，只做多
"""
from typing import Dict, List, Optional, Union
import pandas as pd
import numpy as np

from src.data.indicators import TechnicalIndicators


# ────────── 重采样 ──────────

def resample_ohlc(df: pd.DataFrame, timeframe: Union[str, int] = 'weekly') -> pd.DataFrame:
    """
    将日线 OHLCV 数据重采样为更高时间框架。

    Args:
        df: 日线 DataFrame（需 DatetimeIndex，含 open/high/low/close/volume）
        timeframe: 'weekly' | 'monthly' | int(N日)

    Returns:
        重采样后的 DataFrame
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("DataFrame 需要 DatetimeIndex")

    if timeframe == 'weekly':
        rule = 'W-FRI'
    elif timeframe == 'monthly':
        rule = 'ME'
    elif isinstance(timeframe, int):
        rule = f'{timeframe}D'
    else:
        raise ValueError(f"不支持的时间框架: {timeframe}")

    agg_dict = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
    }
    for col in ['hold', 'settle']:
        if col in df.columns:
            agg_dict[col] = 'last'

    result = df.resample(rule).agg(agg_dict)
    result.dropna(subset=['open', 'close'], inplace=True)
    return result


# ────────── 指标计算 ──────────

def compute_indicators(tf_df: pd.DataFrame, **indicators) -> pd.DataFrame:
    """
    在时间框架 DataFrame 上计算技术指标。

    支持的指标:
        sma: int 或 [int, ...]
        ema: int 或 [int, ...]
        macd: (fast, slow, signal)
        rsi: period
        atr: period
        boll: (period, std_dev)
        kdj: (period, k_smooth, d_smooth)

    Returns:
        添加了指标列的 DataFrame
    """
    df = tf_df.copy()
    close = df['close']

    for name, params in indicators.items():
        # ── SMA ──
        if name == 'sma':
            periods = [params] if isinstance(params, (int, float)) else params
            for p in periods:
                col = f'sma_{p}'
                if col not in df.columns:
                    df[col] = TechnicalIndicators.SMA(close, int(p))

        # ── EMA ──
        elif name == 'ema':
            periods = [params] if isinstance(params, (int, float)) else params
            for p in periods:
                col = f'ema_{p}'
                if col not in df.columns:
                    df[col] = TechnicalIndicators.EMA(close, int(p))

        # ── MACD ──
        elif name == 'macd':
            fast, slow, signal = params
            if 'macd' not in df.columns:
                macd_df = TechnicalIndicators.MACD(close, fast, slow, signal)
                df['macd'] = macd_df['macd']
                df['macd_signal'] = macd_df['signal']
                df['macd_hist'] = macd_df['histogram']

        # ── RSI ──
        elif name == 'rsi':
            period = int(params)
            col = f'rsi_{period}'
            if col not in df.columns:
                df[col] = TechnicalIndicators.RSI(close, period)

        # ── ATR ──
        elif name == 'atr':
            period = int(params)
            col = f'atr_{period}'
            if col not in df.columns and 'high' in df.columns and 'low' in df.columns:
                df[col] = TechnicalIndicators.ATR(df, period)

        # ── 布林带 ──
        elif name == 'boll':
            period, std_dev = params
            prefix = f'boll_{period}'
            if prefix not in df.columns:
                boll_df = TechnicalIndicators.Bollinger(close, period, std_dev)
                df[f'{prefix}_middle'] = boll_df['middle']
                df[f'{prefix}_upper'] = boll_df['upper']
                df[f'{prefix}_lower'] = boll_df['lower']

        # ── KDJ ──
        elif name == 'kdj':
            period, k_smooth, d_smooth = params
            if 'kdj_k' not in df.columns:
                kdj_df = TechnicalIndicators.KDJ(df, period, k_smooth, d_smooth)
                df['kdj_k'] = kdj_df['k']
                df['kdj_d'] = kdj_df['d']
                df['kdj_j'] = kdj_df['j']

    return df


# ────────── 映射 ──────────

def map_to_daily(higher_tf_df: pd.DataFrame, daily_index: pd.DatetimeIndex) -> pd.DataFrame:
    """
    将更高时间框架的指标值映射到每个日线日期。

    对每个日线日期，取该日期之前最近的已完成更高TF K线。
    通过 shift(1) 防止未来函数。

    Args:
        higher_tf_df: 更高TF的DataFrame（DatetimeIndex + 指标列）
        daily_index: 日线索引

    Returns:
        对齐到日线的DataFrame，含前向填充的更高TF指标值
    """
    # 先 reindex 到日线（前向填充），再 shift 1 根避免未来函数
    aligned = higher_tf_df.reindex(daily_index, method='ffill')
    aligned = aligned.shift(1)
    return aligned


# ────────── 多时间框架容器 ──────────

class MultiTimeframeContainer:
    """
    多时间框架数据容器。

    存放每个时间框架的重采样 DataFrame，提供指标计算和值查询方法。
    """

    def __init__(self, daily_df: pd.DataFrame, timeframes: List[str] = None):
        """
        Args:
            daily_df: 日线OHLCV DataFrame（DatetimeIndex）
            timeframes: 时间框架列表，如 ['weekly', 'monthly']
        """
        self._daily_index = daily_df.index
        self._data: Dict[str, pd.DataFrame] = {}
        self._daily_mapped: Dict[str, pd.DataFrame] = {}

        timeframes = timeframes or ['weekly', 'monthly']
        for tf in timeframes:
            name = str(tf)
            self._data[name] = resample_ohlc(daily_df, tf)

    def compute_indicators(self, tf_name: str, **indicators) -> pd.DataFrame:
        """
        在指定时间框架上计算指标，并预映射到日线。

        Args:
            tf_name: 时间框架名称
            **indicators: 指标参数，如 sma=[20,40], atr=14

        Returns:
            该时间框架的 DataFrame（含指标列）
        """
        tf_df = self._data.get(tf_name)
        if tf_df is None:
            raise KeyError(f"时间框架 '{tf_name}' 不存在。可用: {list(self._data.keys())}")

        result = compute_indicators(tf_df, **indicators)
        self._data[tf_name] = result
        self._daily_mapped[tf_name] = map_to_daily(result, self._daily_index)
        return result

    def get(self, tf_name: str, date, column: str):
        """
        获取某日期在指定时间框架上的指标值。

        Args:
            tf_name: 时间框架名称
            date: 日期（DateLike）
            column: 列名

        Returns:
            指标值，若不可用则返回 None
        """
        daily_map = self._daily_mapped.get(tf_name)
        if daily_map is None:
            return None

        dt = pd.Timestamp(date)
        if dt not in daily_map.index:
            idx = daily_map.index.searchsorted(dt)
            if 0 < idx < len(daily_map):
                dt = daily_map.index[idx - 1]
            else:
                return None

        val = daily_map.loc[dt, column] if column in daily_map.columns else None
        return None if pd.isna(val) else val

    def get_df(self, tf_name: str) -> Optional[pd.DataFrame]:
        """获取指定时间框架的重采样 DataFrame。"""
        return self._data.get(tf_name)

    def get_daily(self, tf_name: str, column: str) -> pd.Series:
        """获取某指标列在日线频率上的对齐序列。"""
        daily_map = self._daily_mapped.get(tf_name)
        if daily_map is None or column not in daily_map.columns:
            return pd.Series(index=self._daily_index, dtype=float)
        return daily_map[column]

    @property
    def timeframes(self) -> List[str]:
        return list(self._data.keys())


# ────────── 混入类 ──────────

class MultiTimeframeMixin:
    """
    多时间框架混入类。

    混入 BaseFuturesStrategy 子类，提供 mtf 属性访问多时间框架数据。

    用法:
        class MyStrategy(MultiTimeframeMixin, DualMaCrossStrategy):
            def on_start(self):
                super().on_start()
                self.setup_mtf(self.data, timeframes=['weekly'])
                self.mtf.compute_indicators('weekly', sma=[20, 40])

            def on_bar(self, bar):
                w_sma = self.mtf.get('weekly', bar['date'], 'sma_20')
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mtf: Optional[MultiTimeframeContainer] = None

    def setup_mtf(self, daily_df: pd.DataFrame, timeframes: List[str] = None):
        """
        初始化多时间框架数据。在 on_start() 中调用。

        Args:
            daily_df: 日线 OHLCV 完整 DataFrame
            timeframes: 时间框架列表
        """
        self._mtf = MultiTimeframeContainer(daily_df, timeframes)

    @property
    def mtf(self) -> Optional[MultiTimeframeContainer]:
        return self._mtf
