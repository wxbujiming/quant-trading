"""
布林带策略 + RSI策略
"""
from src.strategy.base import BaseStrategy, Signal
import pandas as pd
import numpy as np


class BollingerBandsStrategy(BaseStrategy):
    """
    布林带均值回归策略
    
    参数:
        period: 布林带周期 (默认20)
        std_dev: 标准差倍数 (默认2.0)
        exit_std_dev: 退出标准差倍数 (默认0.5, 回到中线附近退出)
        stop_loss: 止损比例 (默认0.05)
    """
    
    def init(self):
        """初始化"""
        self.period = self.params.get('period', 20)
        self.std_dev = self.params.get('std_dev', 2.0)
        self.exit_std_dev = self.params.get('exit_std_dev', 0.5)
        self.stop_loss = self.params.get('stop_loss', 0.05)
        
        # 计算布林带
        self.data['ma'] = self.data['close'].rolling(self.period).mean()
        self.data['std'] = self.data['close'].rolling(self.period).std()
        self.data['upper'] = self.data['ma'] + self.std_dev * self.data['std']
        self.data['lower'] = self.data['ma'] - self.std_dev * self.data['std']
        self.data['mid_upper'] = self.data['ma'] + self.exit_std_dev * self.data['std']
        self.data['mid_lower'] = self.data['ma'] - self.exit_std_dev * self.data['std']
        # 带宽
        self.data['bandwidth'] = (self.data['upper'] - self.data['lower']) / self.data['ma']
        
        self._buy_price = None  # 记录买入成本价
        
        self.log(f"布林带策略初始化: 周期={self.period}, 标准差={self.std_dev}")
    
    def next(self, bar: pd.Series) -> Signal:
        """生成信号"""
        idx = bar.name if bar.name is not None else 0
        if isinstance(idx, int):
            loc = idx
        else:
            loc = self.data.index.get_loc(idx)
        
        if loc < self.period:
            return Signal.HOLD
        
        close = self.data['close'].iloc[loc]
        upper = self.data['upper'].iloc[loc]
        lower = self.data['lower'].iloc[loc]
        mid_upper = self.data['mid_upper'].iloc[loc]
        mid_lower = self.data['mid_lower'].iloc[loc]
        bandwidth = self.data['bandwidth'].iloc[loc]
        
        if pd.isna(upper) or pd.isna(lower):
            return Signal.HOLD
        
        # 止损检查
        if self._buy_price is not None:
            loss_pct = (close - self._buy_price) / self._buy_price
            if loss_pct < -self.stop_loss:
                self._buy_price = None
                return Signal.SELL
        
        # 买入: 价格跌破下轨且带宽足够宽(趋势不会太窄)
        if close <= lower and bandwidth > 0.03:
            self._buy_price = close
            return Signal.BUY
        
        # 卖出: 价格回到中轨附近
        if mid_lower <= close <= mid_upper:
            self._buy_price = None
            return Signal.SELL
        
        return Signal.HOLD


class RSIStrategy(BaseStrategy):
    """
    RSI超买超卖策略
    
    参数:
        period: RSI周期 (默认14)
        oversold: 超卖阈值 (默认30)
        overbought: 超买阈值 (默认70)
        exit_oversold: 退出超卖阈值 (默认50)
        exit_overbought: 退出超买阈值 (默认50)
        stop_loss: 止损比例 (默认0.05)
    """
    
    def init(self):
        """初始化"""
        self.period = self.params.get('period', 14)
        self.oversold = self.params.get('oversold', 30)
        self.overbought = self.params.get('overbought', 70)
        self.exit_oversold = self.params.get('exit_oversold', 50)
        self.exit_overbought = self.params.get('exit_overbought', 50)
        self.stop_loss = self.params.get('stop_loss', 0.05)
        
        # 计算RSI
        delta = self.data['close'].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(self.period).mean()
        avg_loss = loss.rolling(self.period).mean()
        
        rs = avg_gain / avg_loss.replace(0, np.nan)
        self.data['rsi'] = 100 - (100 / (1 + rs))
        
        self._buy_price = None
        
        self.log(f"RSI策略初始化: 周期={self.period}, 超卖={self.oversold}, 超买={self.overbought}")
    
    def next(self, bar: pd.Series) -> Signal:
        """生成信号"""
        idx = bar.name if bar.name is not None else 0
        if isinstance(idx, int):
            loc = idx
        else:
            loc = self.data.index.get_loc(idx)
        
        if loc < self.period + 1:
            return Signal.HOLD
        
        rsi = self.data['rsi'].iloc[loc]
        close = self.data['close'].iloc[loc]
        
        if pd.isna(rsi):
            return Signal.HOLD
        
        # 止损检查
        if self._buy_price is not None:
            loss_pct = (close - self._buy_price) / self._buy_price
            if loss_pct < -self.stop_loss:
                self._buy_price = None
                return Signal.SELL
        
        # 超卖买入
        if rsi < self.oversold:
            self._buy_price = close
            return Signal.BUY
        
        # 从超卖区回到中性区卖出
        if rsi > self.exit_oversold:
            self._buy_price = None
            return Signal.SELL
        
        return Signal.HOLD


class RSI2Strategy(BaseStrategy):
    """
    RSI(2)短线反转策略
    
    使用2周期RSI捕捉短线超卖反弹机会
    
    参数:
        period: RSI周期 (默认2)
        oversold: 超卖阈值 (默认10)
        overbought: 超买阈值 (默认90)
        ma_period: 趋势过滤均线周期 (默认200)
        stop_loss: 止损比例 (默认0.03)
    """
    
    def init(self):
        """初始化"""
        self.period = self.params.get('period', 2)
        self.oversold = self.params.get('oversold', 10)
        self.overbought = self.params.get('overbought', 90)
        self.ma_period = self.params.get('ma_period', 200)
        self.stop_loss = self.params.get('stop_loss', 0.03)
        
        # 计算RSI(2)
        delta = self.data['close'].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(self.period).mean()
        avg_loss = loss.rolling(self.period).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        self.data['rsi'] = 100 - (100 / (1 + rs))
        
        # 趋势过滤
        self.data['ma200'] = self.data['close'].rolling(self.ma_period).mean()
        
        self._buy_price = None
        
        self.log(f"RSI2短线策略初始化: RSI周期={self.period}, 超卖={self.oversold}")
    
    def next(self, bar: pd.Series) -> Signal:
        """生成信号"""
        idx = bar.name if bar.name is not None else 0
        if isinstance(idx, int):
            loc = idx
        else:
            loc = self.data.index.get_loc(idx)
        
        if loc < self.ma_period:
            return Signal.HOLD
        
        rsi = self.data['rsi'].iloc[loc]
        close = self.data['close'].iloc[loc]
        ma200 = self.data['ma200'].iloc[loc]
        
        if pd.isna(rsi) or pd.isna(ma200):
            return Signal.HOLD
        
        # 止损检查
        if self._buy_price is not None:
            loss_pct = (close - self._buy_price) / self._buy_price
            if loss_pct < -self.stop_loss:
                self._buy_price = None
                return Signal.SELL
        
        # 只在上升趋势中做多 (价格在200日均线上方)
        if close < ma200:
            return Signal.HOLD
        
        # 超卖买入
        if rsi < self.oversold:
            self._buy_price = close
            return Signal.BUY
        
        # 超买卖出
        if rsi > self.overbought:
            self._buy_price = None
            return Signal.SELL
        
        return Signal.HOLD
