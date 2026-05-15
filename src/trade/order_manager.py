"""
订单管理器
负责订单的创建、跟踪、查询和统计
"""

from typing import Optional, Callable
from datetime import datetime
from loguru import logger

from src.trade.gateway import (
    BaseGateway, OrderData, TradeData,
    OrderStatus, OrderDirection, OrderType,
)


class OrderManager:
    """订单管理器"""

    def __init__(self, gateway: BaseGateway):
        self.gateway = gateway
        self._orders: dict = {}          # order_id -> OrderData
        self._trades: list = []           # 成交记录
        self._trade_counter = 0

        # 注册回调
        gateway.on_order = self._on_order
        gateway.on_trade = self._on_trade

        # 外部回调
        self.on_order_update: Optional[Callable] = None
        self.on_trade: Optional[Callable] = None

    def buy(self, symbol: str, price: float, volume: int, exchange: str = "") -> str:
        """买入开仓"""
        order = OrderData(
            symbol=symbol,
            exchange=exchange,
            order_id="",
            direction=OrderDirection.BUY,
            offset="open",
            price=price,
            volume=volume,
            order_type=OrderType.LIMIT,
            gateway_name=self.gateway.gateway_name,
        )
        return self.gateway.send_order(order)

    def sell(self, symbol: str, price: float, volume: int, exchange: str = "") -> str:
        """卖出平仓"""
        order = OrderData(
            symbol=symbol,
            exchange=exchange,
            order_id="",
            direction=OrderDirection.SELL,
            offset="close",
            price=price,
            volume=volume,
            order_type=OrderType.LIMIT,
            gateway_name=self.gateway.gateway_name,
        )
        return self.gateway.send_order(order)

    def short(self, symbol: str, price: float, volume: int, exchange: str = "") -> str:
        """卖出开仓"""
        order = OrderData(
            symbol=symbol,
            exchange=exchange,
            order_id="",
            direction=OrderDirection.SHORT,
            offset="open",
            price=price,
            volume=volume,
            order_type=OrderType.LIMIT,
            gateway_name=self.gateway.gateway_name,
        )
        return self.gateway.send_order(order)

    def cover(self, symbol: str, price: float, volume: int, exchange: str = "") -> str:
        """买入平仓"""
        order = OrderData(
            symbol=symbol,
            exchange=exchange,
            order_id="",
            direction=OrderDirection.COVER,
            offset="close",
            price=price,
            volume=volume,
            order_type=OrderType.LIMIT,
            gateway_name=self.gateway.gateway_name,
        )
        return self.gateway.send_order(order)

    def cancel(self, order_id: str) -> bool:
        """撤销订单"""
        return self.gateway.cancel_order(order_id)

    def get_order(self, order_id: str) -> Optional[OrderData]:
        """获取订单详情"""
        return self.gateway.get_order(order_id)

    def get_orders(self, status: OrderStatus = None) -> list:
        """获取订单列表"""
        orders = list(self.gateway.get_orders().values())
        if status:
            orders = [o for o in orders if o.status == status]
        return sorted(orders, key=lambda o: o.create_time, reverse=True)

    def get_active_orders(self) -> list:
        """获取活跃订单"""
        return [o for o in self.get_orders() if o.is_active()]

    def get_trades(self, symbol: str = "") -> list:
        """获取成交记录"""
        if symbol:
            return [t for t in self._trades if t.symbol == symbol]
        return self._trades.copy()

    def get_order_statistics(self) -> dict:
        """获取订单统计"""
        orders = self.get_orders()
        total = len(orders)
        traded = sum(1 for o in orders if o.status == OrderStatus.ALL_TRADED)
        canceled = sum(1 for o in orders if o.status == OrderStatus.CANCELED)
        rejected = sum(1 for o in orders if o.status == OrderStatus.REJECTED)
        active = sum(1 for o in orders if o.is_active())

        return {
            "total": total,
            "traded": traded,
            "canceled": canceled,
            "rejected": rejected,
            "active": active,
            "trade_rate": traded / total * 100 if total > 0 else 0,
        }

    def _on_order(self, order: OrderData):
        """订单回调"""
        self._orders[order.order_id] = order
        logger.debug(f"订单更新: {order.order_id} -> {order.status.value}")

        if self.on_order_update:
            self.on_order_update(order)

    def _on_trade(self, trade: TradeData):
        """成交回调"""
        self._trade_counter += 1
        trade.trade_id = f"trade_{self._trade_counter:06d}"
        self._trades.append(trade)
        logger.info(f"成交: {trade.symbol} {trade.volume}手 @ {trade.price}")

        if self.on_trade:
            self.on_trade(trade)

    def print_summary(self):
        """打印订单摘要"""
        from rich.table import Table
        from rich.console import Console

        stats = self.get_order_statistics()
        console = Console()

        table = Table(title="订单统计")
        table.add_column("指标", style="cyan")
        table.add_column("数值", justify="right")

        table.add_row("总订单数", str(stats["total"]))
        table.add_row("已成交", str(stats["traded"]))
        table.add_row("已撤销", str(stats["canceled"]))
        table.add_row("已拒绝", str(stats["rejected"]))
        table.add_row("活跃中", str(stats["active"]))
        table.add_row("成交率", f"{stats['trade_rate']:.1f}%")

        console.print(table)
