"""
套利策略模块

提供:
- BaseArbitrageStrategy — 策略基类
- ZScoreArbitrageStrategy — Z-Score 均值回归套利
"""
from typing import Dict, Optional
from abc import ABC, abstractmethod
import pandas as pd
import numpy as np
from loguru import logger


class BaseArbitrageStrategy(ABC):
    """套利策略基类"""

    def __init__(self, params: Optional[Dict] = None):
        self.params = params or {}
        self.engine = None  # ArbitrageBacktestEngine，回测时注入
        self.name = self.__class__.__name__

    def on_start(self):
        """策略初始化（可重写）"""
        pass

    @abstractmethod
    def on_spread_bar(self, bar: Dict):
        """
        每根价差 K 线回调。

        bar 包含:
            date, leg1_open/high/low/close/settle/volume,
            leg2_open/high/low/close/settle/volume,
            spread, zscore, bb_upper, bb_middle, bb_lower
        """
        raise NotImplementedError

    def log(self, msg: str):
        logger.info(f"[{self.name}] {msg}")

    # ──────────────── 便捷下单方法 ────────────────

    def open_long(self, leg: int, date, price, volume: int, contract=""):
        return self.engine.arb_open_long(leg, date, price, volume, contract)

    def open_short(self, leg: int, date, price, volume: int, contract=""):
        return self.engine.arb_open_short(leg, date, price, volume, contract)

    def close_long(self, leg: int, date, price, volume=None, is_today=False, contract=""):
        return self.engine.arb_close_long(leg, date, price, volume, is_today, contract)

    def close_short(self, leg: int, date, price, volume=None, is_today=False, contract=""):
        return self.engine.arb_close_short(leg, date, price, volume, is_today, contract)


# ──────────────── Z-Score 套利策略 ────────────────

class ZScoreArbitrageStrategy(BaseArbitrageStrategy):
    """
    Z-Score 均值回归套利策略。

    当 |zscore| > entry_z 时入场：
      - zscore > +entry_z → short spread（空 leg1 + 多 leg2）
      - zscore < -entry_z → long spread（多 leg1 + 空 leg2）
    当 |zscore| < exit_z 时出场（均值回归平仓）
    当 |zscore| > stop_z 时止损出场

    参数:
        entry_z (float): 入场阈值，默认 2.0
        exit_z (float): 出场阈值，默认 0.5
        stop_z (float): 止损阈值，默认 3.5
        trade_volume (int): 固定交易手数，默认 1
        position_ratio (float): 腿2 相对于腿1 的手数比例, 默认 1.0
        max_volume (int): 单腿最大手数限制，默认 10
        cooldown_bars (int): 出场后等待多少根K线再入场, 默认 3
    """

    def __init__(self, params: Optional[Dict] = None):
        super().__init__(params)
        self._spread_direction = 0   # +1=long spread, -1=short spread, 0=no position
        self._entry_z = 0.0
        self._cooldown_counter = 0

    def on_start(self):
        self.entry_z = self.params.get("entry_z", 2.0)
        self.exit_z = self.params.get("exit_z", 0.5)
        self.stop_z = self.params.get("stop_z", 3.5)
        self.trade_volume = self.params.get("trade_volume", 1)
        self.position_ratio = self.params.get("position_ratio", 1.0)
        self.max_volume = self.params.get("max_volume", 10)
        self.cooldown_bars = self.params.get("cooldown_bars", 3)

        logger.info(f"[ZScoreArbitrage] 参数: "
                    f"entry_z={self.entry_z}, exit_z={self.exit_z}, "
                    f"stop_z={self.stop_z}, volume={self.trade_volume}")

    def on_spread_bar(self, bar: Dict):
        zscore = bar.get("zscore", 0)
        date = bar["date"]

        # 跳过 zscore NaN（窗口期）
        if pd.isna(zscore) or np.isinf(zscore):
            return

        # 冷却计数
        if self._cooldown_counter > 0:
            self._cooldown_counter -= 1

        # 检查当前仓位状态
        leg1_long, leg1_short = self.engine.get_position(1)
        leg2_long, leg2_short = self.engine.get_position(2)
        has_position = self._has_spread_position(leg1_long, leg1_short,
                                                  leg2_long, leg2_short)

        if not has_position:
            self._handle_entry(zscore, date, bar)
        else:
            self._handle_exit(zscore, date, bar,
                              leg1_long, leg1_short, leg2_long, leg2_short)

    # ──────────────── 内部逻辑 ────────────────

    def _has_spread_position(self, l1l, l1s, l2l, l2s) -> bool:
        """检查是否持有价差仓位"""
        if self._spread_direction == 1:  # long spread: 多leg1 + 空leg2
            return (l1l is not None and l1l.volume > 0
                    and l2s is not None and l2s.volume > 0)
        elif self._spread_direction == -1:  # short spread: 空leg1 + 多leg2
            return (l1s is not None and l1s.volume > 0
                    and l2l is not None and l2l.volume > 0)
        return False

    def _handle_entry(self, zscore: float, date, bar: Dict):
        """处理入场信号"""
        if self._cooldown_counter > 0:
            return

        vol1 = min(self.trade_volume, self.max_volume)
        vol2 = min(int(vol1 * self.position_ratio), self.max_volume)

        if zscore > self.entry_z:
            # spread 过高 → short spread: 空 leg1 + 多 leg2
            ok1 = self.open_short(1, date, bar["leg1_close"], vol1)
            ok2 = self.open_long(2, date, bar["leg2_close"], vol2)
            if ok1 and ok2:
                self._spread_direction = -1
                self._entry_z = zscore
                self.log(f"入场 SHORT SPREAD: 空{vol1}手 leg1 + 多{vol2}手 leg2 "
                         f"(zscore={zscore:.2f})")

        elif zscore < -self.entry_z:
            # spread 过低 → long spread: 多 leg1 + 空 leg2
            ok1 = self.open_long(1, date, bar["leg1_close"], vol1)
            ok2 = self.open_short(2, date, bar["leg2_close"], vol2)
            if ok1 and ok2:
                self._spread_direction = 1
                self._entry_z = zscore
                self.log(f"入场 LONG SPREAD: 多{vol1}手 leg1 + 空{vol2}手 leg2 "
                         f"(zscore={zscore:.2f})")

    def _handle_exit(self, zscore: float, date, bar: Dict,
                     l1l, l1s, l2l, l2s):
        """处理出场信号"""
        should_exit = False
        reason = ""

        if self._spread_direction == 1:  # long spread
            if zscore <= self.exit_z:
                should_exit = True
                reason = "均值回归平仓"
            elif abs(zscore) >= self.stop_z:
                should_exit = True
                reason = f"止损平仓 (|zscore|={abs(zscore):.2f} >= {self.stop_z})"

        elif self._spread_direction == -1:  # short spread
            if zscore >= -self.exit_z:
                should_exit = True
                reason = "均值回归平仓"
            elif abs(zscore) >= self.stop_z:
                should_exit = True
                reason = f"止损平仓 (|zscore|={abs(zscore):.2f} >= {self.stop_z})"

        if should_exit:
            self.close_long(1, date, bar["leg1_close"])
            self.close_short(1, date, bar["leg1_close"])
            self.close_long(2, date, bar["leg2_close"])
            self.close_short(2, date, bar["leg2_close"])
            self._spread_direction = 0
            self._cooldown_counter = self.cooldown_bars
            self._entry_z = 0
            self.log(f"出场 {reason} (zscore={zscore:.2f})")
