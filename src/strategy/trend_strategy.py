"""
双均线策略示例
"""
from src.strategy.base import BaseStrategy, Signal
import pandas as pd
import numpy as np


class SmaCrossStrategy(BaseStrategy):
    """
    双均线交叉策略
    
    参数:
        fast_period: 快线周期 (默认10)
        slow_period: 慢线周期 (默认30)
    """
    
    def init(self):
        """初始化策略"""
        self.fast_period = self.params.get('fast_period', 10)
        self.slow_period = self.params.get('slow_period', 30)
        
        # 计算均线
        self.data['sma_fast'] = self.data['close'].rolling(self.fast_period).mean()
        self.data['sma_slow'] = self.data['close'].rolling(self.slow_period).mean()
        
        self.log(f"初始化完成: 快线={self.fast_period}, 慢线={self.slow_period}")
    
    def next(self, bar: pd.Series) -> Signal:
        """
        生成信号
        
        快线上穿慢线 -> 买入
        快线下穿慢线 -> 卖出
        """
        idx = bar.name if bar.name is not None else 0
        
        # 获取当前位置
        if isinstance(idx, int):
            loc = idx
        else:
            loc = self.data.index.get_loc(idx)
        
        if loc < self.slow_period:
            return Signal.HOLD
        
        # 获取当前和前一个值
        current_fast = self.data['sma_fast'].iloc[loc]
        current_slow = self.data['sma_slow'].iloc[loc]
        prev_fast = self.data['sma_fast'].iloc[loc - 1]
        prev_slow = self.data['sma_slow'].iloc[loc - 1]
        
        # 检查交叉
        if pd.isna(current_fast) or pd.isna(current_slow):
            return Signal.HOLD
        
        # 金叉 - 买入
        if prev_fast <= prev_slow and current_fast > current_slow:
            return Signal.BUY
        
        # 死叉 - 卖出
        if prev_fast >= prev_slow and current_fast < current_slow:
            return Signal.SELL
        
        return Signal.HOLD


class MACDStrategy(BaseStrategy):
    """
    MACD策略
    
    参数:
        fast_period: 快线周期 (默认12)
        slow_period: 慢线周期 (默认26)
        signal_period: 信号线周期 (默认9)
    """
    
    def init(self):
        """初始化"""
        self.fast_period = self.params.get('fast_period', 12)
        self.slow_period = self.params.get('slow_period', 26)
        self.signal_period = self.params.get('signal_period', 9)
        
        # 计算MACD
        ema_fast = self.data['close'].ewm(span=self.fast_period).mean()
        ema_slow = self.data['close'].ewm(span=self.slow_period).mean()
        
        self.data['macd'] = ema_fast - ema_slow
        self.data['signal'] = self.data['macd'].ewm(span=self.signal_period).mean()
        self.data['histogram'] = self.data['macd'] - self.data['signal']
        
        self.log(f"MACD策略初始化完成")
    
    def next(self, bar: pd.Series) -> Signal:
        """生成信号"""
        idx = bar.name if bar.name is not None else 0
        
        if isinstance(idx, int):
            loc = idx
        else:
            loc = self.data.index.get_loc(idx)
        
        if loc < self.slow_period + self.signal_period:
            return Signal.HOLD
        
        current_macd = self.data['macd'].iloc[loc]
        current_signal = self.data['signal'].iloc[loc]
        prev_macd = self.data['macd'].iloc[loc - 1]
        prev_signal = self.data['signal'].iloc[loc - 1]
        
        if pd.isna(current_macd) or pd.isna(current_signal):
            return Signal.HOLD
        
        # MACD上穿信号线 - 买入
        if prev_macd <= prev_signal and current_macd > current_signal:
            return Signal.BUY
        
        # MACD下穿信号线 - 卖出
        if prev_macd >= prev_signal and current_macd < current_signal:
            return Signal.SELL
        
        return Signal.HOLD
