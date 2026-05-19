"""
多时间框架CTA策略示例

策略:
  1. WeeklyFilteredMaStrategy — 周线趋势过滤 + 日线双均线交叉
  2. TripleTimeframeStrategy — 月线趋势 + 周线信号 + 日线入场

用法:
    from src.strategy.mtf_strategies import WeeklyFilteredMaStrategy
    strategy = WeeklyFilteredMaStrategy(params={...})
"""
from typing import Dict, Optional
import pandas as pd
import numpy as np
from loguru import logger

from src.strategy.futures_strategy import BaseFuturesStrategy
from src.strategy.mtf import MultiTimeframeMixin


def _calc_atr_from_lists(highs, lows, closes, period: int) -> float:
    """从价格列表计算 ATR（辅助函数）"""
    if len(closes) < period + 1:
        return 0.0
    tr_values = []
    for i in range(-period, 0):
        h = highs[i] if i < 0 else highs[-1]
        lo = lows[i] if i < 0 else lows[-1]
        pc = closes[i - 1] if abs(i - 1) < len(closes) else closes[i]
        tr = max(h - lo, abs(h - pc), abs(lo - pc))
        tr_values.append(tr)
    return float(np.mean(tr_values)) if tr_values else 0.0


def _risk_sizing(engine, close: float, atr_value: float,
                 atr_multiplier: float, max_risk_pct: float) -> int:
    """基于风险的仓位计算（辅助函数）"""
    risk_per_contract = atr_value * engine.contract_multiplier * atr_multiplier
    if risk_per_contract <= 0:
        return 0
    max_loss = engine.get_available_capital() * max_risk_pct
    volume = max(1, int(max_loss / risk_per_contract))
    margin_per = close * engine.contract_multiplier * engine.margin_rate
    max_by_margin = int(engine.get_available_capital() * 0.8 / margin_per)
    return min(volume, max_by_margin)


# ═══════════════════════════════════════════════════════════════
# 策略 1: 周线趋势过滤 + 日线双均线交叉
# ═══════════════════════════════════════════════════════════════

class WeeklyFilteredMaStrategy(MultiTimeframeMixin, BaseFuturesStrategy):
    """
    周线趋势过滤 + 日线双均线交叉 CTA 策略。

    核心理念:
      - 用周线判断大趋势方向（过滤）
      - 用日线双均线交叉作为入场/出场信号（择时）
      - 只在周线多头趋势中做多，周线空头趋势中做空

    周线多头条件: close > sma_20（周线收盘价在20周均线上方）
    周线空头条件: close < sma_40（周线收盘价在40周均线下方）
    中间震荡区: 不交易

    参数:
        fast_period: 日线快线周期 (默认10)
        slow_period: 日线慢线周期 (默认30)
        atr_period: ATR周期 (默认14)
        atr_multiplier: ATR止损乘数 (默认2.0)
        max_risk_pct: 单笔最大风险 (默认0.02)
        use_trailing_stop: 是否使用移动止损 (默认True)
        weekly_sma_fast: 周线快线 (默认20)
        weekly_sma_slow: 周线慢线 (默认40)
    """

    def __init__(self, params: Dict = None):
        super().__init__(params)
        self.fast_period = self.params.get("fast_period", 10)
        self.slow_period = self.params.get("slow_period", 30)
        self.atr_period = self.params.get("atr_period", 14)
        self.atr_multiplier = self.params.get("atr_multiplier", 2.0)
        self.max_risk_pct = self.params.get("max_risk_pct", 0.02)
        self.use_trailing_stop = self.params.get("use_trailing_stop", True)
        self.weekly_sma_fast = self.params.get("weekly_sma_fast", 20)
        self.weekly_sma_slow = self.params.get("weekly_sma_slow", 40)

        # 运行时状态
        self._prices = []
        self._highs = []
        self._lows = []
        self._position = 0  # 1=多, -1=空, 0=空仓
        self._entry_price = 0.0
        self._stop_price = 0.0

    # ── 属性（与 DualMaCrossStrategy 兼容） ──

    @property
    def fast_ma(self): return None
    @property
    def slow_ma(self): return None
    @property
    def atr(self): return None

    # ── 生命周期 ──

    def on_start(self):
        self.log(
            f"周线过滤+日线均线 CTA: "
            f"日线快线={self.fast_period}, 慢线={self.slow_period}, "
            f"周线快线={self.weekly_sma_fast}, 慢线={self.weekly_sma_slow}, "
            f"ATR止损={self.atr_multiplier}倍"
        )
        # 初始化多时间框架
        if self.data is not None and not self.data.empty:
            self.setup_mtf(self.data, timeframes=['weekly'])
            self.mtf.compute_indicators(
                'weekly',
                sma=[self.weekly_sma_fast, self.weekly_sma_slow],
            )

    def on_bar(self, bar):
        close = bar["close"]
        high = bar["high"]
        low = bar["low"]
        date = bar["date"]

        self._prices.append(close)
        self._highs.append(high)
        self._lows.append(low)

        if len(self._prices) < self.slow_period + 1:
            return

        # ── 周线趋势判断 ──
        weekly_close = self.mtf.get('weekly', date, 'close') if self.mtf else None
        weekly_sma20 = self.mtf.get('weekly', date, f'sma_{self.weekly_sma_fast}') if self.mtf else None
        weekly_sma40 = self.mtf.get('weekly', date, f'sma_{self.weekly_sma_slow}') if self.mtf else None

        trend_up = (weekly_close is not None and weekly_sma20 is not None
                    and weekly_close > weekly_sma20)
        trend_down = (weekly_close is not None and weekly_sma40 is not None
                      and weekly_close < weekly_sma40)
        trend_neutral = not trend_up and not trend_down

        # ── 日线指标 ──
        prices_series = pd.Series(self._prices)
        fast_ma = prices_series.rolling(self.fast_period).mean().iloc[-1]
        slow_ma = prices_series.rolling(self.slow_period).mean().iloc[-1]
        atr_value = max(_calc_atr_from_lists(self._highs, self._lows,
                        self._prices, self.atr_period), 1.0)

        long_pos, short_pos = self.engine.get_position(self.symbol)

        # ── 交易逻辑：周线多头 → 只做多 ──
        if trend_up:
            # 平空
            if short_pos and short_pos.volume > 0:
                self.engine.close_short(date, self.symbol, close)
                self._position = 0

            # 日线金叉开多
            if fast_ma > slow_ma:
                if long_pos is None or long_pos.volume == 0:
                    volume = _risk_sizing(self.engine, close, atr_value,
                                          self.atr_multiplier, self.max_risk_pct)
                    if volume > 0:
                        ok = self.engine.open_long(date, self.symbol, close, volume)
                        if ok:
                            self._position = 1
                            self._entry_price = close
                            self._stop_price = close - atr_value * self.atr_multiplier
                            self.log(f"周线多头+金叉 开多 {volume}手 @ {close:.1f}")

            # 移动止损
            if long_pos and long_pos.volume > 0 and self.use_trailing_stop:
                new_stop = close - atr_value * self.atr_multiplier
                self._stop_price = max(self._stop_price, new_stop)
                if close <= self._stop_price:
                    self.engine.close_long(date, self.symbol, close)
                    self._position = 0
                    self.log(f"移动止损平多 @ {close:.1f}")

        # ── 交易逻辑：周线空头 → 只做空 ──
        elif trend_down:
            # 平多
            if long_pos and long_pos.volume > 0:
                self.engine.close_long(date, self.symbol, close)
                self._position = 0

            # 日线死叉开空
            if fast_ma < slow_ma:
                if short_pos is None or short_pos.volume == 0:
                    volume = _risk_sizing(self.engine, close, atr_value,
                                          self.atr_multiplier, self.max_risk_pct)
                    if volume > 0:
                        ok = self.engine.open_short(date, self.symbol, close, volume)
                        if ok:
                            self._position = -1
                            self._entry_price = close
                            self._stop_price = close + atr_value * self.atr_multiplier
                            self.log(f"周线空头+死叉 开空 {volume}手 @ {close:.1f}")

            # 移动止损
            if short_pos and short_pos.volume > 0 and self.use_trailing_stop:
                new_stop = close + atr_value * self.atr_multiplier
                self._stop_price = min(self._stop_price or float('inf'), new_stop)
                if close >= self._stop_price:
                    self.engine.close_short(date, self.symbol, close)
                    self._position = 0
                    self.log(f"移动止损平空 @ {close:.1f}")

        # ── 震荡区：清仓观望 ──
        elif trend_neutral:
            if long_pos and long_pos.volume > 0:
                self.engine.close_long(date, self.symbol, close)
                self._position = 0
            if short_pos and short_pos.volume > 0:
                self.engine.close_short(date, self.symbol, close)
                self._position = 0

        # ── 止损检查（无信号时） ──
        else:
            if long_pos and long_pos.volume > 0 and self._stop_price > 0:
                if close <= self._stop_price:
                    self.engine.close_long(date, self.symbol, close)
                    self._position = 0
            if short_pos and short_pos.volume > 0 and self._stop_price > 0:
                if close >= self._stop_price:
                    self.engine.close_short(date, self.symbol, close)
                    self._position = 0


# ═══════════════════════════════════════════════════════════════
# 策略 2: 三时间框架策略（月线 + 周线 + 日线）
# ═══════════════════════════════════════════════════════════════

class TripleTimeframeStrategy(MultiTimeframeMixin, BaseFuturesStrategy):
    """
    三时间框架 CTA 策略。

    核心理念:
      - 月线: 确定长期趋势方向（最长周期）
      - 周线: 确认中周期信号（MACD）
      - 日线: 入场择时（价格回调至均线 + ATR止损）

    月线看方向: close > sma_12（~年线）→ 多头市场
    周线等信号: MACD > signal → 多头信号
    日线找入场: 回调至 sma_20 附近且 RSI > 50 → 入场做多

    参数:
        atr_multiplier: ATR止损乘数 (默认2.0)
        max_risk_pct: 单笔最大风险 (默认0.02)
        use_trailing_stop: 是否使用移动止损 (默认True)
    """

    def __init__(self, params: Dict = None):
        super().__init__(params)
        self.atr_multiplier = self.params.get("atr_multiplier", 2.0)
        self.max_risk_pct = self.params.get("max_risk_pct", 0.02)
        self.use_trailing_stop = self.params.get("use_trailing_stop", True)
        self.daily_sma_period = self.params.get("daily_sma_period", 20)
        self.rsi_period = self.params.get("rsi_period", 14)

        # 运行时状态
        self._prices = []
        self._highs = []
        self._lows = []
        self._position = 0
        self._entry_price = 0.0
        self._stop_price = 0.0

    def on_start(self):
        self.log(
            f"三时间框架 CTA: "
            f"月线方向+周线MACD+日线回调, "
            f"ATR止损={self.atr_multiplier}倍"
        )
        if self.data is not None and not self.data.empty:
            self.setup_mtf(self.data, timeframes=['weekly', 'monthly'])
            self.mtf.compute_indicators('monthly', sma=[12])
            self.mtf.compute_indicators('weekly', macd=(12, 26, 9))

    def on_bar(self, bar):
        close = bar["close"]
        high = bar["high"]
        low = bar["low"]
        date = bar["date"]

        self._prices.append(close)
        self._highs.append(high)
        self._lows.append(low)

        if len(self._prices) < self.daily_sma_period + 5:
            return

        # ── 三时间框架信号 ──
        monthly_close = self.mtf.get('monthly', date, 'close') if self.mtf else None
        monthly_sma12 = self.mtf.get('monthly', date, 'sma_12') if self.mtf else None
        weekly_macd = self.mtf.get('weekly', date, 'macd') if self.mtf else None
        weekly_macd_signal = self.mtf.get('weekly', date, 'macd_signal') if self.mtf else None

        # 日线指标
        prices_series = pd.Series(self._prices)
        daily_sma = prices_series.rolling(self.daily_sma_period).mean().iloc[-1]
        atr_value = max(_calc_atr_from_lists(self._highs, self._lows,
                        self._prices, 14), 1.0)

        # RSI
        rsi_series = pd.Series(self._prices)
        gains = rsi_series.diff().clip(lower=0)
        losses = -rsi_series.diff().clip(upper=0)
        avg_gain = gains.rolling(self.rsi_period).mean().iloc[-1]
        avg_loss = losses.rolling(self.rsi_period).mean().iloc[-1]
        rsi = 50.0
        if avg_loss > 0:
            rs = avg_gain / avg_loss
            rsi = 100 - 100 / (1 + rs)

        # 信号合成
        bull_market = (monthly_close is not None and monthly_sma12 is not None
                       and monthly_close > monthly_sma12)
        weekly_bull = (weekly_macd is not None and weekly_macd_signal is not None
                       and weekly_macd > weekly_macd_signal)

        long_pos, short_pos = self.engine.get_position(self.symbol)

        # ── 多头入场条件 ──
        # 月线多头 + 周线MACD多头 + 日线回调至均线附近 + RSI > 50
        if bull_market and weekly_bull:
            # 平空
            if short_pos and short_pos.volume > 0:
                self.engine.close_short(date, self.symbol, close)
                self._position = 0

            # 回调入场: close 在均线附近（±1 ATR）
            near_sma = abs(close - daily_sma) < atr_value * 1.0
            if near_sma and rsi > 50:
                if long_pos is None or long_pos.volume == 0:
                    volume = _risk_sizing(self.engine, close, atr_value,
                                          self.atr_multiplier, self.max_risk_pct)
                    if volume > 0:
                        ok = self.engine.open_long(date, self.symbol, close, volume)
                        if ok:
                            self._position = 1
                            self._entry_price = close
                            self._stop_price = close - atr_value * self.atr_multiplier
                            self.log(f"三TF多头入场 {volume}手 @ {close:.1f}")

            # 移动止损
            if long_pos and long_pos.volume > 0 and self.use_trailing_stop:
                new_stop = close - atr_value * self.atr_multiplier
                self._stop_price = max(self._stop_price, new_stop)
                if close <= self._stop_price:
                    self.engine.close_long(date, self.symbol, close)
                    self._position = 0
                    self.log(f"三TF平多 @ {close:.1f}")

        # ── 空头入场条件 ──
        elif not bull_market and not weekly_bull:
            if long_pos and long_pos.volume > 0:
                self.engine.close_long(date, self.symbol, close)
                self._position = 0

            near_sma = abs(close - daily_sma) < atr_value * 1.0
            if near_sma and rsi < 50:
                if short_pos is None or short_pos.volume == 0:
                    volume = _risk_sizing(self.engine, close, atr_value,
                                          self.atr_multiplier, self.max_risk_pct)
                    if volume > 0:
                        ok = self.engine.open_short(date, self.symbol, close, volume)
                        if ok:
                            self._position = -1
                            self._entry_price = close
                            self._stop_price = close + atr_value * self.atr_multiplier
                            self.log(f"三TF空头入场 {volume}手 @ {close:.1f}")

            if short_pos and short_pos.volume > 0 and self.use_trailing_stop:
                new_stop = close + atr_value * self.atr_multiplier
                self._stop_price = min(self._stop_price or float('inf'), new_stop)
                if close >= self._stop_price:
                    self.engine.close_short(date, self.symbol, close)
                    self._position = 0
                    self.log(f"三TF平空 @ {close:.1f}")

        # ── 信号不一致 → 清仓 ──
        else:
            if long_pos and long_pos.volume > 0:
                self.engine.close_long(date, self.symbol, close)
                self._position = 0
            if short_pos and short_pos.volume > 0:
                self.engine.close_short(date, self.symbol, close)
                self._position = 0
