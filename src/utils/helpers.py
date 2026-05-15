"""
工具函数
"""
from typing import List, Tuple
import pandas as pd
import numpy as np


def calculate_returns(prices: pd.Series) -> pd.Series:
    """计算收益率"""
    return prices.pct_change()


def calculate_cumulative_returns(returns: pd.Series) -> pd.Series:
    """计算累计收益率"""
    return (1 + returns).cumprod() - 1


def calculate_max_drawdown(values: pd.Series) -> float:
    """计算最大回撤"""
    cummax = values.cummax()
    drawdown = (cummax - values) / cummax
    return drawdown.max()


def calculate_sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.03) -> float:
    """
    计算夏普比率
    
    Args:
        returns: 日收益率序列
        risk_free_rate: 无风险年化收益率
    """
    excess_returns = returns - risk_free_rate / 252
    if excess_returns.std() == 0:
        return 0
    return excess_returns.mean() / excess_returns.std() * np.sqrt(252)


def calculate_volatility(returns: pd.Series) -> float:
    """计算年化波动率"""
    return returns.std() * np.sqrt(252)


def calculate_sortino_ratio(returns: pd.Series, risk_free_rate: float = 0.03) -> float:
    """计算索提诺比率"""
    excess_returns = returns - risk_free_rate / 252
    downside_returns = excess_returns[excess_returns < 0]
    if len(downside_returns) == 0 or downside_returns.std() == 0:
        return 0
    return excess_returns.mean() / downside_returns.std() * np.sqrt(252)


def format_number(value: float, decimal: int = 2) -> str:
    """格式化数字"""
    return f"{value:,.{decimal}f}"


def format_percentage(value: float, decimal: int = 2) -> str:
    """格式化百分比"""
    return f"{value:.{decimal}%}"
