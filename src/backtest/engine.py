"""
回测引擎
"""
from typing import Dict, List, Optional, Type
from dataclasses import dataclass, field
from datetime import datetime
import pandas as pd
import numpy as np
from loguru import logger

from src.strategy.base import BaseStrategy, Signal


@dataclass
class TradeRecord:
    """交易记录"""
    date: datetime
    symbol: str
    action: str  # BUY/SELL
    price: float
    quantity: float
    amount: float
    commission: float
    profit: float = 0.0


@dataclass
class BacktestResult:
    """回测结果"""
    initial_cash: float
    final_value: float
    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float
    total_trades: int
    profit_trades: int
    loss_trades: int
    trades: List[TradeRecord] = field(default_factory=list)
    daily_values: pd.DataFrame = None


class BacktestEngine:
    """
    回测引擎
    
    支持事件驱动回测和绩效分析
    """
    
    def __init__(
        self,
        initial_cash: float = 100000.0,
        commission: float = 0.0003,  # 万三
        slippage: float = 0.0001,    # 万一
        stamp_duty: float = 0.001,   # 千一印花税(卖出)
    ):
        """
        初始化回测引擎
        
        Args:
            initial_cash: 初始资金
            commission: 手续费率
            slippage: 滑点
            stamp_duty: 印花税率
        """
        self.initial_cash = initial_cash
        self.commission = commission
        self.slippage = slippage
        self.stamp_duty = stamp_duty
        
        # 运行时状态
        self.cash = initial_cash
        self.positions: Dict[str, float] = {}  # symbol -> quantity
        self.avg_prices: Dict[str, float] = {}  # symbol -> avg_price
        self.trades: List[TradeRecord] = []
        self.daily_values: List[Dict] = []
        
        logger.info(f"回测引擎初始化: 初始资金={initial_cash}, 手续费率={commission}")
    
    def run(
        self,
        data: pd.DataFrame,
        strategy: BaseStrategy,
        symbol: str = None,
    ) -> BacktestResult:
        """
        运行回测
        
        Args:
            data: 行情数据
            strategy: 策略实例
            symbol: 股票代码(单只股票时)
            
        Returns:
            回测结果
        """
        logger.info("开始回测...")
        
        # 重置状态
        self.cash = self.initial_cash
        self.positions = {}
        self.avg_prices = {}
        self.trades = []
        self.daily_values = []
        
        # 设置策略数据
        strategy.data = data
        strategy.init()
        
        symbol = symbol or data.get('symbol', ['unknown'])[0] if 'symbol' in data.columns else 'unknown'
        
        # 遍历数据
        for i, (date, row) in enumerate(data.iterrows()):
            # 生成信号
            signal = strategy.next(row)
            
            # 执行交易
            if signal == Signal.BUY:
                self._execute_buy(date, symbol, row['close'])
            elif signal == Signal.SELL:
                self._execute_sell(date, symbol, row['close'])
            
            # 记录每日资产
            total_value = self._calculate_total_value(row['close'])
            self.daily_values.append({
                'date': date,
                'cash': self.cash,
                'position': self.positions.get(symbol, 0),
                'price': row['close'],
                'total_value': total_value
            })
        
        # 计算结果
        result = self._calculate_result(data)
        logger.success(f"回测完成: 总收益率={result.total_return:.2%}")
        
        return result
    
    def _execute_buy(self, date, symbol: str, price: float):
        """执行买入"""
        # 计算可买入数量(按手买入，1手=100股)
        available = self.cash * 0.95  # 留5%现金
        actual_price = price * (1 + self.slippage)  # 滑点
        max_quantity = int(available / actual_price / 100) * 100
        
        if max_quantity <= 0:
            return
        
        # 计算费用
        amount = max_quantity * actual_price
        commission_fee = max(amount * self.commission, 5)  # 最低5元
        
        # 更新状态
        self.cash -= (amount + commission_fee)
        
        if symbol in self.positions:
            old_qty = self.positions[symbol]
            old_avg = self.avg_prices[symbol]
            new_avg = (old_qty * old_avg + amount) / (old_qty + max_quantity)
            self.positions[symbol] += max_quantity
            self.avg_prices[symbol] = new_avg
        else:
            self.positions[symbol] = max_quantity
            self.avg_prices[symbol] = actual_price
        
        # 记录交易
        self.trades.append(TradeRecord(
            date=date,
            symbol=symbol,
            action='BUY',
            price=actual_price,
            quantity=max_quantity,
            amount=amount,
            commission=commission_fee
        ))
        
        logger.debug(f"{date.date()} 买入 {symbol}: {max_quantity}股 @ {actual_price:.2f}")
    
    def _execute_sell(self, date, symbol: str, price: float):
        """执行卖出"""
        if symbol not in self.positions or self.positions[symbol] <= 0:
            return
        
        quantity = self.positions[symbol]
        actual_price = price * (1 - self.slippage)  # 滑点
        
        # 计算费用
        amount = quantity * actual_price
        commission_fee = max(amount * self.commission, 5)
        stamp_fee = amount * self.stamp_duty  # 印花税
        
        # 计算盈亏
        cost = quantity * self.avg_prices[symbol]
        profit = amount - cost - commission_fee - stamp_fee
        
        # 更新状态
        self.cash += (amount - commission_fee - stamp_fee)
        self.positions[symbol] = 0
        
        # 记录交易
        self.trades.append(TradeRecord(
            date=date,
            symbol=symbol,
            action='SELL',
            price=actual_price,
            quantity=quantity,
            amount=amount,
            commission=commission_fee + stamp_fee,
            profit=profit
        ))
        
        logger.debug(f"{date.date()} 卖出 {symbol}: {quantity}股 @ {actual_price:.2f}, 盈亏={profit:.2f}")
    
    def _calculate_total_value(self, current_price: float) -> float:
        """计算总资产"""
        total = self.cash
        for symbol, quantity in self.positions.items():
            if quantity > 0:
                total += quantity * current_price
        return total
    
    def _calculate_result(self, data: pd.DataFrame) -> BacktestResult:
        """计算回测结果"""
        df = pd.DataFrame(self.daily_values)
        
        # 最终资产
        final_value = df['total_value'].iloc[-1] if len(df) > 0 else self.initial_cash
        
        # 总收益率
        total_return = (final_value - self.initial_cash) / self.initial_cash
        
        # 年化收益率
        if len(df) > 1:
            days = (df['date'].iloc[-1] - df['date'].iloc[0]).days
            annual_return = (1 + total_return) ** (365 / max(days, 1)) - 1
        else:
            annual_return = 0
        
        # 最大回撤
        df['cummax'] = df['total_value'].cummax()
        df['drawdown'] = (df['cummax'] - df['total_value']) / df['cummax']
        max_drawdown = df['drawdown'].max()
        
        # 夏普比率
        if len(df) > 1:
            df['daily_return'] = df['total_value'].pct_change()
            sharpe_ratio = df['daily_return'].mean() / df['daily_return'].std() * np.sqrt(252)
        else:
            sharpe_ratio = 0
        
        # 交易统计
        sell_trades = [t for t in self.trades if t.action == 'SELL']
        profit_trades = [t for t in sell_trades if t.profit > 0]
        loss_trades = [t for t in sell_trades if t.profit <= 0]
        win_rate = len(profit_trades) / len(sell_trades) if sell_trades else 0
        
        return BacktestResult(
            initial_cash=self.initial_cash,
            final_value=final_value,
            total_return=total_return,
            annual_return=annual_return,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            win_rate=win_rate,
            total_trades=len(self.trades),
            profit_trades=len(profit_trades),
            loss_trades=len(loss_trades),
            trades=self.trades,
            daily_values=df
        )
    
    def print_result(self, result: BacktestResult):
        """打印回测结果"""
        print("\n" + "=" * 60)
        print("                    回测结果报告")
        print("=" * 60)
        print(f"初始资金:     {result.initial_cash:,.2f}")
        print(f"最终资产:     {result.final_value:,.2f}")
        print(f"总收益率:     {result.total_return:.2%}")
        print(f"年化收益率:   {result.annual_return:.2%}")
        print(f"最大回撤:     {result.max_drawdown:.2%}")
        print(f"夏普比率:     {result.sharpe_ratio:.2f}")
        print("-" * 60)
        print(f"总交易次数:   {result.total_trades}")
        print(f"盈利次数:     {result.profit_trades}")
        print(f"亏损次数:     {result.loss_trades}")
        print(f"胜率:         {result.win_rate:.2%}")
        print("=" * 60 + "\n")
