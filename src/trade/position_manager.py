"""
持仓管理器
管理所有持仓数据，提供风险计算和报表功能
"""

from typing import Optional, Callable
from loguru import logger

from src.trade.gateway import (
    BaseGateway, PositionData, AccountData,
    OrderDirection,
)


class PositionManager:
    """持仓管理器"""

    def __init__(self, gateway: BaseGateway, initial_cash: float = 1000000.0):
        self.gateway = gateway
        self._initial_cash = initial_cash
        self._positions: dict = {}         # symbol -> PositionData
        self._account: Optional[AccountData] = None

        # 注册回调
        gateway.on_position = self._on_position
        gateway.on_account = self._on_account

        # 外部回调
        self.on_position_update: Optional[Callable] = None

    def get_position(self, symbol: str, direction: Optional[OrderDirection] = None) -> Optional[PositionData]:
        """获取持仓"""
        if direction:
            return self._positions.get(f"{symbol}_{direction.value}")

        # 合并方向
        positions = [p for p in self._positions.values() if p.symbol == symbol]
        if positions:
            return positions[0]
        return None

    def get_all_positions(self) -> list:
        """获取所有持仓"""
        return list(self._positions.values())

    def get_account(self) -> Optional[AccountData]:
        """获取账户信息"""
        if not self._account:
            self._account = self.gateway.query_account()
        return self._account

    def refresh_account(self) -> AccountData:
        """刷新账户信息"""
        self._account = self.gateway.query_account()
        return self._account

    def refresh_positions(self):
        """刷新持仓"""
        self.gateway.query_position()

    def get_total_market_value(self) -> float:
        """获取总市值"""
        return sum(p.volume * p.price for p in self._positions.values())

    def get_total_pnl(self) -> float:
        """获取总浮动盈亏"""
        return sum(p.pnl for p in self._positions.values())

    def get_available_cash(self) -> float:
        """获取可用资金"""
        account = self.get_account()
        return account.available if account else self._initial_cash

    def get_position_ratio(self, symbol: str = "") -> float:
        """获取持仓占比"""
        account = self.get_account()
        if not account or account.balance <= 0:
            return 0.0

        positions = self.get_all_positions()
        if not positions:
            return 0.0

        if symbol:
            pos = self.get_position(symbol)
            if not pos:
                return 0.0
            return (pos.volume * pos.price) / account.balance * 100

        return self.get_total_market_value() / account.balance * 100

    def get_summary(self) -> dict:
        """获取持仓摘要"""
        account = self.get_account()
        positions = self.get_all_positions()

        total_cost = sum(p.volume * p.price for p in positions)
        total_volume = sum(p.volume for p in positions)
        total_pnl = sum(p.pnl for p in positions)

        return {
            "total_cash": account.available if account else 0,
            "total_balance": account.balance if account else 0,
            "total_market_value": total_cost,
            "total_volume": total_volume,
            "total_pnl": total_pnl,
            "position_count": len(positions),
            "position_ratio": (total_cost / account.balance * 100) if account and account.balance > 0 else 0,
        }

    def _on_position(self, position: PositionData):
        """持仓更新回调"""
        key = f"{position.symbol}_{position.direction.value}"
        self._positions[key] = position

        if self.on_position_update:
            self.on_position_update(position)

    def _on_account(self, account: AccountData):
        """账户更新回调"""
        self._account = account

    def print_summary(self):
        """打印持仓摘要"""
        from rich.table import Table
        from rich.console import Console

        summary = self.get_summary()
        console = Console()

        # 账户信息
        account_table = Table(title="账户概览")
        account_table.add_column("指标", style="cyan")
        account_table.add_column("数值", justify="right")

        account_table.add_row("总资产", f"{summary['total_balance']:,.2f}")
        account_table.add_row("可用资金", f"{summary['total_cash']:,.2f}")
        account_table.add_row("持仓市值", f"{summary['total_market_value']:,.2f}")
        account_table.add_row("总盈亏", f"{summary['total_pnl']:+,.2f}")
        account_table.add_row("持仓个数", str(summary["position_count"]))
        account_table.add_row("仓位比例", f"{summary['position_ratio']:.2f}%")

        console.print(account_table)

        # 持仓明细
        positions = self.get_all_positions()
        if positions:
            pos_table = Table(title="持仓明细")
            pos_table.add_column("合约", style="cyan")
            pos_table.add_column("方向")
            pos_table.add_column("持仓量", justify="right")
            pos_table.add_column("均价", justify="right")
            pos_table.add_column("市值", justify="right")
            pos_table.add_column("盈亏", justify="right")

            for pos in positions:
                direction_text = "多" if pos.direction in (OrderDirection.BUY, OrderDirection.COVER) else "空"
                pos_table.add_row(
                    pos.symbol,
                    direction_text,
                    str(pos.volume),
                    f"{pos.price:.2f}",
                    f"{pos.volume * pos.price:,.2f}",
                    f"{pos.pnl:+,.2f}",
                )

            console.print(pos_table)
