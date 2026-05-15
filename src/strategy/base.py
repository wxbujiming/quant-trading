"""
策略基类
所有策略都需要继承此类
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum
import pandas as pd
import numpy as np


class Signal(Enum):
    """交易信号"""
    BUY = 1
    SELL = -1
    HOLD = 0


@dataclass
class Position:
    """持仓信息"""
    symbol: str
    quantity: float
    avg_price: float
    current_price: float = 0.0
    
    @property
    def market_value(self) -> float:
        """市值"""
        return self.quantity * self.current_price
    
    @property
    def profit_loss(self) -> float:
        """浮动盈亏"""
        return (self.current_price - self.avg_price) * self.quantity
    
    @property
    def profit_pct(self) -> float:
        """盈亏比例"""
        if self.avg_price == 0:
            return 0.0
        return (self.current_price - self.avg_price) / self.avg_price


class BaseStrategy(ABC):
    """
    策略基类
    
    所有策略需要实现:
    - init(): 初始化
    - next(): 每个bar调用一次，生成交易信号
    """
    
    def __init__(self, params: Dict = None):
        """
        初始化策略
        
        Args:
            params: 策略参数
        """
        self.params = params or {}
        self.data = None
        self.positions: Dict[str, Position] = {}
        self.cash = 0.0
        self.trades = []
        self.signals = []
        
    def set_data(self, data: pd.DataFrame):
        """设置数据"""
        self.data = data
        
    def init(self):
        """
        初始化策略
        子类可重写此方法
        """
        pass
    
    @abstractmethod
    def next(self, bar: pd.Series) -> Signal:
        """
        每个bar调用一次
        
        Args:
            bar: 当前的K线数据
            
        Returns:
            交易信号
        """
        pass
    
    def buy(self, symbol: str, price: float, quantity: float):
        """买入"""
        if symbol in self.positions:
            # 加仓
            pos = self.positions[symbol]
            total_quantity = pos.quantity + quantity
            pos.avg_price = (pos.avg_price * pos.quantity + price * quantity) / total_quantity
            pos.quantity = total_quantity
        else:
            # 新建仓位
            self.positions[symbol] = Position(
                symbol=symbol,
                quantity=quantity,
                avg_price=price
            )
        
        self.cash -= price * quantity
        self.trades.append({
            'type': 'BUY',
            'symbol': symbol,
            'price': price,
            'quantity': quantity
        })
    
    def sell(self, symbol: str, price: float, quantity: float):
        """卖出"""
        if symbol not in self.positions:
            return
            
        pos = self.positions[symbol]
        if quantity > pos.quantity:
            quantity = pos.quantity
            
        profit = (price - pos.avg_price) * quantity
        self.cash += price * quantity
        
        pos.quantity -= quantity
        if pos.quantity <= 0:
            del self.positions[symbol]
            
        self.trades.append({
            'type': 'SELL',
            'symbol': symbol,
            'price': price,
            'quantity': quantity,
            'profit': profit
        })
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """获取持仓"""
        return self.positions.get(symbol)
    
    def get_total_value(self) -> float:
        """获取总资产"""
        total = self.cash
        for pos in self.positions.values():
            total += pos.market_value
        return total
    
    def log(self, msg: str):
        """日志输出"""
        print(f"[{self.__class__.__name__}] {msg}")
