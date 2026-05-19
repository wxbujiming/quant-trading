"""
期货CTA策略示例
"""
from typing import Dict, Optional
from abc import ABC, abstractmethod
import pandas as pd
import numpy as np
from loguru import logger


class BaseFuturesStrategy(ABC):
    """
    期货策略基类
    
    子类需要实现:
    - on_start(): 策略初始化
    - on_bar(): 每个bar调用一次
    """
    
    def __init__(self, params: Dict = None):
        self.params = params or {}
        self.engine = None
        self.symbol = ""
        self.name = self.__class__.__name__
        self.data: Optional[pd.DataFrame] = None  # 完整数据（on_start 前由引擎注入）
    
    def on_start(self):
        """策略初始化"""
        pass
    
    @abstractmethod
    def on_bar(self, bar: Dict):
        """每个K线调用一次"""
        pass
    
    def log(self, msg: str):
        logger.info(f"[{self.name}] {msg}")


class DualMaCrossStrategy(BaseFuturesStrategy):
    """
    双均线期货CTA策略
    
    参数:
        fast_period: 快线周期 (默认10)
        slow_period: 慢线周期 (默认30)
        atr_period: ATR周期 (默认14)
        atr_multiplier: ATR止损乘数 (默认2.0)
        max_risk_pct: 单笔最大风险 (默认0.02 = 2%)
        use_trailing_stop: 是否使用移动止损 (默认True)
    """
    
    def __init__(self, params: Dict = None):
        super().__init__(params)
        self.fast_period = self.params.get("fast_period", 10)
        self.slow_period = self.params.get("slow_period", 30)
        self.atr_period = self.params.get("atr_period", 14)
        self.atr_multiplier = self.params.get("atr_multiplier", 2.0)
        self.max_risk_pct = self.params.get("max_risk_pct", 0.02)
        self.use_trailing_stop = self.params.get("use_trailing_stop", True)
        
        # 运行时状态
        self._prices = []
        self._fast_ma = None
        self._slow_ma = None
        self._atr = None
        self._position = 0  # 1=多, -1=空, 0=空仓
        self._entry_price = 0.0
        self._stop_price = 0.0
    
    def on_start(self):
        self.log(
            f"双均线CTA策略初始化: "
            f"快线={self.fast_period}, 慢线={self.slow_period}, "
            f"ATR止损={self.atr_multiplier}倍"
        )
    
    def on_bar(self, bar: Dict):
        close = bar["close"]
        high = bar["high"]
        low = bar["low"]
        date = bar["date"]
        
        self._prices.append(close)
        
        # 需要足够的数据来计算指标
        if len(self._prices) < self.slow_period + 1:
            return
        
        # 计算均线
        prices_series = pd.Series(self._prices)
        fast_ma = prices_series.rolling(self.fast_period).mean().iloc[-1]
        slow_ma = prices_series.rolling(self.slow_period).mean().iloc[-1]
        
        # 计算ATR
        if len(self._prices) >= self.atr_period + 1:
            tr_values = []
            for i in range(-self.atr_period, 0):
                h = self._prices[:i][-1] if len(self._prices[:i]) > 0 else high
                l_val = self._prices[:i][-1] if len(self._prices[:i]) > 0 else low
                prev_close = self._prices[i - 1] if abs(i - 1) < len(self._prices) else self._prices[i]
                tr = max(
                    high - low,
                    abs(high - prev_close),
                    abs(low - prev_close),
                )
                tr_values.append(tr)
            atr = np.mean(tr_values) if tr_values else 0
        else:
            atr = 0
        
        atr_value = max(atr, 1.0)  # 避免ATR为0
        
        # 获取当前持仓
        long_pos, short_pos = self.engine.get_position(self.symbol)
        
        # ─── 交易逻辑 ───
        
        # 多单信号：快线 > 慢线
        if fast_ma > slow_ma:
            # 如果没有多单，且有空单则先平空
            if short_pos and short_pos.volume > 0:
                self.engine.close_short(date, self.symbol, close)
                self._position = 0
            
            # 开多（如果还没有多单）
            if long_pos is None or long_pos.volume == 0:
                # 计算开仓量（基于风险）
                risk_per_contract = atr_value * self.engine.contract_multiplier * self.atr_multiplier
                if risk_per_contract > 0:
                    max_loss = self.engine.get_available_capital() * self.max_risk_pct
                    volume = max(1, int(max_loss / risk_per_contract))
                    # 限制最大手数
                    margin_per = close * self.engine.contract_multiplier * self.engine.margin_rate
                    max_by_margin = int(self.engine.get_available_capital() * 0.8 / margin_per)
                    volume = min(volume, max_by_margin)
                    
                    if volume > 0:
                        success = self.engine.open_long(date, self.symbol, close, volume)
                        if success:
                            self._position = 1
                            self._entry_price = close
                            self._stop_price = close - atr_value * self.atr_multiplier
                            self.log(f"开多 {volume}手 @ {close:.1f}, 止损={self._stop_price:.1f} (ATR={atr_value:.1f})")
            
            # 移动止损（多单）
            if long_pos and long_pos.volume > 0 and self.use_trailing_stop:
                new_stop = close - atr_value * self.atr_multiplier
                self._stop_price = max(self._stop_price, new_stop)
                if close <= self._stop_price:
                    self.engine.close_long(date, self.symbol, close)
                    self._position = 0
                    self.log(f"移动止损平多 @ {close:.1f}")
        
        # 空单信号：快线 < 慢线
        elif fast_ma < slow_ma:
            # 如果有多单则先平多
            if long_pos and long_pos.volume > 0:
                self.engine.close_long(date, self.symbol, close)
                self._position = 0
            
            # 开空
            if short_pos is None or short_pos.volume == 0:
                risk_per_contract = atr_value * self.engine.contract_multiplier * self.atr_multiplier
                if risk_per_contract > 0:
                    max_loss = self.engine.get_available_capital() * self.max_risk_pct
                    volume = max(1, int(max_loss / risk_per_contract))
                    margin_per = close * self.engine.contract_multiplier * self.engine.margin_rate
                    max_by_margin = int(self.engine.get_available_capital() * 0.8 / margin_per)
                    volume = min(volume, max_by_margin)
                    
                    if volume > 0:
                        success = self.engine.open_short(date, self.symbol, close, volume)
                        if success:
                            self._position = -1
                            self._entry_price = close
                            self._stop_price = close + atr_value * self.atr_multiplier
                            self.log(f"开空 {volume}手 @ {close:.1f}, 止损={self._stop_price:.1f} (ATR={atr_value:.1f})")
            
            # 移动止损（空单）
            if short_pos and short_pos.volume > 0 and self.use_trailing_stop:
                new_stop = close + atr_value * self.atr_multiplier
                self._stop_price = min(self._stop_price if self._stop_price > 0 else float("inf"), new_stop)
                if close >= self._stop_price:
                    self.engine.close_short(date, self.symbol, close)
                    self._position = 0
                    self.log(f"移动止损平空 @ {close:.1f}")
        
        # 没有信号 => 检查止损
        else:
            if long_pos and long_pos.volume > 0 and self._stop_price > 0:
                if close <= self._stop_price:
                    self.engine.close_long(date, self.symbol, close)
                    self._position = 0
                    self.log(f"止损平多 @ {close:.1f}")
            if short_pos and short_pos.volume > 0 and self._stop_price > 0:
                if close >= self._stop_price:
                    self.engine.close_short(date, self.symbol, close)
                    self._position = 0
                    self.log(f"止损平空 @ {close:.1f}")


class SimpleTrendStrategy(BaseFuturesStrategy):
    """
    简化趋势跟踪策略
    
    参数:
        channel_period: 通道周期 (默认20)
        atr_multiplier: ATR乘数 (默认2.0)
    """
    
    def __init__(self, params: Dict = None):
        super().__init__(params)
        self.channel_period = self.params.get("channel_period", 20)
        self.atr_period = self.params.get("atr_period", 14)
        self.atr_multiplier = self.params.get("atr_multiplier", 2.0)
        
        self._highs = []
        self._lows = []
        self._closes = []
        self._position = 0
    
    def on_start(self):
        self.log(f"趋势通道策略初始化: 通道={self.channel_period}, ATR={self.atr_multiplier}倍")
    
    def on_bar(self, bar: Dict):
        high = bar["high"]
        low = bar["low"]
        close = bar["close"]
        date = bar["date"]
        
        self._highs.append(high)
        self._lows.append(low)
        self._closes.append(close)
        
        if len(self._closes) < self.channel_period + 1:
            return
        
        # 唐奇安通道
        upper = pd.Series(self._highs).rolling(self.channel_period).max().iloc[-1]
        lower = pd.Series(self._lows).rolling(self.channel_period).min().iloc[-1]
        
        # ATR
        tr_values = []
        for i in range(-min(self.atr_period, len(self._closes)), 0):
            h = self._highs[i]
            l_val = self._lows[i]
            pc = self._closes[i - 1] if abs(i - 1) < len(self._closes) else self._closes[i]
            tr = max(h - l_val, abs(h - pc), abs(l_val - pc))
            tr_values.append(tr)
        atr = np.mean(tr_values) if tr_values else 0
        
        long_pos, short_pos = self.engine.get_position(self.symbol)
        
        # 突破上轨开多
        if close > upper:
            if short_pos and short_pos.volume > 0:
                self.engine.close_short(date, self.symbol, close)
            if long_pos is None or long_pos.volume == 0:
                self.engine.open_long(date, self.symbol, close, 1)
                self._position = 1
                self.log(f"突破上轨开多 @ {close:.1f}")
        
        # 突破下轨开空
        elif close < lower:
            if long_pos and long_pos.volume > 0:
                self.engine.close_long(date, self.symbol, close)
            if short_pos is None or short_pos.volume == 0:
                self.engine.open_short(date, self.symbol, close, 1)
                self._position = -1
                self.log(f"突破下轨开空 @ {close:.1f}")
        
        # 回归中轨平仓
        mid = (upper + lower) / 2
        if long_pos and long_pos.volume > 0 and close < mid:
            self.engine.close_long(date, self.symbol, close)
            self._position = 0
        if short_pos and short_pos.volume > 0 and close > mid:
            self.engine.close_short(date, self.symbol, close)
            self._position = 0
