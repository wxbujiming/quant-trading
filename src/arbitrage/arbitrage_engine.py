"""
价差套利回测引擎

独立双腿回测引擎（不继承 FuturesBacktestEngine），
复用其数据类 PositionState / FuturesTradeRecord / DailySettlement / FuturesBacktestResult。

核心设计：
- 双腿共用资金池（self.capital）
- 每腿独立配置乘数/保证金率/手续费率
- 交易记录通过 contract 字段标记 L1: / L2: 前缀区分腿
"""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import pandas as pd
import numpy as np
from loguru import logger

from src.backtest.futures_engine import (
    PositionState, PositionSide,
    OrderDirection, OffsetFlag,
    FuturesTradeRecord, DailySettlement, FuturesBacktestResult,
)


# ──────────────── 交易标记前缀 ────────────────

LEG1_PREFIX = "L1:"
LEG2_PREFIX = "L2:"


def _leg_tag(leg: int, contract: str = "") -> str:
    """生成带腿标记的合约代码"""
    prefix = LEG1_PREFIX if leg == 1 else LEG2_PREFIX
    return f"{prefix}{contract}" if contract else f"{prefix}"


def _parse_leg_tag(tag: str) -> Tuple[int, str]:
    """解析腿标记，返回 (leg, original_contract)"""
    if tag.startswith(LEG1_PREFIX):
        return 1, tag[len(LEG1_PREFIX):]
    elif tag.startswith(LEG2_PREFIX):
        return 2, tag[len(LEG2_PREFIX):]
    return 0, tag


# ──────────────── 回测结果数据类 ────────────────

@dataclass
class ArbitrageBacktestResult:
    """套利回测结果"""
    # 合并指标
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
    # 各腿独立结果
    leg1_result: FuturesBacktestResult = field(default_factory=lambda: FuturesBacktestResult(
        initial_capital=0, final_capital=0, total_return=0, annual_return=0,
        max_drawdown=0, sharpe_ratio=0, total_trades=0, win_rate=0,
        profit_factor=0, total_commission=0))
    leg2_result: FuturesBacktestResult = field(default_factory=lambda: FuturesBacktestResult(
        initial_capital=0, final_capital=0, total_return=0, annual_return=0,
        max_drawdown=0, sharpe_ratio=0, total_trades=0, win_rate=0,
        profit_factor=0, total_commission=0))
    # 时间序列
    settlements: List[DailySettlement] = field(default_factory=list)
    trades: List[FuturesTradeRecord] = field(default_factory=list)
    # 标识
    leg1_symbol: str = ""
    leg2_symbol: str = ""
    leg1_name: str = ""
    leg2_name: str = ""


# ──────────────── 套利回测引擎 ────────────────

class ArbitrageBacktestEngine:
    """
    价差套利回测引擎

    支持双腿独立配置参数、共用资金池、双腿同步结算。

    Usage:
        engine = ArbitrageBacktestEngine(
            initial_capital=1_000_000,
            leg1_symbol="RB", leg1_multiplier=10, leg1_margin_rate=0.10,
            leg2_symbol="HC", leg2_multiplier=10, leg2_margin_rate=0.10,
        )
        result = engine.run(spread_df, strategy)
    """

    def __init__(
        self,
        initial_capital: float = 1_000_000.0,
        # 腿1 参数
        leg1_symbol: str = "LEG1",
        leg1_multiplier: int = 10,
        leg1_margin_rate: float = 0.10,
        leg1_commission_open: float = 0.0001,
        leg1_commission_close: float = 0.0001,
        leg1_commission_close_today: Optional[float] = None,
        leg1_name: str = "",
        # 腿2 参数
        leg2_symbol: str = "LEG2",
        leg2_multiplier: int = 10,
        leg2_margin_rate: float = 0.10,
        leg2_commission_open: float = 0.0001,
        leg2_commission_close: float = 0.0001,
        leg2_commission_close_today: Optional[float] = None,
        leg2_name: str = "",
        # 通用参数
        slippage: float = 0.0001,
        min_commission: float = 0.0,
    ):
        self.initial_capital = initial_capital
        self.slippage = slippage
        self.min_commission = min_commission

        # 腿1 配置
        self.leg1_symbol = leg1_symbol
        self.leg1_multiplier = leg1_multiplier
        self.leg1_margin_rate = leg1_margin_rate
        self.leg1_commission_open = leg1_commission_open
        self.leg1_commission_close = leg1_commission_close
        self.leg1_commission_close_today = (
            leg1_commission_close_today if leg1_commission_close_today is not None
            else leg1_commission_close
        )
        self.leg1_name = leg1_name or leg1_symbol

        # 腿2 配置
        self.leg2_symbol = leg2_symbol
        self.leg2_multiplier = leg2_multiplier
        self.leg2_margin_rate = leg2_margin_rate
        self.leg2_commission_open = leg2_commission_open
        self.leg2_commission_close = leg2_commission_close
        self.leg2_commission_close_today = (
            leg2_commission_close_today if leg2_commission_close_today is not None
            else leg2_commission_close
        )
        self.leg2_name = leg2_name or leg2_symbol

        self._reset()

        logger.info(
            f"套利回测引擎初始化: 资金={initial_capital:,.0f}, "
            f"腿1={self.leg1_name}(乘数={leg1_multiplier},保证金={leg1_margin_rate:.0%}), "
            f"腿2={self.leg2_name}(乘数={leg2_multiplier},保证金={leg2_margin_rate:.0%})"
        )

    # ──────────────── 运行时状态 ────────────────

    def _reset(self):
        """重置运行时状态"""
        self.capital = self.initial_capital  # 共用资金池
        self.frozen_capital = 0.0

        # 腿1 持仓
        self._leg1_long: Dict[str, PositionState] = {}
        self._leg1_short: Dict[str, PositionState] = {}
        # 腿2 持仓
        self._leg2_long: Dict[str, PositionState] = {}
        self._leg2_short: Dict[str, PositionState] = {}

        self.trades: List[FuturesTradeRecord] = []
        self.settlements: List[DailySettlement] = []
        self.cum_commission = 0.0

    # ──────────────── 参数查询 ────────────────

    def _leg_params(self, leg: int) -> dict:
        """获取某腿的参数"""
        if leg == 1:
            return {
                "symbol": self.leg1_symbol,
                "multiplier": self.leg1_multiplier,
                "margin_rate": self.leg1_margin_rate,
                "commission_open": self.leg1_commission_open,
                "commission_close": self.leg1_commission_close,
                "commission_close_today": self.leg1_commission_close_today,
            }
        else:
            return {
                "symbol": self.leg2_symbol,
                "multiplier": self.leg2_multiplier,
                "margin_rate": self.leg2_margin_rate,
                "commission_open": self.leg2_commission_open,
                "commission_close": self.leg2_commission_close,
                "commission_close_today": self.leg2_commission_close_today,
            }

    def _pos_dicts(self, leg: int) -> Tuple[Dict, Dict]:
        """获取某腿的多空持仓字典"""
        if leg == 1:
            return self._leg1_long, self._leg1_short
        return self._leg2_long, self._leg2_short

    # ──────────────── 手续费计算 ────────────────

    def _calc_commission(self, leg: int, price: float, volume: int,
                         offset: OffsetFlag) -> float:
        """按腿配置计算手续费"""
        p = self._leg_params(leg)
        turnover = price * p["multiplier"] * volume

        if offset == OffsetFlag.OPEN:
            rate = p["commission_open"]
        elif offset == OffsetFlag.CLOSE_TODAY:
            rate = p["commission_close_today"]
        else:
            rate = p["commission_close"]

        return max(turnover * rate, self.min_commission)

    def _calc_margin(self, leg: int, price: float, volume: int) -> float:
        """计算某腿开仓保证金"""
        p = self._leg_params(leg)
        return price * p["multiplier"] * p["margin_rate"] * volume

    # ──────────────── 下单接口 ────────────────

    def arb_open_long(self, leg: int, date: datetime, price: float,
                      volume: int, contract: str = "") -> bool:
        """
        指定腿开多仓

        Args:
            leg: 腿编号 (1 或 2)
            date: 日期
            price: 成交价
            volume: 手数
            contract: 合约代码

        Returns:
            是否成功
        """
        if volume <= 0:
            return False

        p = self._leg_params(leg)
        total_margin = self._calc_margin(leg, price, volume)

        if total_margin > self.capital:
            logger.debug(f"[{date.date()}] 腿{leg}资金不足: "
                         f"需保证金={total_margin:.0f}, 可用={self.capital:.0f}")
            return False

        commission = self._calc_commission(leg, price, volume, OffsetFlag.OPEN)
        actual_price = price * (1 + self.slippage)

        # 扣减资金
        self.capital -= (total_margin + commission)
        self.cum_commission += commission
        self.frozen_capital += total_margin

        # 更新持仓
        long_dict, _ = self._pos_dicts(leg)
        key = contract or p["symbol"]
        if key in long_dict:
            pos = long_dict[key]
            total_cost = pos.avg_price * pos.volume + actual_price * volume
            pos.volume += volume
            pos.avg_price = total_cost / pos.volume
            pos.margin += total_margin
        else:
            long_dict[key] = PositionState(
                side=PositionSide.LONG,
                volume=volume,
                avg_price=actual_price,
                margin=total_margin,
            )

        # 记录交易
        tag = _leg_tag(leg, contract or p["symbol"])
        self.trades.append(FuturesTradeRecord(
            date=date,
            symbol=p["symbol"],
            direction=OrderDirection.BUY,
            offset=OffsetFlag.OPEN,
            price=actual_price,
            volume=volume,
            margin=total_margin,
            commission=commission,
            contract=tag,
        ))

        logger.debug(f"{date.date()} 腿{leg}开多 {p['symbol']}: "
                     f"{volume}手 @ {actual_price:.1f}, 保证金={total_margin:.0f}")
        return True

    def arb_open_short(self, leg: int, date: datetime, price: float,
                       volume: int, contract: str = "") -> bool:
        """指定腿开空仓"""
        if volume <= 0:
            return False

        p = self._leg_params(leg)
        total_margin = self._calc_margin(leg, price, volume)

        if total_margin > self.capital:
            logger.debug(f"[{date.date()}] 腿{leg}资金不足: "
                         f"需保证金={total_margin:.0f}, 可用={self.capital:.0f}")
            return False

        commission = self._calc_commission(leg, price, volume, OffsetFlag.OPEN)
        actual_price = price * (1 - self.slippage)

        # 扣减资金
        self.capital -= (total_margin + commission)
        self.cum_commission += commission
        self.frozen_capital += total_margin

        # 更新持仓
        _, short_dict = self._pos_dicts(leg)
        key = contract or p["symbol"]
        if key in short_dict:
            pos = short_dict[key]
            total_cost = pos.avg_price * pos.volume + actual_price * volume
            pos.volume += volume
            pos.avg_price = total_cost / pos.volume
            pos.margin += total_margin
        else:
            short_dict[key] = PositionState(
                side=PositionSide.SHORT,
                volume=volume,
                avg_price=actual_price,
                margin=total_margin,
            )

        # 记录交易
        tag = _leg_tag(leg, contract or p["symbol"])
        self.trades.append(FuturesTradeRecord(
            date=date,
            symbol=p["symbol"],
            direction=OrderDirection.SELL,
            offset=OffsetFlag.OPEN,
            price=actual_price,
            volume=volume,
            margin=total_margin,
            commission=commission,
            contract=tag,
        ))

        logger.debug(f"{date.date()} 腿{leg}开空 {p['symbol']}: "
                     f"{volume}手 @ {actual_price:.1f}, 保证金={total_margin:.0f}")
        return True

    def arb_close_long(self, leg: int, date: datetime, price: float,
                       volume: Optional[int] = None, is_today: bool = False,
                       contract: str = "") -> bool:
        """指定腿平多仓"""
        p = self._leg_params(leg)
        long_dict, _ = self._pos_dicts(leg)
        key = contract or p["symbol"]

        pos = long_dict.get(key)
        if pos is None or pos.volume <= 0:
            return False

        if volume is None or volume > pos.volume:
            volume = pos.volume

        # 盈亏
        actual_price = price * (1 - self.slippage)
        profit = (actual_price - pos.avg_price) * p["multiplier"] * volume

        # 手续费
        offset = OffsetFlag.CLOSE_TODAY if is_today else OffsetFlag.CLOSE
        commission = self._calc_commission(leg, price, volume, offset)

        # 释放保证金
        margin_release = pos.margin * (volume / pos.volume)
        pos.margin -= margin_release

        # 更新持仓
        pos.volume -= volume
        if pos.volume <= 0:
            del long_dict[key]

        # 资金变动
        self.capital += (margin_release + profit - commission)
        self.cum_commission += commission
        self.frozen_capital -= margin_release

        # 记录交易
        tag = _leg_tag(leg, contract or p["symbol"])
        self.trades.append(FuturesTradeRecord(
            date=date,
            symbol=p["symbol"],
            direction=OrderDirection.SELL,
            offset=offset,
            price=actual_price,
            volume=volume,
            margin=0,
            commission=commission,
            profit=profit,
            contract=tag,
        ))

        logger.debug(f"{date.date()} 腿{leg}平多 {p['symbol']}: "
                     f"{volume}手 @ {actual_price:.1f}, 盈亏={profit:.0f}")
        return True

    def arb_close_short(self, leg: int, date: datetime, price: float,
                        volume: Optional[int] = None, is_today: bool = False,
                        contract: str = "") -> bool:
        """指定腿平空仓"""
        p = self._leg_params(leg)
        _, short_dict = self._pos_dicts(leg)
        key = contract or p["symbol"]

        pos = short_dict.get(key)
        if pos is None or pos.volume <= 0:
            return False

        if volume is None or volume > pos.volume:
            volume = pos.volume

        # 盈亏（空单：开仓价 - 平仓价）
        actual_price = price * (1 + self.slippage)
        profit = (pos.avg_price - actual_price) * p["multiplier"] * volume

        # 手续费
        offset = OffsetFlag.CLOSE_TODAY if is_today else OffsetFlag.CLOSE
        commission = self._calc_commission(leg, price, volume, offset)

        # 释放保证金
        margin_release = pos.margin * (volume / pos.volume)
        pos.margin -= margin_release

        # 更新持仓
        pos.volume -= volume
        if pos.volume <= 0:
            del short_dict[key]

        # 资金变动
        self.capital += (margin_release + profit - commission)
        self.cum_commission += commission
        self.frozen_capital -= margin_release

        # 记录交易
        tag = _leg_tag(leg, contract or p["symbol"])
        self.trades.append(FuturesTradeRecord(
            date=date,
            symbol=p["symbol"],
            direction=OrderDirection.BUY,
            offset=offset,
            price=actual_price,
            volume=volume,
            margin=0,
            commission=commission,
            profit=profit,
            contract=tag,
        ))

        logger.debug(f"{date.date()} 腿{leg}平空 {p['symbol']}: "
                     f"{volume}手 @ {actual_price:.1f}, 盈亏={profit:.0f}")
        return True

    # ──────────────── 逐日盯市 ────────────────

    def daily_settle(self, date: datetime,
                     leg1_prices: Tuple[float, float],
                     leg2_prices: Tuple[float, float]):
        """
        双腿逐日盯市结算。

        Args:
            date: 当前日期
            leg1_prices: (结算价, 收盘价)
            leg2_prices: (结算价, 收盘价)
        """
        total_position_pnl = 0.0
        total_margin = 0.0

        # 腿1 浮动盈亏
        l1_settle, _ = leg1_prices
        for key, pos in list(self._leg1_long.items()):
            pnl = (l1_settle - pos.avg_price) * self.leg1_multiplier * pos.volume
            total_position_pnl += pnl
            total_margin += pos.margin
        for key, pos in list(self._leg1_short.items()):
            pnl = (pos.avg_price - l1_settle) * self.leg1_multiplier * pos.volume
            total_position_pnl += pnl
            total_margin += pos.margin

        # 腿2 浮动盈亏
        l2_settle, _ = leg2_prices
        for key, pos in list(self._leg2_long.items()):
            pnl = (l2_settle - pos.avg_price) * self.leg2_multiplier * pos.volume
            total_position_pnl += pnl
            total_margin += pos.margin
        for key, pos in list(self._leg2_short.items()):
            pnl = (pos.avg_price - l2_settle) * self.leg2_multiplier * pos.volume
            total_position_pnl += pnl
            total_margin += pos.margin

        # 总权益
        total_equity = self.capital + total_position_pnl

        self.settlements.append(DailySettlement(
            date=date,
            total_equity=total_equity,
            available=total_equity - total_margin,
            margin=total_margin,
            position_pnl=total_position_pnl,
            realized_pnl=0.0,
            commission=0.0,
            margin_ratio=total_margin / total_equity if total_equity > 0 else 1.0,
        ))

    # ──────────────── 查询接口 ────────────────

    def get_position(self, leg: int, contract: str = "") -> Tuple[Optional[PositionState], Optional[PositionState]]:
        """获取某腿的多空持仓"""
        long_dict, short_dict = self._pos_dicts(leg)
        p = self._leg_params(leg)
        key = contract or p["symbol"]
        return long_dict.get(key), short_dict.get(key)

    def get_available_capital(self) -> float:
        """获取可用资金"""
        return self.capital

    # ──────────────── 运行回测 ────────────────

    def run(self, spread_data: pd.DataFrame, strategy) -> ArbitrageBacktestResult:
        """
        运行套利回测。

        Args:
            spread_data: SpreadBuilder.build() 的输出，
                         含 leg1_* / leg2_* / spread / zscore / bb_* 列
            strategy: BaseArbitrageStrategy 实例

        Returns:
            ArbitrageBacktestResult
        """
        symbol_str = f"{self.leg1_name} vs {self.leg2_name}"
        logger.info(f"开始套利回测: {symbol_str}")
        self._reset()

        strategy.engine = self
        strategy.on_start()

        for date, row in spread_data.iterrows():
            # 组装 spread bar
            spread_bar = {
                "date": date,
                "leg1_open": row.get("leg1_open", 0),
                "leg1_high": row.get("leg1_high", 0),
                "leg1_low": row.get("leg1_low", 0),
                "leg1_close": row.get("leg1_close", 0),
                "leg1_settle": row.get("leg1_settle", row.get("leg1_close", 0)),
                "leg1_volume": row.get("leg1_volume", 0),
                "leg2_open": row.get("leg2_open", 0),
                "leg2_high": row.get("leg2_high", 0),
                "leg2_low": row.get("leg2_low", 0),
                "leg2_close": row.get("leg2_close", 0),
                "leg2_settle": row.get("leg2_settle", row.get("leg2_close", 0)),
                "leg2_volume": row.get("leg2_volume", 0),
                "spread": row.get("spread", 0),
                "zscore": row.get("zscore", 0),
                "bb_upper": row.get("bb_upper", 0),
                "bb_middle": row.get("bb_middle", 0),
                "bb_lower": row.get("bb_lower", 0),
            }

            # 策略决策
            strategy.on_spread_bar(spread_bar)

            # 每日结算
            self.daily_settle(
                date=date,
                leg1_prices=(
                    row.get("leg1_settle", row.get("leg1_close", 0)),
                    row.get("leg1_close", 0),
                ),
                leg2_prices=(
                    row.get("leg2_settle", row.get("leg2_close", 0)),
                    row.get("leg2_close", 0),
                ),
            )

        # 收盘强制平仓
        self._force_close_all(spread_data)

        # 计算结果
        result = self._calculate_result()
        logger.success(f"套利回测完成: {symbol_str}, "
                       f"总收益率={result.total_return:.2%}")
        return result

    def _force_close_all(self, spread_data: pd.DataFrame):
        """回测结束强制平仓"""
        last_row = spread_data.iloc[-1]
        last_date = spread_data.index[-1] if isinstance(spread_data.index[-1], datetime) else last_row.name

        for key in list(self._leg1_long.keys()):
            self.arb_close_long(1, last_date, last_row["leg1_close"], contract=key)
        for key in list(self._leg1_short.keys()):
            self.arb_close_short(1, last_date, last_row["leg1_close"], contract=key)
        for key in list(self._leg2_long.keys()):
            self.arb_close_long(2, last_date, last_row["leg2_close"], contract=key)
        for key in list(self._leg2_short.keys()):
            self.arb_close_short(2, last_date, last_row["leg2_close"], contract=key)

    # ──────────────── 结果计算 ────────────────

    def _calculate_result(self) -> ArbitrageBacktestResult:
        """计算回测结果"""
        # 各腿独立结果
        leg1_result = self._build_leg_result(1)
        leg2_result = self._build_leg_result(2)

        # 合并指标
        if not self.settlements:
            return ArbitrageBacktestResult(
                initial_capital=self.initial_capital,
                final_capital=self.initial_capital,
                total_return=0.0, annual_return=0.0,
                max_drawdown=0.0, sharpe_ratio=0.0,
                total_trades=0, win_rate=0.0, profit_factor=0.0,
                total_commission=self.cum_commission,
                leg1_result=leg1_result, leg2_result=leg2_result,
                leg1_symbol=self.leg1_symbol, leg2_symbol=self.leg2_symbol,
                leg1_name=self.leg1_name, leg2_name=self.leg2_name,
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
            std = df["daily_return"].std()
            sharpe = df["daily_return"].mean() / std * np.sqrt(252) if std > 0 else 0
        else:
            sharpe = 0

        # 交易统计
        close_trades = [t for t in self.trades
                        if t.offset in (OffsetFlag.CLOSE, OffsetFlag.CLOSE_TODAY)]
        win_trades = [t for t in close_trades if t.profit > 0]
        loss_trades = [t for t in close_trades if t.profit <= 0]
        win_rate = len(win_trades) / len(close_trades) if close_trades else 0
        total_profit = sum(t.profit for t in win_trades)
        total_loss = abs(sum(t.profit for t in loss_trades))
        profit_factor = total_profit / total_loss if total_loss > 0 else float("inf")

        return ArbitrageBacktestResult(
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
            leg1_result=leg1_result,
            leg2_result=leg2_result,
            settlements=self.settlements,
            trades=self.trades,
            leg1_symbol=self.leg1_symbol,
            leg2_symbol=self.leg2_symbol,
            leg1_name=self.leg1_name,
            leg2_name=self.leg2_name,
        )

    def _build_leg_result(self, leg: int) -> FuturesBacktestResult:
        """
        从全局交易记录中过滤出某腿的交易，重建 FuturesBacktestResult。

        用于 per-leg 分解展示。
        """
        prefix = LEG1_PREFIX if leg == 1 else LEG2_PREFIX
        p = self._leg_params(leg)

        # 过滤该腿的平仓交易
        leg_close_trades = [
            t for t in self.trades
            if t.contract.startswith(prefix)
            and t.offset in (OffsetFlag.CLOSE, OffsetFlag.CLOSE_TODAY)
        ]

        leg_win = [t for t in leg_close_trades if t.profit > 0]
        leg_loss = [t for t in leg_close_trades if t.profit <= 0]
        total_profit = sum(t.profit for t in leg_win)
        total_loss = abs(sum(t.profit for t in leg_loss))

        win_rate = len(leg_win) / len(leg_close_trades) if leg_close_trades else 0
        profit_factor = total_profit / total_loss if total_loss > 0 else float("inf")

        # 该腿的交易次数（所有操作）
        leg_all_trades = [t for t in self.trades if t.contract.startswith(prefix)]

        # 费用（该腿累计）
        leg_commission = sum(t.commission for t in leg_all_trades)

        # 该腿的保证金占用（最后一个结算日）
        total_margin = 0.0
        long_dict, short_dict = self._pos_dicts(leg)
        for pos in list(long_dict.values()) + list(short_dict.values()):
            total_margin += pos.margin

        return FuturesBacktestResult(
            initial_capital=0,  # 单腿无法独立计算初始资金
            final_capital=0,
            total_return=0,
            annual_return=0,
            max_drawdown=0,
            sharpe_ratio=0,
            total_trades=len(leg_close_trades),
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_commission=leg_commission,
        )

    # ──────────────── 结果打印 ────────────────

    def print_result(self, result: ArbitrageBacktestResult,
                     strategy_name: str = ""):
        """打印套利回测结果"""
        arb_type = ""
        if result.leg1_symbol == result.leg2_symbol:
            arb_type = " (跨期套利)"
        else:
            arb_type = " (跨品种套利)"

        print("\n" + "=" * 60)
        print(f"             套利回测结果报告{arb_type}")
        print("=" * 60)
        if strategy_name:
            print(f"策略:          {strategy_name}")
        print(f"品种组合:      {result.leg1_name} vs {result.leg2_name}")
        print()

        print("─" * 10 + " 合并权益 " + "─" * 39)
        print(f"初始资金:      {result.initial_capital:>10,.2f}")
        print(f"最终权益:      {result.final_capital:>10,.2f}")
        print(f"总收益率:      {result.total_return:>10.2%}")
        print(f"年化收益率:    {result.annual_return:>10.2%}")
        print(f"最大回撤:      {result.max_drawdown:>10.2%}")
        print(f"夏普比率:      {result.sharpe_ratio:>10.2f}")
        print(f"总手续费:      {result.total_commission:>10,.2f}")
        print(f"总交易次数:    {result.total_trades:>10}")
        print(f"胜率:          {result.win_rate:>10.2%}")
        print(f"盈亏比:        {result.profit_factor:>10.2f}")
        print()

        print("─" * 10 + " 各腿分解 " + "─" * 39)
        print(f"{'腿':<8} {'手续费':>10} {'交易次数':>10} {'胜率':>8}")
        print("-" * 40)
        print(f"{result.leg1_name:<8} "
              f"{result.leg1_result.total_commission:>10,.0f} "
              f"{result.leg1_result.total_trades:>10} "
              f"{result.leg1_result.win_rate:>8.2%}")
        print(f"{result.leg2_name:<8} "
              f"{result.leg2_result.total_commission:>10,.0f} "
              f"{result.leg2_result.total_trades:>10} "
              f"{result.leg2_result.win_rate:>8.2%}")
        print("=" * 60)

        # 如果还有持仓未平，警告
        if self._leg1_long or self._leg1_short:
            n = len(self._leg1_long) + len(self._leg1_short)
            print(f"⚠ 腿1 仍有 {n} 个持仓未平")
        if self._leg2_long or self._leg2_short:
            n = len(self._leg2_long) + len(self._leg2_short)
            print(f"⚠ 腿2 仍有 {n} 个持仓未平")
