"""
期货回测引擎

与A股回测的核心差异:
1. 保证金交易 - 不是全款买入，只占用部分保证金
2. 多空双向 - 可以做多也可以做空
3. 逐日盯市 - 每日按结算价计算浮动盈亏
4. T+0 - 当天开仓当天可平仓
5. 合约乘数 - 每个品种有固定的合约乘数
6. 平今手续费 - 平今仓手续费可能不同
"""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import pandas as pd
import numpy as np
from loguru import logger


class PositionSide(Enum):
    """持仓方向"""
    LONG = "long"      # 多单
    SHORT = "short"    # 空单


class OrderDirection(Enum):
    """交易指令方向"""
    BUY = "buy"              # 买入开多 / 买入平空
    SELL = "sell"            # 卖出开空 / 卖出平多


class OffsetFlag(Enum):
    """开平标志"""
    OPEN = "open"       # 开仓
    CLOSE = "close"     # 平仓
    CLOSE_TODAY = "close_today"  # 平今仓


@dataclass
class FuturesTradeRecord:
    """期货交易记录"""
    date: datetime
    symbol: str
    direction: OrderDirection    # BUY/SELL
    offset: OffsetFlag           # OPEN/CLOSE
    price: float                 # 成交价
    volume: int                  # 手数
    margin: float                # 占用保证金
    commission: float            # 手续费
    profit: float = 0.0          # 平仓盈亏（仅平仓时有）
    contract: str = ""           # 具体合约（用于换月）


@dataclass
class PositionState:
    """持仓状态"""
    side: PositionSide            # 多/空
    volume: int = 0               # 持仓手数
    avg_price: float = 0.0        # 持仓均价
    margin: float = 0.0           # 占用保证金
    frozen: int = 0               # 冻结手数（挂单未成交）
    
    @property
    def available(self) -> int:
        return self.volume - self.frozen


@dataclass
class DailySettlement:
    """每日结算记录"""
    date: datetime
    total_equity: float           # 总权益 = 可用资金 + 保证金 + 浮动盈亏
    available: float              # 可用资金
    margin: float                 # 占用保证金
    position_pnl: float           # 持仓浮动盈亏
    realized_pnl: float           # 已实现盈亏
    commission: float             # 今日手续费
    margin_ratio: float           # 保证金占用率


@dataclass
class FuturesBacktestResult:
    """期货回测结果"""
    initial_capital: float
    final_capital: float
    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe_ratio: float
    total_trades: int
    win_rate: float
    profit_factor: float
    total_commission: float
    settlements: List[DailySettlement] = field(default_factory=list)
    trades: List[FuturesTradeRecord] = field(default_factory=list)


class FuturesBacktestEngine:
    """
    期货回测引擎
    
    支持:
    - 保证金交易 (自定义保证金率)
    - 多空双向
    - 逐日盯市
    - 合约乘数
    - 平今/平昨差异手续费
    - 换月移仓
    """
    
    def __init__(
        self,
        initial_capital: float = 100000.0,
        contract_multiplier: int = 10,          # 合约乘数（螺纹钢10吨/手）
        margin_rate: float = 0.10,              # 保证金比例 10%
        commission_open: float = 0.0001,        # 开仓手续费率（万分之一）
        commission_close: float = 0.0001,       # 平仓手续费率
        commission_close_today: float = None,   # 平今仓手续费（None=同平昨）
        min_commission: float = 0.0,            # 最低手续费
        slippage: float = 0.0001,               # 滑点比例
    ):
        """
        初始化期货回测引擎
        
        Args:
            initial_capital: 初始资金
            contract_multiplier: 合约乘数（每手多少吨/股）
            margin_rate: 保证金比例 (0.10 = 10%)
            commission_open: 开仓手续费率
            commission_close: 平仓手续费率
            commission_close_today: 平今手续费率（None=同平昨）
            min_commission: 最低手续费（按手）
            slippage: 滑点比例
        """
        self.initial_capital = initial_capital
        self.contract_multiplier = contract_multiplier
        self.margin_rate = margin_rate
        self.commission_open = commission_open
        self.commission_close = commission_close
        self.commission_close_today = commission_close_today if commission_close_today is not None else commission_close
        self.min_commission = min_commission
        self.slippage = slippage
        
        # 运行时状态
        self._reset()
        
        logger.info(
            f"期货回测引擎初始化: 资金={initial_capital}, "
            f"乘数={contract_multiplier}, 保证金={margin_rate:.0%}"
        )
    
    def _reset(self):
        """重置运行时状态"""
        self.capital = self.initial_capital
        self.frozen_capital = 0.0
        self.long_positions: Dict[str, PositionState] = {}      # symbol -> PositionState
        self.short_positions: Dict[str, PositionState] = {}     # symbol -> PositionState
        self.trades: List[FuturesTradeRecord] = []
        self.settlements: List[DailySettlement] = []
        self.daily_pnl = 0.0
        self.cum_commission = 0.0
        
        # 价格序列 (用于计算逐日盯市盈亏)
        self._last_prices: Dict[str, Tuple[str, float]] = {}    # symbol -> (settle_price, close_price)
    
    # ──────────────── 核心参数配置 ────────────────
    
    def set_product_params(self, base: str, multiplier: int = None,
                           margin_rate: float = None):
        """
        设置具体品种参数（覆盖默认值）
        
        Args:
            base: 品种代码
            multiplier: 合约乘数
            margin_rate: 保证金比例
        """
        if multiplier is not None:
            logger.info(f"[{base}] 设置合约乘数: {multiplier}")
            self.contract_multiplier = multiplier
        if margin_rate is not None:
            logger.info(f"[{base}] 设置保证金率: {margin_rate:.1%}")
            self.margin_rate = margin_rate
    
    # ──────────────── 下单接口 ────────────────
    
    def open_long(self, date: datetime, symbol: str, price: float,
                  volume: int, contract: str = "") -> bool:
        """
        开多仓
        
        Args:
            date: 日期
            symbol: 品种代码
            price: 成交价
            volume: 手数
            contract: 合约代码
            
        Returns:
            是否成功开仓
        """
        if volume <= 0:
            return False
        
        # 计算保证金
        margin_per_contract = price * self.contract_multiplier * self.margin_rate
        total_margin = margin_per_contract * volume
        
        # 检查资金是否足够
        if total_margin > self.capital:
            logger.debug(f"[{date.date()}] 资金不足: 需保证金={total_margin:.0f}, 可用={self.capital:.0f}")
            return False
        
        # 计算手续费
        commission = self._calc_commission(price, volume, OffsetFlag.OPEN)
        
        # 滑点
        actual_price = price * (1 + self.slippage)
        
        # 扣减资金
        self.capital -= (total_margin + commission)
        self.cum_commission += commission
        self.frozen_capital += total_margin
        
        # 更新持仓
        key = f"{symbol}_{contract}" if contract else symbol
        if key in self.long_positions:
            pos = self.long_positions[key]
            total_cost = pos.avg_price * pos.volume + actual_price * volume
            pos.volume += volume
            pos.avg_price = total_cost / pos.volume
            pos.margin += total_margin
        else:
            self.long_positions[key] = PositionState(
                side=PositionSide.LONG,
                volume=volume,
                avg_price=actual_price,
                margin=total_margin,
            )
        
        # 记录交易
        self.trades.append(FuturesTradeRecord(
            date=date,
            symbol=symbol,
            direction=OrderDirection.BUY,
            offset=OffsetFlag.OPEN,
            price=actual_price,
            volume=volume,
            margin=total_margin,
            commission=commission,
            contract=contract or symbol,
        ))
        
        logger.debug(f"{date.date()} 开多 {symbol}: {volume}手 @ {actual_price:.1f}, 保证金={total_margin:.0f}")
        return True
    
    def open_short(self, date: datetime, symbol: str, price: float,
                   volume: int, contract: str = "") -> bool:
        """
        开空仓
        
        Args:
            date: 日期
            symbol: 品种代码
            price: 成交价
            volume: 手数
            contract: 合约代码
            
        Returns:
            是否成功开仓
        """
        if volume <= 0:
            return False
        
        # 计算保证金
        margin_per_contract = price * self.contract_multiplier * self.margin_rate
        total_margin = margin_per_contract * volume
        
        # 检查资金
        if total_margin > self.capital:
            logger.debug(f"[{date.date()}] 资金不足: 需保证金={total_margin:.0f}, 可用={self.capital:.0f}")
            return False
        
        # 计算手续费
        commission = self._calc_commission(price, volume, OffsetFlag.OPEN)
        
        # 滑点
        actual_price = price * (1 - self.slippage)
        
        # 扣减资金
        self.capital -= (total_margin + commission)
        self.cum_commission += commission
        self.frozen_capital += total_margin
        
        # 更新持仓
        key = f"{symbol}_{contract}" if contract else symbol
        if key in self.short_positions:
            pos = self.short_positions[key]
            total_cost = pos.avg_price * pos.volume + actual_price * volume
            pos.volume += volume
            pos.avg_price = total_cost / pos.volume
            pos.margin += total_margin
        else:
            self.short_positions[key] = PositionState(
                side=PositionSide.SHORT,
                volume=volume,
                avg_price=actual_price,
                margin=total_margin,
            )
        
        # 记录交易
        self.trades.append(FuturesTradeRecord(
            date=date,
            symbol=symbol,
            direction=OrderDirection.SELL,
            offset=OffsetFlag.OPEN,
            price=actual_price,
            volume=volume,
            margin=total_margin,
            commission=commission,
            contract=contract or symbol,
        ))
        
        logger.debug(f"{date.date()} 开空 {symbol}: {volume}手 @ {actual_price:.1f}, 保证金={total_margin:.0f}")
        return True
    
    def close_long(self, date: datetime, symbol: str, price: float,
                   volume: int = None, is_today: bool = False,
                   contract: str = "") -> bool:
        """
        平多仓
        
        Args:
            date: 日期
            symbol: 品种代码
            price: 平仓价
            volume: 手数（None=全部平仓）
            is_today: 是否是平今仓（影响手续费）
            contract: 合约代码
        """
        key = f"{symbol}_{contract}" if contract else symbol
        pos = self.long_positions.get(key)
        if pos is None or pos.volume <= 0:
            return False
        
        if volume is None or volume > pos.volume:
            volume = pos.volume
        
        # 计算盈亏
        actual_price = price * (1 - self.slippage)
        profit = (actual_price - pos.avg_price) * self.contract_multiplier * volume
        
        # 计算手续费
        offset = OffsetFlag.CLOSE_TODAY if is_today else OffsetFlag.CLOSE
        commission = self._calc_commission(price, volume, offset)
        
        # 释放保证金
        margin_release = pos.margin * (volume / pos.volume)
        pos.margin -= margin_release
        
        # 更新持仓
        pos.volume -= volume
        if pos.volume <= 0:
            del self.long_positions[key]
        
        # 资金变动
        self.capital += (margin_release + profit - commission)
        self.cum_commission += commission
        self.frozen_capital -= margin_release
        
        # 记录交易
        self.trades.append(FuturesTradeRecord(
            date=date,
            symbol=symbol,
            direction=OrderDirection.SELL,
            offset=offset,
            price=actual_price,
            volume=volume,
            margin=0,
            commission=commission,
            profit=profit,
            contract=contract or symbol,
        ))
        
        logger.debug(f"{date.date()} 平多 {symbol}: {volume}手 @ {actual_price:.1f}, 盈亏={profit:.0f}")
        return True
    
    def close_short(self, date: datetime, symbol: str, price: float,
                    volume: int = None, is_today: bool = False,
                    contract: str = "") -> bool:
        """
        平空仓
        
        Args:
            date: 日期
            symbol: 品种代码
            price: 平仓价
            volume: 手数（None=全部平仓）
            is_today: 是否是平今仓
            contract: 合约代码
        """
        key = f"{symbol}_{contract}" if contract else symbol
        pos = self.short_positions.get(key)
        if pos is None or pos.volume <= 0:
            return False
        
        if volume is None or volume > pos.volume:
            volume = pos.volume
        
        # 计算盈亏（空单：开仓价 - 平仓价）
        actual_price = price * (1 + self.slippage)
        profit = (pos.avg_price - actual_price) * self.contract_multiplier * volume
        
        # 计算手续费
        offset = OffsetFlag.CLOSE_TODAY if is_today else OffsetFlag.CLOSE
        commission = self._calc_commission(price, volume, offset)
        
        # 释放保证金
        margin_release = pos.margin * (volume / pos.volume)
        pos.margin -= margin_release
        
        # 更新持仓
        pos.volume -= volume
        if pos.volume <= 0:
            del self.short_positions[key]
        
        # 资金变动
        self.capital += (margin_release + profit - commission)
        self.cum_commission += commission
        self.frozen_capital -= margin_release
        
        # 记录交易
        self.trades.append(FuturesTradeRecord(
            date=date,
            symbol=symbol,
            direction=OrderDirection.BUY,
            offset=offset,
            price=actual_price,
            volume=volume,
            margin=0,
            commission=commission,
            profit=profit,
            contract=contract or symbol,
        ))
        
        logger.debug(f"{date.date()} 平空 {symbol}: {volume}手 @ {actual_price:.1f}, 盈亏={profit:.0f}")
        return True
    
    def _calc_commission(self, price: float, volume: int, offset: OffsetFlag) -> float:
        """计算手续费"""
        turnover = price * self.contract_multiplier * volume
        
        if offset == OffsetFlag.OPEN:
            rate = self.commission_open
        elif offset == OffsetFlag.CLOSE_TODAY:
            rate = self.commission_close_today
        else:
            rate = self.commission_close
        
        fee = max(turnover * rate, self.min_commission)
        return fee
    
    # ──────────────── 逐日盯市结算 ────────────────
    
    def daily_settle(self, date: datetime, prices: Dict[str, Tuple[float, float]]):
        """
        每日结算（基于结算价）
        
        Args:
            date: 当前日期
            prices: {symbol: (结算价, 收盘价)} 的字典
        """
        total_position_pnl = 0.0
        total_margin = 0.0
        
        # 计算多单浮动盈亏
        for key, pos in list(self.long_positions.items()):
            settle_price, _ = prices.get(key.split("_")[0], (pos.avg_price, pos.avg_price))
            pnl = (settle_price - pos.avg_price) * self.contract_multiplier * pos.volume
            total_position_pnl += pnl
            total_margin += pos.margin
        
        # 计算空单浮动盈亏
        for key, pos in list(self.short_positions.items()):
            settle_price, _ = prices.get(key.split("_")[0], (pos.avg_price, pos.avg_price))
            pnl = (pos.avg_price - settle_price) * self.contract_multiplier * pos.volume
            total_position_pnl += pnl
            total_margin += pos.margin
        
        # 总权益
        total_equity = self.capital + total_position_pnl
        
        # 记录结算
        settlement = DailySettlement(
            date=date,
            total_equity=total_equity,
            available=total_equity - total_margin,
            margin=total_margin,
            position_pnl=total_position_pnl,
            realized_pnl=0.0,
            commission=0.0,
            margin_ratio=total_margin / total_equity if total_equity > 0 else 1.0,
        )
        self.settlements.append(settlement)
    
    # ──────────────── 查询接口 ────────────────
    
    def get_position(self, symbol: str, contract: str = "") -> Tuple[Optional[PositionState], Optional[PositionState]]:
        """获取某品种的多空持仓"""
        key = f"{symbol}_{contract}" if contract else symbol
        return self.long_positions.get(key), self.short_positions.get(key)
    
    def get_available_capital(self) -> float:
        """获取可用资金"""
        return self.capital
    
    def get_total_equity(self, prices: Dict[str, float] = None) -> float:
        """获取总权益"""
        total_pnl = 0.0
        for key, pos in self.long_positions.items():
            price = prices.get(key.split("_")[0], pos.avg_price) if prices else pos.avg_price
            total_pnl += (price - pos.avg_price) * self.contract_multiplier * pos.volume
        for key, pos in self.short_positions.items():
            price = prices.get(key.split("_")[0], pos.avg_price) if prices else pos.avg_price
            total_pnl += (pos.avg_price - price) * self.contract_multiplier * pos.volume
        return self.capital + total_pnl

    # ──────────────── 执行回测 ────────────────
    
    def run(self, data: pd.DataFrame, strategy, symbol: str):
        """
        运行期货回测
        
        Args:
            data: 行情数据（需包含 date, open, high, low, close, settle）
            strategy: 策略实例（需实现 generate_signals 方法）
            symbol: 品种代码
            
        Returns:
            FuturesBacktestResult
        """
        logger.info(f"开始期货回测: {symbol}")
        self._reset()
        
        strategy.engine = self
        strategy.symbol = symbol
        strategy.data = data  # 注入完整数据，用于多时间框架等预计算
        strategy.on_start()
        
        for i, (date, row) in enumerate(data.iterrows()):
            price_info = {
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "settle": row.get("settle", row["close"]),
                "volume": row.get("volume", 0),
                "hold": row.get("hold", 0),
                "date": date,
            }
            
            # 策略决策
            strategy.on_bar(price_info)
            
            # 每日结算
            self.daily_settle(
                date=date,
                prices={symbol: (row.get("settle", row["close"]), row["close"])}
            )
        
        # 收盘强制平仓
        self._force_close_all(data)
        
        # 计算结果
        result = self._calculate_result()
        logger.success(f"期货回测完成: {symbol}, 总收益率={result.total_return:.2%}")
        return result
    
    def _force_close_all(self, data: pd.DataFrame):
        """回测结束强制平仓"""
        last_row = data.iloc[-1]
        last_date = data.index[-1] if isinstance(data.index[-1], datetime) else last_row["date"]
        
        for key in list(self.long_positions.keys()):
            self.close_long(last_date, key.split("_")[0], last_row["close"],
                           is_today=False)
        for key in list(self.short_positions.keys()):
            self.close_short(last_date, key.split("_")[0], last_row["close"],
                            is_today=False)
    
    def _calculate_result(self) -> FuturesBacktestResult:
        """计算回测结果"""
        if not self.settlements:
            return FuturesBacktestResult(
                initial_capital=self.initial_capital,
                final_capital=self.initial_capital,
                total_return=0.0,
                annual_return=0.0,
                max_drawdown=0.0,
                sharpe_ratio=0.0,
                total_trades=0,
                win_rate=0.0,
                profit_factor=0.0,
                total_commission=self.cum_commission,
            )
        
        df = pd.DataFrame([s.__dict__ for s in self.settlements])
        
        final_capital = df["total_equity"].iloc[-1]
        total_return = (final_capital - self.initial_capital) / self.initial_capital
        
        # 年化
        days = (df["date"].iloc[-1] - df["date"].iloc[0]).days if len(df) > 1 else 1
        annual_return = (1 + total_return) ** (365 / max(days, 1)) - 1
        
        # 最大回撤
        df["cummax"] = df["total_equity"].cummax()
        df["drawdown"] = (df["cummax"] - df["total_equity"]) / df["cummax"]
        max_drawdown = df["drawdown"].max()
        
        # 夏普
        if len(df) > 1:
            df["daily_return"] = df["total_equity"].pct_change()
            sharpe = df["daily_return"].mean() / df["daily_return"].std() * np.sqrt(252) if df["daily_return"].std() > 0 else 0
        else:
            sharpe = 0
        
        # 交易统计
        close_trades = [t for t in self.trades if t.offset in (OffsetFlag.CLOSE, OffsetFlag.CLOSE_TODAY)]
        win_trades = [t for t in close_trades if t.profit > 0]
        loss_trades = [t for t in close_trades if t.profit <= 0]
        win_rate = len(win_trades) / len(close_trades) if close_trades else 0
        
        # 盈亏比
        total_profit = sum(t.profit for t in win_trades)
        total_loss = abs(sum(t.profit for t in loss_trades))
        profit_factor = total_profit / total_loss if total_loss > 0 else float("inf")
        
        return FuturesBacktestResult(
            initial_capital=self.initial_capital,
            final_capital=final_capital,
            total_return=total_return,
            annual_return=annual_return,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe,
            total_trades=len(close_trades),
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_commission=self.cum_commission,
            trades=self.trades,
            settlements=self.settlements,
        )
    
    def print_result(self, result: FuturesBacktestResult):
        """打印回测结果"""
        print("\n" + "=" * 60)
        print("               期货回测结果报告")
        print("=" * 60)
        print(f"初始资金:     {result.initial_capital:>10,.2f}")
        print(f"最终权益:     {result.final_capital:>10,.2f}")
        print(f"总收益率:     {result.total_return:>10.2%}")
        print(f"年化收益率:   {result.annual_return:>10.2%}")
        print(f"最大回撤:     {result.max_drawdown:>10.2%}")
        print(f"夏普比率:     {result.sharpe_ratio:>10.2f}")
        print("-" * 60)
        print(f"总手续费:     {result.total_commission:>10,.2f}")
        print(f"总交易次数:   {result.total_trades:>10}")
        print(f"胜率:         {result.win_rate:>10.2%}")
        print(f"盈亏比:       {result.profit_factor:>10.2f}")
        print("=" * 60)
