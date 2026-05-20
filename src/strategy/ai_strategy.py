"""
AI 预测策略。

在实盘/回测环境中加载预训练 ML 模型，在每个 bar 上计算因子 → 标准化 → 预测 → 生成信号。

用法:
    strategy = MLTradingStrategy(params={
        "model_path": "data/models/RB_xgb_20260520.joblib",
        "score_threshold": 0.6,
    })
"""
from typing import Dict, Optional
import numpy as np
from loguru import logger

from .futures_strategy import BaseFuturesStrategy


class MLTradingStrategy(BaseFuturesStrategy):
    """基于 ML 模型预测的期货交易策略。

    参数:
        model_path: 预训练模型 .joblib 文件路径
        score_threshold: 信号概率阈值 (默认 0.6)
        lookback: 因子计算最小窗口 (默认 60)
        stop_loss_atr: ATR 止损乘数 (默认 2.0)
        use_short: 是否允许做空 (默认 True)
    """

    def __init__(self, params: Dict = None):
        super().__init__(params)
        self.model_path = self.params.get("model_path", "")
        self.score_threshold = self.params.get("score_threshold", 0.6)
        self.lookback = self.params.get("lookback", 60)
        self.stop_loss_atr = self.params.get("stop_loss_atr", 2.0)
        self.use_short = self.params.get("use_short", True)

        # 运行时状态
        self._pipeline = None
        self._position = 0       # 1=多, -1=空, 0=空仓
        self._entry_price = 0.0
        self._stop_price = 0.0
        self._prices = []
        self._highs = []
        self._lows = []
        self._volumes = []
        self._data_buffer = None  # DataFrame 缓存

    def on_start(self):
        from src.ai.pipeline import AIPipeline

        if not self.model_path:
            raise ValueError("MLTradingStrategy 需要 model_path 参数")

        # 全局数据由引擎通过 self.data 注入（完整的回测 DataFame）
        self._pipeline = AIPipeline()
        logger.info(f"MLTradingStrategy 加载模型: {self.model_path}")
        logger.info(f"  概率阈值: {self.score_threshold}")
        logger.info(f"  做空: {'允许' if self.use_short else '禁止'}")

    def on_bar(self, bar: Dict):
        close = bar["close"]
        high = bar["high"]
        low = bar["low"]
        volume = bar.get("volume", 0)
        date = bar.get("date", bar.get("datetime"))

        # 缓存最新 bar 到缓冲区
        self._prices.append(close)
        self._highs.append(high)
        self._lows.append(low)
        self._volumes.append(volume)

        # 需要足够数据计算因子
        if len(self._prices) < self.lookback:
            return

        # 构建当前 DataFrame（从完整 data 切片或从 buffer 构建）
        latest_idx = len(self._prices) - 1
        if self.data is not None and len(self.data) >= latest_idx + 1:
            # 优先从完整数据切片（回测模式）
            df_window = self.data.iloc[:latest_idx + 1]
        else:
            # 从 buffer 构建（实盘模式）
            import pandas as pd
            df_window = pd.DataFrame({
                "open": self._highs,  # 近似
                "high": self._highs,
                "low": self._lows,
                "close": self._prices,
                "volume": self._volumes,
            })

        # ML 预测
        try:
            probas = self._pipeline.predict_proba(df_window, self.model_path)
            preds = self._pipeline.predict(df_window, self.model_path)
            max_proba = probas.max(axis=1)
            latest_pred = preds[-1]
            latest_conf = max_proba[-1]
        except Exception as e:
            logger.warning(f"ML 预测失败: {e}")
            return

        # 获取当前持仓
        long_pos, short_pos = self.engine.get_position(self.symbol)

        # ─── 信号判断 ───

        # 信号 = 做多 (预测涨且概率达标)
        if latest_pred == 1 and latest_conf >= self.score_threshold:
            # 平空
            if short_pos and short_pos.volume > 0:
                self.engine.close_short(date, self.symbol, close)
                self._position = 0

            # 开多
            if long_pos is None or long_pos.volume == 0:
                volume = self._calc_volume(close)
                if volume > 0:
                    success = self.engine.open_long(date, self.symbol, close, volume)
                    if success:
                        self._position = 1
                        self._entry_price = close
                        self._stop_price = close - self._calc_atr() * self.stop_loss_atr
                        self.log(f"ML 开多 {volume}手 @ {close:.1f}, "
                                 f"置信={latest_conf:.2f}")

        # 信号 = 做空
        elif latest_pred == -1 and latest_conf >= self.score_threshold and self.use_short:
            # 平多
            if long_pos and long_pos.volume > 0:
                self.engine.close_long(date, self.symbol, close)
                self._position = 0

            # 开空
            if short_pos is None or short_pos.volume == 0:
                volume = self._calc_volume(close)
                if volume > 0:
                    success = self.engine.open_short(date, self.symbol, close, volume)
                    if success:
                        self._position = -1
                        self._entry_price = close
                        self._stop_price = close + self._calc_atr() * self.stop_loss_atr
                        self.log(f"ML 开空 {volume}手 @ {close:.1f}, "
                                 f"置信={latest_conf:.2f}")

        # 止损检查
        if self._stop_price > 0:
            if self._position == 1 and long_pos and long_pos.volume > 0:
                if close <= self._stop_price:
                    self.engine.close_long(date, self.symbol, close)
                    self._position = 0
                    self.log(f"止损平多 @ {close:.1f}")
            elif self._position == -1 and short_pos and short_pos.volume > 0:
                if close >= self._stop_price:
                    self.engine.close_short(date, self.symbol, close)
                    self._position = 0
                    self.log(f"止损平空 @ {close:.1f}")

    def _calc_volume(self, price: float) -> int:
        """基于风险计算开仓手数。"""
        if not hasattr(self.engine, "contract_multiplier"):
            return 1
        atr = self._calc_atr()
        risk_per = atr * self.engine.contract_multiplier * self.stop_loss_atr
        if risk_per <= 0:
            return 1
        max_loss = self.engine.get_available_capital() * 0.02
        volume = max(1, int(max_loss / risk_per))
        # 按保证金限制
        margin_per = price * self.engine.contract_multiplier * self.engine.margin_rate
        if margin_per > 0:
            max_by_margin = int(self.engine.get_available_capital() * 0.8 / margin_per)
            volume = min(volume, max_by_margin)
        return max(volume, 1)

    def _calc_atr(self) -> float:
        """简易 ATR 计算。"""
        if len(self._prices) < 15:
            return 1.0
        tr_values = []
        for i in range(-14, 0):
            h = self._highs[i]
            l_val = self._lows[i]
            pc = self._prices[i - 1] if abs(i - 1) < len(self._prices) else self._prices[i]
            tr = max(h - l_val, abs(h - pc), abs(l_val - pc))
            tr_values.append(tr)
        return float(np.mean(tr_values)) if tr_values else 1.0
