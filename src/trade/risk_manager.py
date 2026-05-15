"""
风控系统
提供止损止盈、仓位控制、风险预警等功能
"""

from typing import Optional, Callable
from datetime import datetime, timedelta
from loguru import logger

from src.trade.gateway import (
    BaseGateway, OrderData, OrderDirection, OrderStatus,
)
from src.trade.order_manager import OrderManager
from src.trade.position_manager import PositionManager


class RiskRule:
    """风控规则基类"""

    def __init__(self, name: str, enabled: bool = True):
        self.name = name
        self.enabled = enabled
        self.description = ""

    def check(self, *args, **kwargs) -> tuple[bool, str]:
        """
        检查规则
        返回: (是否通过, 消息)
        """
        return True, ""

    def __str__(self):
        return f"[{'✅' if self.enabled else '❌'}] {self.name}: {self.description}"


class MaxPositionRule(RiskRule):
    """单品种最大持仓限制"""

    def __init__(self, max_volume: int = 100):
        super().__init__("单品种持仓限制")
        self.max_volume = max_volume
        self.description = f"单品种最大持仓 {max_volume} 手"

    def check(self, symbol: str, order_volume: int, position_manager: PositionManager) -> tuple[bool, str]:
        if not self.enabled:
            return True, ""

        pos = position_manager.get_position(symbol)
        current = pos.volume if pos else 0
        if current + order_volume > self.max_volume:
            return False, f"{symbol} 持仓超限: 当前{current}, 将达{current + order_volume}, 限制{self.max_volume}"
        return True, ""


class MaxNotionalRule(RiskRule):
    """最大名义价值限制"""

    def __init__(self, max_notional: float = 1000000.0, total_balance: float = 1000000.0):
        super().__init__("仓位比例限制")
        self.max_notional = max_notional
        self.total_balance = total_balance
        self.description = f"最大名义价值 {max_notional:,.0f}"

    def check(self, symbol: str, price: float, volume: int, position_manager: PositionManager) -> tuple[bool, str]:
        if not self.enabled:
            return True, ""

        order_value = price * volume
        position_value = position_manager.get_total_market_value()
        total = position_value + order_value

        if total > self.max_notional:
            ratio = total / self.total_balance * 100
            return False, f"仓位超限: 当前{position_value:,.0f} + 新增{order_value:,.0f} = {total:,.0f}, 限制{self.max_notional:,.0f} ({ratio:.1f}%)"
        return True, ""


class DailyLossLimitRule(RiskRule):
    """每日最大亏损限制"""

    def __init__(self, max_daily_loss: float = 50000.0):
        super().__init__("每日亏损限制")
        self.max_daily_loss = max_daily_loss
        self.description = f"每日最大亏损 {max_daily_loss:,.0f}"
        self._daily_pnl = 0.0
        self._date = datetime.now().date()

    def check(self, position_manager: PositionManager) -> tuple[bool, str]:
        if not self.enabled:
            return True, ""

        # 每天重置
        today = datetime.now().date()
        if today != self._date:
            self._daily_pnl = 0.0
            self._date = today

        pnl = position_manager.get_total_pnl()
        loss = max(0, -pnl)

        if loss > self.max_daily_loss:
            return False, f"当日亏损超限: 亏损{loss:,.0f}, 限制{self.max_daily_loss:,.0f}"
        return True, ""


class StopLossRule(RiskRule):
    """单个持仓止损"""

    def __init__(self, stop_loss_pct: float = 5.0):
        super().__init__("止损线")
        self.stop_loss_pct = stop_loss_pct
        self.description = f"止损线 {stop_loss_pct}%"

    def check(self, symbol: str, position_manager: PositionManager) -> tuple[bool, str]:
        if not self.enabled:
            return True, ""

        pos = position_manager.get_position(symbol)
        if not pos or pos.volume <= 0:
            return True, ""

        # 简单判断: 多仓亏损超过百分比
        if pos.pnl < 0:
            loss_pct = abs(pos.pnl) / (pos.volume * pos.price) * 100
            if loss_pct >= self.stop_loss_pct:
                return False, f"{symbol} 触发止损: 亏损{loss_pct:.1f}%, 限制{self.stop_loss_pct}%"
        return True, ""


class TradeFrequencyRule(RiskRule):
    """交易频率限制"""

    def __init__(self, max_orders_per_minute: int = 5):
        super().__init__("交易频率限制")
        self.max_orders_per_minute = max_orders_per_minute
        self.description = f"每分钟最大订单数 {max_orders_per_minute}"
        self._order_times: list = []

    def check(self) -> tuple[bool, str]:
        if not self.enabled:
            return True, ""

        now = datetime.now()
        # 清理1分钟前的记录
        self._order_times = [t for t in self._order_times if now - t < timedelta(minutes=1)]

        if len(self._order_times) >= self.max_orders_per_minute:
            return False, f"交易频率超限: 当前{len(self._order_times)}/分钟, 限制{self.max_orders_per_minute}"
        return True, ""

    def record_order(self):
        """记录一次下单"""
        self._order_times.append(datetime.now())


class RiskManager:
    """风控系统总管理器"""

    def __init__(self, gateway: BaseGateway, initial_cash: float = 1000000.0):
        self.gateway = gateway
        self.order_manager = OrderManager(gateway)
        self.position_manager = PositionManager(gateway, initial_cash)

        # 风控规则列表
        self.rules: list[RiskRule] = [
            MaxPositionRule(max_volume=100),
            MaxNotionalRule(max_notional=initial_cash * 0.8, total_balance=initial_cash),
            DailyLossLimitRule(max_daily_loss=initial_cash * 0.05),
            StopLossRule(stop_loss_pct=5.0),
            TradeFrequencyRule(max_orders_per_minute=5),
        ]

        # 止损定时器
        self._stop_loss_interval = 60  # 秒
        self._last_stop_loss_check = datetime.now()

    def add_rule(self, rule: RiskRule):
        """添加风控规则"""
        self.rules.append(rule)
        logger.info(f"添加风控规则: {rule}")

    def remove_rule(self, name: str) -> bool:
        """移除风控规则"""
        for i, rule in enumerate(self.rules):
            if rule.name == name:
                self.rules.pop(i)
                logger.info(f"移除风控规则: {name}")
                return True
        return False

    def enable_rule(self, name: str, enabled: bool = True):
        """启用/禁用规则"""
        for rule in self.rules:
            if rule.name == name:
                rule.enabled = enabled
                logger.info(f"{'启用' if enabled else '禁用'}风控规则: {name}")
                break

    def check_before_order(self, symbol: str, price: float, volume: int) -> tuple[bool, str]:
        """下单前风控检查"""
        for rule in self.rules:
            if not rule.enabled:
                continue

            # 频率检查
            if isinstance(rule, TradeFrequencyRule):
                passed, msg = rule.check()
                if not passed:
                    return False, msg

            # 持仓限制
            elif isinstance(rule, MaxPositionRule):
                passed, msg = rule.check(symbol, volume, self.position_manager)
                if not passed:
                    return False, msg

            # 名义价值
            elif isinstance(rule, MaxNotionalRule):
                passed, msg = rule.check(symbol, price, volume, self.position_manager)
                if not passed:
                    return False, msg

        return True, "风控通过"

    def check_positions(self) -> list:
        """定期持仓检查 (止损检查)"""
        alerts = []

        for rule in self.rules:
            if not rule.enabled:
                continue

            if isinstance(rule, StopLossRule):
                for pos in self.position_manager.get_all_positions():
                    passed, msg = rule.check(pos.symbol, self.position_manager)
                    if not passed:
                        alerts.append({"rule": rule.name, "symbol": pos.symbol, "message": msg})

            elif isinstance(rule, DailyLossLimitRule):
                passed, msg = rule.check(self.position_manager)
                if not passed:
                    alerts.append({"rule": rule.name, "symbol": "", "message": msg})

        return alerts

    def buy(self, symbol: str, price: float, volume: int, exchange: str = "") -> Optional[str]:
        """买入开仓(带风控)"""
        passed, msg = self.check_before_order(symbol, price, volume)
        if not passed:
            self.gateway.write_error(f"风控拦截开仓: {msg}")
            return None

        self._record_trade_frequency()
        return self.order_manager.buy(symbol, price, volume, exchange)

    def sell(self, symbol: str, price: float, volume: int, exchange: str = "") -> Optional[str]:
        """卖出平仓(带风控)"""
        self._record_trade_frequency()
        return self.order_manager.sell(symbol, price, volume, exchange)

    def _record_trade_frequency(self):
        """记录交易频率"""
        for rule in self.rules:
            if isinstance(rule, TradeFrequencyRule):
                rule.record_order()

    def print_risk_status(self):
        """打印风控状态"""
        from rich.table import Table
        from rich.console import Console

        console = Console()
        table = Table(title="风控规则状态")
        table.add_column("状态")
        table.add_column("规则名称")
        table.add_column("说明")

        for rule in self.rules:
            status = "✅" if rule.enabled else "❌"
            table.add_row(status, rule.name, rule.description)

        console.print(table)

    def print_system_summary(self):
        """打印系统总览"""
        from rich.console import Console
        from rich.panel import Panel
        from rich import box

        console = Console()

        # 风控状态
        self.print_risk_status()

        # 账户持仓
        self.position_manager.print_summary()

        # 订单统计
        self.order_manager.print_summary()
