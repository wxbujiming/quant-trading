"""
资金分配策略

定义如何将资金分配到不同品种上。

支持:
  - EqualWeightAllocator — 等权分配
  - RiskParityAllocator — 风险平价（基于历史波动率）
  - FixedWeightAllocator — 固定权重分配
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import pandas as pd
import numpy as np


class AllocationStrategy(ABC):
    """资金分配策略基类"""

    @abstractmethod
    def allocate(self, symbols: List[str], total_capital: float,
                 data_dict: Optional[Dict[str, pd.DataFrame]] = None) -> Dict[str, float]:
        """
        分配资金到各品种。

        Args:
            symbols: 品种列表
            total_capital: 总资金
            data_dict: 可选，各品种的行情数据（用于波动率等计算）

        Returns:
            {symbol: allocated_capital} 映射
        """
        pass


class EqualWeightAllocator(AllocationStrategy):
    """等权分配 — 所有品种获得相同资金"""

    def allocate(self, symbols: List[str], total_capital: float,
                 data_dict: Optional[Dict[str, pd.DataFrame]] = None) -> Dict[str, float]:
        per = total_capital / max(len(symbols), 1)
        return {s: per for s in symbols}


class FixedWeightAllocator(AllocationStrategy):
    """固定权重分配 — 按指定权重分配资金"""

    def __init__(self, weights: Dict[str, float]):
        """
        Args:
            weights: {symbol: weight}，权重之和应为 1.0
        """
        total = sum(weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"权重之和应为 1.0，当前为 {total}")
        self._weights = weights

    def allocate(self, symbols: List[str], total_capital: float,
                 data_dict: Optional[Dict[str, pd.DataFrame]] = None) -> Dict[str, float]:
        return {s: total_capital * self._weights.get(s, 0.0) for s in symbols}


class RiskParityAllocator(AllocationStrategy):
    """
    风险平价分配 — 各品种的风险贡献相等。

    使用历史波动率的倒数作为权重基础，使各品种对组合的风险贡献相近。
    波动率越高，分配资金越少。
    """

    def __init__(self, window: int = 60):
        """
        Args:
            window: 波动率计算窗口（日线周期数，默认60 = ~3个月）
        """
        self.window = window

    def allocate(self, symbols: List[str], total_capital: float,
                 data_dict: Optional[Dict[str, pd.DataFrame]] = None) -> Dict[str, float]:
        if data_dict is None:
            raise ValueError("风险平价需要 data_dict 来计算波动率")

        vols = {}
        for s in symbols:
            df = data_dict.get(s)
            if df is None or len(df) < self.window:
                vols[s] = 1.0  # 数据不足时使用默认波动率
                continue
            close = df['close'] if 'close' in df.columns else df.iloc[:, 3]
            returns = close.pct_change().dropna()
            vol = returns.tail(self.window).std()
            vols[s] = max(vol, 0.001)  # 避免除零

        # 风险平价：权重与波动率成反比
        inv_vols = np.array([1.0 / v for v in vols.values()])
        weights = inv_vols / inv_vols.sum()

        allocations = {}
        for (s, _), w in zip(vols.items(), weights):
            allocations[s] = total_capital * w

        return allocations
