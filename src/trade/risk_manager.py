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
from src.trade.contract_manager import ContractManager


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


# ──────────────── 新增: 保证金与风险度规则 ────────────────


class MarginRule(RiskRule):
    """
    保证金占用监控

    通过 ContractManager 获取合约乘数和保证金率，计算开仓所需保证金，
    在开仓前检查可用资金是否充足。
    """

    def __init__(self, contract_manager: ContractManager, initial_capital: float = 1000000.0):
        super().__init__("保证金监控")
        self.cm = contract_manager
        self.initial_capital = initial_capital
        self._total_margin = 0.0
        self.description = "保证金占用实时计算与检查"

    def calc_margin(self, symbol: str, price: float, volume: int) -> float:
        """
        计算指定开仓需要的保证金

        Args:
            symbol: 品种代码
            price: 价格
            volume: 手数

        Returns:
            需要保证金金额
        """
        base = ContractManager.parse_contract(symbol)["base"]
        multiplier = self.cm.get_multiplier(base)
        margin_rate = self.cm.get_margin_rate(base, symbol)
        margin = price * multiplier * margin_rate * volume
        return margin

    def set_total_margin(self, margin: float):
        """设置当前总占用保证金（从外部更新）"""
        self._total_margin = margin

    def check(self, symbol: str, price: float, volume: int,
              position_manager: PositionManager) -> tuple[bool, str]:
        if not self.enabled:
            return True, ""

        base = ContractManager.parse_contract(symbol)["base"]
        if not self.cm or not self.cm.has_spec(base):
            return True, ""  # 未知品种跳过检查

        needed = self.calc_margin(symbol, price, volume)
        total_needed = self._total_margin + needed

        account = position_manager.get_account()
        equity = account.balance if account else self.initial_capital

        if total_needed > equity:
            return False, (
                f"[{symbol}] 保证金不足: 需{total_needed:,.0f}, "
                f"总权益{equity:,.0f}, 差额{total_needed - equity:,.0f}"
            )
        return True, f"保证金: 当前{self._total_margin:,.0f}, 新增{needed:,.0f}, 总{total_needed:,.0f}"


class RiskRatioRule(RiskRule):
    """
    风险度监控

    风险度 = 总占用保证金 / 总权益
      - 警戒线 80%: 记录警告日志
      - 危险线 90%: 拒绝新开仓
      - 强平线 100%: 触发强平预警
    """

    def __init__(self, contract_manager: ContractManager, initial_capital: float = 1000000.0,
                 warning_ratio: float = 0.80, danger_ratio: float = 0.90,
                 liquidation_ratio: float = 1.0):
        super().__init__("风险度监控")
        self.cm = contract_manager
        self.initial_capital = initial_capital
        self.warning_ratio = warning_ratio
        self.danger_ratio = danger_ratio
        self.liquidation_ratio = liquidation_ratio
        self.description = (
            f"风险度监控: 警戒线{warning_ratio:.0%}, "
            f"危险线{danger_ratio:.0%}, 强平线{liquidation_ratio:.0%}"
        )
        self.current_ratio = 0.0
        self.total_margin = 0.0
        self.total_equity = 0.0

    def update(self, total_margin: float, total_equity: float):
        """更新当前风险度"""
        self.total_margin = total_margin
        self.total_equity = total_equity
        self.current_ratio = total_margin / total_equity if total_equity > 0 else 1.0

    def check(self) -> tuple[bool, str]:
        """风险度检查（开仓前调用）"""
        if not self.enabled:
            return True, ""

        if self.current_ratio >= self.liquidation_ratio:
            return False, (
                f"风险度已达强平线: {self.current_ratio:.1%}, "
                f"保证金{self.total_margin:,.0f}/权益{self.total_equity:,.0f}"
            )
        if self.current_ratio >= self.danger_ratio:
            return False, (
                f"风险度过高: {self.current_ratio:.1%}, "
                f"超过危险线{self.danger_ratio:.0%}, 拒绝开仓"
            )
        if self.current_ratio >= self.warning_ratio:
            return True, (
                f"风险度预警: {self.current_ratio:.1%}, "
                f"超过警戒线{self.warning_ratio:.0%}"
            )
        return True, f"风险度正常: {self.current_ratio:.1%}"

    def get_risk_level(self) -> str:
        """获取风险等级"""
        if self.current_ratio >= self.liquidation_ratio:
            return "liquidation"
        if self.current_ratio >= self.danger_ratio:
            return "danger"
        if self.current_ratio >= self.warning_ratio:
            return "warning"
        return "normal"

    def get_alerts(self) -> list:
        """获取当前风险告警"""
        alerts = []
        level = self.get_risk_level()
        if level == "liquidation":
            alerts.append({
                "rule": self.name,
                "symbol": "",
                "message": (
                    f"强平预警! 风险度{self.current_ratio:.1%} >= "
                    f"强平线{self.liquidation_ratio:.0%}"
                ),
                "level": "critical",
            })
        elif level == "danger":
            alerts.append({
                "rule": self.name,
                "symbol": "",
                "message": f"风险度{self.current_ratio:.1%} 超过危险线{self.danger_ratio:.0%}",
                "level": "danger",
            })
        elif level == "warning":
            alerts.append({
                "rule": self.name,
                "symbol": "",
                "message": f"风险度{self.current_ratio:.1%} 超过警戒线{self.warning_ratio:.0%}",
                "level": "warning",
            })
        return alerts


class PriceLimitRule(RiskRule):
    """
    涨跌停板保护

    涨停不能开空，跌停不能开多。
    开仓价格超出涨跌停范围时拒绝。
    """

    def __init__(self):
        super().__init__("涨跌停板保护")
        self.description = "涨停限制开空/跌停限制开多"
        # 各品种涨跌停百分比 (品种 -> up_pct, down_pct)
        self._limits: dict = {}
        self._prev_settle: dict = {}  # symbol -> 前结算价

    def set_limit(self, symbol: str, up_pct: float, down_pct: float):
        """
        设置品种涨跌停比例

        Args:
            symbol: 合约代码
            up_pct: 涨停百分比 (0.06 = 6%)
            down_pct: 跌停百分比 (0.06 = 6%)
        """
        base = ContractManager.parse_contract(symbol)["base"]
        self._limits[base] = (up_pct, down_pct)

    def set_prev_settle(self, symbol: str, settle: float):
        """设置前结算价"""
        self._prev_settle[symbol] = settle

    def check(self, symbol: str, price: float, direction: str) -> tuple[bool, str]:
        """
        价格限制检查

        Args:
            symbol: 合约代码
            price: 申报价格
            direction: 交易方向 (open_long/open_short/close_long/close_short)

        Returns:
            (是否通过, 消息)
        """
        if not self.enabled:
            return True, ""

        base = ContractManager.parse_contract(symbol)["base"]
        limits = self._limits.get(base)
        if not limits:
            return True, ""  # 未知品种无限制

        up_pct, down_pct = limits
        settle = self._prev_settle.get(symbol)
        if settle is None or settle <= 0:
            return True, ""  # 无结算价数据

        up_price = settle * (1 + up_pct)
        down_price = settle * (1 - down_pct)

        # 开多: 价格不能超过涨停价
        if direction in ("open_long", "close_short"):
            if price > up_price:
                return False, (
                    f"[{symbol}] 开多价格{price}超过涨停价{up_price:.2f} "
                    f"(前结算{settle}*{1+up_pct:.0%})"
                )
            if price < down_price:
                return False, (
                    f"[{symbol}] 开多价格{price}低于跌停价{down_price:.2f}, "
                    f"但可能为正常低价, 警告"
                )

        # 开空: 价格不能低于跌停价
        if direction in ("open_short", "close_long"):
            if price > up_price:
                return False, (
                    f"[{symbol}] 开空价格{price}超过涨停价{up_price:.2f}, "
                    f"但可能为正常高价, 警告"
                )
            if price < down_price:
                return False, (
                    f"[{symbol}] 开空价格{price}低于跌停价{down_price:.2f} "
                    f"(前结算{settle}*{1-down_pct:.0%})"
                )

        return True, ""


class LiquidationWarningRule(RiskRule):
    """
    强平预警

    周期性检查风险度，接近强平线时发出告警。
    达到强平线时记录严重告警。
    """

    def __init__(self, risk_ratio_rule: RiskRatioRule,
                 auto_reduce_pct: float = 0.2):
        """
        Args:
            risk_ratio_rule: RiskRatioRule 实例（获取风险度数据）
            auto_reduce_pct: 自动减仓比例 (0.2 = 减20%仓位)
        """
        super().__init__("强平预警")
        self.risk_ratio = risk_ratio_rule
        self.auto_reduce_pct = auto_reduce_pct
        self.description = f"风险度超过强平线时预警, 自动减仓比例{auto_reduce_pct:.0%}"
        self._last_alert_level = "normal"

    def check(self) -> tuple[bool, str]:
        """检查是否需要强平预警"""
        if not self.enabled:
            return True, ""

        level = self.risk_ratio.get_risk_level()
        ratio = self.risk_ratio.current_ratio

        if level == "liquidation":
            self._last_alert_level = "liquidation"
            return False, (
                f"强平预警! 风险度{ratio:.1%}已达强平线, "
                f"建议立即减仓{self.auto_reduce_pct:.0%}"
            )
        if level == "danger":
            self._last_alert_level = "danger"
            return True, (
                f"风险度{ratio:.1%}处于危险区间(>{self.risk_ratio.danger_ratio:.0%}), "
                f"接近强平线{self.risk_ratio.liquidation_ratio:.0%}"
            )
        if self._last_alert_level != "normal" and level == "normal":
            self._last_alert_level = "normal"
            return True, f"风险度已恢复正常: {ratio:.1%}"

        return True, ""


class RiskManager:
    """风控系统总管理器"""

    def __init__(self, gateway: BaseGateway, initial_cash: float = 1000000.0,
                 contract_manager: ContractManager = None):
        self.gateway = gateway
        self.order_manager = OrderManager(gateway)
        self.position_manager = PositionManager(gateway, initial_cash)
        self.contract_manager = contract_manager

        # 保证金与风险度规则（需要 contract_manager）
        if contract_manager:
            self.margin_rule = MarginRule(contract_manager, initial_cash)
            self.risk_ratio_rule = RiskRatioRule(contract_manager, initial_cash)
            self.price_limit_rule = PriceLimitRule()
            self.liquidation_warning = LiquidationWarningRule(self.risk_ratio_rule)
        else:
            self.margin_rule = None
            self.risk_ratio_rule = None
            self.price_limit_rule = None
            self.liquidation_warning = None

        # 风控规则列表
        self.rules: list[RiskRule] = [
            MaxPositionRule(max_volume=100),
            MaxNotionalRule(max_notional=initial_cash * 0.8, total_balance=initial_cash),
            DailyLossLimitRule(max_daily_loss=initial_cash * 0.05),
            StopLossRule(stop_loss_pct=5.0),
            TradeFrequencyRule(max_orders_per_minute=5),
        ]
        if contract_manager:
            self.rules.extend([
                self.margin_rule,
                self.risk_ratio_rule,
                self.price_limit_rule,
                self.liquidation_warning,
            ])

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

    def check_before_order(self, symbol: str, price: float, volume: int,
                           direction: str = ""):
        """
        下单前风控检查

        Args:
            symbol: 品种代码
            price: 价格
            volume: 手数
            direction: 交易方向 (open_long/open_short/close_long/close_short)

        Returns:
            (是否通过, 消息)
        """
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

            # 保证金检查
            elif isinstance(rule, MarginRule):
                passed, msg = rule.check(symbol, price, volume, self.position_manager)
                if not passed:
                    return False, msg

            # 风险度检查
            elif isinstance(rule, RiskRatioRule):
                passed, msg = rule.check()
                if not passed:
                    return False, msg

            # 涨跌停保护
            elif isinstance(rule, PriceLimitRule) and direction:
                passed, msg = rule.check(symbol, price, direction)
                if not passed:
                    return False, msg

        return True, "风控通过"

    def check_positions(self) -> list:
        """定期持仓检查 (止损检查 + 风险度检查)"""
        alerts = []

        # 更新风险度（在检查前计算）
        self._update_risk_metrics()

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

            # 强平预警检查
            elif isinstance(rule, LiquidationWarningRule):
                passed, msg = rule.check()
                if not passed:
                    alerts.append({"rule": rule.name, "symbol": "", "message": msg, "level": "critical"})
                elif msg and "风险度" in msg:
                    alerts.append({"rule": rule.name, "symbol": "", "message": msg, "level": "warning"})

            # 风险度告警
            elif isinstance(rule, RiskRatioRule):
                for alert in rule.get_alerts():
                    alerts.append(alert)

        return alerts

    def _update_risk_metrics(self):
        """更新保证金和风险度指标"""
        if not self.contract_manager:
            return

        total_margin = self.calc_total_margin()
        account = self.position_manager.get_account()
        total_equity = account.balance if account else 0

        if self.margin_rule:
            self.margin_rule.set_total_margin(total_margin)
        if self.risk_ratio_rule:
            self.risk_ratio_rule.update(total_margin, total_equity)

    def buy(self, symbol: str, price: float, volume: int, exchange: str = "",
            direction: str = "open_long") -> Optional[str]:
        """买入开仓(带风控)"""
        passed, msg = self.check_before_order(symbol, price, volume, direction)
        if not passed:
            self.gateway.write_error(f"风控拦截开仓: {msg}")
            return None

        self._record_trade_frequency()
        return self.order_manager.buy(symbol, price, volume, exchange)

    def sell(self, symbol: str, price: float, volume: int, exchange: str = "") -> Optional[str]:
        """卖出平仓(带风控)"""
        self._record_trade_frequency()
        return self.order_manager.sell(symbol, price, volume, exchange)

    # ──────────────── 新增: 保证金与风险度计算 ────────────────

    def calc_margin(self, symbol: str, price: float, volume: int) -> float:
        """
        计算指定开仓所需保证金

        Args:
            symbol: 品种代码
            price: 价格
            volume: 手数

        Returns:
            保证金金额
        """
        if not self.contract_manager:
            base = ContractManager.parse_contract(symbol)["base"]
            return price * 10 * 0.10 * volume  # 默认值
        return self.margin_rule.calc_margin(symbol, price, volume)

    def calc_total_margin(self) -> float:
        """计算当前所有持仓的总占用保证金"""
        if not self.contract_manager:
            return 0.0

        total = 0.0
        for pos in self.position_manager.get_all_positions():
            base = ContractManager.parse_contract(pos.symbol)["base"]
            multiplier = self.contract_manager.get_multiplier(base)
            margin_rate = self.contract_manager.get_margin_rate(base, pos.symbol)
            margin = pos.price * multiplier * margin_rate * pos.volume
            total += margin
        return total

    def calc_risk_ratio(self) -> float:
        """
        计算当前风险度

        Returns:
            风险度 (0.0 ~ 1.0+), 1.0 = 100% = 强平线
        """
        account = self.position_manager.get_account()
        if not account or account.balance <= 0:
            return 0.0
        total_margin = self.calc_total_margin()
        return total_margin / account.balance if account.balance > 0 else 0.0

    def get_margin_status(self) -> dict:
        """获取保证金和风险度状态摘要"""
        account = self.position_manager.get_account()
        total_equity = account.balance if account else 0
        total_margin = self.calc_total_margin()
        risk_ratio = total_margin / total_equity if total_equity > 0 else 0
        available = total_equity - total_margin

        return {
            "total_equity": total_equity,
            "total_margin": total_margin,
            "available_margin": available,
            "risk_ratio": risk_ratio,
            "risk_level": (
                "liquidation" if risk_ratio >= 1.0
                else "danger" if risk_ratio >= 0.9
                else "warning" if risk_ratio >= 0.8
                else "normal"
            ),
        }

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

        # 保证金与风险度信息
        margin_status = self.get_margin_status()
        if margin_status["total_equity"] > 0:
            from rich.panel import Panel
            status_text = (
                f"总权益: {margin_status['total_equity']:>10,.0f}  |  "
                f"占用保证金: {margin_status['total_margin']:>10,.0f}  |  "
                f"可用: {margin_status['available_margin']:>10,.0f}\n"
                f"风险度: {margin_status['risk_ratio']:>7.1%}  |  "
                f"风险等级: {margin_status['risk_level']}"
            )
            console.print(Panel(status_text, title="保证金与风险度"))

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
