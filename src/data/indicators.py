"""
技术指标计算模块
提供常用的技术分析指标计算
"""

import pandas as pd
import numpy as np
from typing import Optional
from loguru import logger


class TechnicalIndicators:
    """技术指标计算器"""

    @staticmethod
    def SMA(data: pd.Series, period: int = 20) -> pd.Series:
        """简单移动平均线"""
        return data.rolling(window=period).mean()

    @staticmethod
    def EMA(data: pd.Series, period: int = 20) -> pd.Series:
        """指数移动平均线"""
        return data.ewm(span=period, adjust=False).mean()

    @staticmethod
    def MACD(data: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
        """MACD指标
        返回: DataFrame with columns ['macd', 'signal', 'histogram']
        """
        ema_fast = data.ewm(span=fast, adjust=False).mean()
        ema_slow = data.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = (macd_line - signal_line) * 2

        return pd.DataFrame({
            'macd': macd_line,
            'signal': signal_line,
            'histogram': histogram,
        })

    @staticmethod
    def RSI(data: pd.Series, period: int = 14) -> pd.Series:
        """相对强弱指标 (RSI)"""
        delta = data.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()

        # 修正: 避免除零
        avg_loss = avg_loss.replace(0, np.nan)

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50.0)

    @staticmethod
    def Bollinger(data: pd.Series, period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
        """布林带指标
        返回: DataFrame with columns ['middle', 'upper', 'lower']
        """
        middle = data.rolling(window=period).mean()
        std = data.rolling(window=period).std()
        upper = middle + std_dev * std
        lower = middle - std_dev * std

        return pd.DataFrame({
            'middle': middle,
            'upper': upper,
            'lower': lower,
        })

    @staticmethod
    def ATR(data: pd.DataFrame, period: int = 14) -> pd.Series:
        """平均真实波幅 (ATR)
        需要DataFrame包含 high, low, close 列
        """
        high = data['high']
        low = data['low']
        close = data['close']

        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        return tr.rolling(window=period).mean()

    @staticmethod
    def KDJ(data: pd.DataFrame, period: int = 9, k_smooth: int = 3, d_smooth: int = 3) -> pd.DataFrame:
        """KDJ指标
        需要DataFrame包含 high, low, close 列
        """
        low_min = data['low'].rolling(window=period).min()
        high_max = data['high'].rolling(window=period).max()

        rsv = (data['close'] - low_min) / (high_max - low_min) * 100
        rsv = rsv.fillna(50)

        k = rsv.ewm(com=k_smooth - 1, adjust=False).mean()
        d = k.ewm(com=d_smooth - 1, adjust=False).mean()
        j = 3 * k - 2 * d

        return pd.DataFrame({'k': k, 'd': d, 'j': j})

    @staticmethod
    def WilliamsR(data: pd.DataFrame, period: int = 14) -> pd.Series:
        """威廉指标 (%R)"""
        high_max = data['high'].rolling(window=period).max()
        low_min = data['low'].rolling(window=period).min()
        wr = (high_max - data['close']) / (high_max - low_min) * -100
        return wr.fillna(-50)

    @staticmethod
    def CCI(data: pd.DataFrame, period: int = 20) -> pd.Series:
        """商品通道指标 (CCI)"""
        tp = (data['high'] + data['low'] + data['close']) / 3
        sma = tp.rolling(window=period).mean()
        mad = tp.rolling(window=period).apply(lambda x: np.abs(x - x.mean()).mean())
        cci = (tp - sma) / (0.015 * mad)
        return cci.fillna(0)

    @staticmethod
    def OBV(data: pd.DataFrame) -> pd.Series:
        """能量潮 (OBV)"""
        obv = (data['volume'] * (~data['close'].diff().le(0) * 2 - 1)).cumsum()
        return obv

    @staticmethod
    def add_indicators(df: pd.DataFrame, indicators: list = None) -> pd.DataFrame:
        """批量添加技术指标到DataFrame
        indicators: 指标列表, 如 ['sma5', 'sma20', 'macd', 'rsi', 'boll', 'atr']
        """
        result = df.copy()

        if indicators is None:
            indicators = ['sma5', 'sma20', 'macd', 'rsi', 'boll', 'atr']

        close = result['close']

        for ind in indicators:
            ind_lower = ind.lower()

            if ind_lower == 'sma5':
                result['sma5'] = TechnicalIndicators.SMA(close, 5)
            elif ind_lower == 'sma10':
                result['sma10'] = TechnicalIndicators.SMA(close, 10)
            elif ind_lower == 'sma20':
                result['sma20'] = TechnicalIndicators.SMA(close, 20)
            elif ind_lower == 'sma60':
                result['sma60'] = TechnicalIndicators.SMA(close, 60)
            elif ind_lower == 'ema5':
                result['ema5'] = TechnicalIndicators.EMA(close, 5)
            elif ind_lower == 'ema20':
                result['ema20'] = TechnicalIndicators.EMA(close, 20)
            elif ind_lower == 'ema60':
                result['ema60'] = TechnicalIndicators.EMA(close, 60)
            elif ind_lower == 'macd':
                macd_df = TechnicalIndicators.MACD(close)
                result['macd'] = macd_df['macd']
                result['macd_signal'] = macd_df['signal']
                result['macd_histogram'] = macd_df['histogram']
            elif ind_lower == 'rsi':
                result['rsi'] = TechnicalIndicators.RSI(close)
            elif ind_lower == 'boll':
                boll_df = TechnicalIndicators.Bollinger(close)
                result['boll_middle'] = boll_df['middle']
                result['boll_upper'] = boll_df['upper']
                result['boll_lower'] = boll_df['lower']
            elif ind_lower == 'atr':
                result['atr'] = TechnicalIndicators.ATR(result)
            elif ind_lower == 'kdj':
                kdj_df = TechnicalIndicators.KDJ(result)
                result['kdj_k'] = kdj_df['k']
                result['kdj_d'] = kdj_df['d']
                result['kdj_j'] = kdj_df['j']
            elif ind_lower == 'wr':
                result['wr'] = TechnicalIndicators.WilliamsR(result)
            elif ind_lower == 'cci':
                result['cci'] = TechnicalIndicators.CCI(result)
            elif ind_lower == 'obv':
                result['obv'] = TechnicalIndicators.OBV(result)

        return result
