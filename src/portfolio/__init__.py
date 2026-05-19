"""
投资组合模块

提供资金分配策略和组合回测聚合。
"""
from .allocator import (
    AllocationStrategy,
    EqualWeightAllocator,
    RiskParityAllocator,
    FixedWeightAllocator,
)
from .portfolio import (
    PortfolioResult,
    aggregate_results,
    run_portfolio_backtest,
)

__all__ = [
    "AllocationStrategy",
    "EqualWeightAllocator",
    "RiskParityAllocator",
    "FixedWeightAllocator",
    "PortfolioResult",
    "aggregate_results",
    "run_portfolio_backtest",
]
