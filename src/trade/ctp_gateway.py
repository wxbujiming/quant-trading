"""
CTP (SimNow) 期货接口实现
通过REST API和WebSocket对接SimNow仿真交易环境
"""

import requests
import json
import time
import hashlib
from datetime import datetime
from typing import Optional
from loguru import logger

from src.trade.gateway import (
    BaseGateway, OrderData, TradeData, PositionData,
    AccountData, ContractData, TickData,
    OrderStatus, OrderDirection, OrderType,
)

# SimNow 默认地址
SIMNOW_TRADE_HOST = "180.168.146.187"
SIMNOW_MARKET_HOST = "180.168.146.187"

# 环境配置
ENVIRONMENTS = {
    "simnow": {
        "trade": ("180.168.146.187", 10200),
        "market": ("180.168.146.187", 10210),
        "name": "SimNow仿真交易",
    },
    "simnow_7x24": {
        "trade": ("180.168.146.187", 10130),
        "market": ("180.168.146.187", 10131),
        "name": "SimNow 7x24环境",
    },
}


class CtpGateway(BaseGateway):
    """CTP期货接口(基于REST API模拟)"""

    def __init__(self, gateway_name: str = "SimNow", setting: dict = None):
        super().__init__(gateway_name, setting)

        self.broker_id = setting.get("broker_id", "9999")
        self.user_id = setting.get("user_id", "")
        self.password = setting.get("password", "")
        self.app_id = setting.get("app_id", "simnow_client_test")
        self.auth_code = setting.get("auth_code", "0000000000000000")

        env_name = setting.get("environment", "simnow")
        env = ENVIRONMENTS.get(env_name, ENVIRONMENTS["simnow"])
        self.trade_addr = f"{env['trade'][0]}:{env['trade'][1]}"
        self.market_addr = f"{env['market'][0]}:{env['market'][1]}"
        self.env_name = env["name"]

        # 会话和状态
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })

        self._front_id = ""
        self._session_id = ""
        self._order_ref = 0
        self._orders: dict = {}
        self._positions: dict = {}
        self._contracts: dict = {}

        logger.info(f"CTP接口初始化: {self.env_name}, Broker={self.broker_id}, User={self.user_id}")

    def connect(self) -> bool:
        """连接SimNow (当前为模拟模式,实际CTP需要C++编译)"""
        self.write_log(f"正在连接 {self.env_name}...")
        self.write_log(f"注意: 当前使用REST API模拟模式, 如需真实CTP接口请安装vnpy_ctp编译版本")

        # 模拟连接成功
        self._connected = True
        self._logined = True

        self._on_connected()
        self._login()

        return True

    def close(self):
        """关闭连接"""
        self._connected = False
        self._logined = False
        self._session.close()
        self.write_log("连接已关闭")

    def _on_connected(self):
        """连接成功回调"""
        self.write_log(f"连接成功: {self.env_name}")

    def _login(self):
        """登录"""
        self.write_log(f"用户 {self.user_id} 登录成功 (仿真模式)")

    def send_order(self, order: OrderData) -> str:
        """发送订单"""
        if not self._logined:
            self.write_error("未登录,无法下单")
            return ""

        self._order_ref += 1
        order_id = f"{self.gateway_name}_{self._order_ref:06d}"
        order.order_id = order_id
        order.gateway_name = self.gateway_name
        order.status = OrderStatus.NOT_TRADED
        order.create_time = datetime.now()

        self._orders[order_id] = order
        self.write_log(
            f"下单: {order.symbol} "
            f"{'买入' if order.direction == OrderDirection.BUY else '卖出'} "
            f"{order.volume}手 @ {order.price}"
        )

        if self.on_order:
            self.on_order(order)

        return order_id

    def cancel_order(self, order_id: str) -> bool:
        """撤销订单"""
        order = self._orders.get(order_id)
        if not order:
            self.write_error(f"订单不存在: {order_id}")
            return False

        if order.is_finished():
            self.write_error(f"订单已完成,无法撤销: {order_id}")
            return False

        order.status = OrderStatus.CANCELED
        order.cancel_time = datetime.now()

        if self.on_order:
            self.on_order(order)

        self.write_log(f"撤单成功: {order_id}")
        return True

    def query_account(self) -> AccountData:
        """查询账户(返回模拟数据)"""
        account = AccountData(
            account_id=self.user_id,
            balance=1000000.0,       # 模拟100万
            frozen=0.0,
            available=1000000.0,
            margin=0.0,
            pnl=0.0,
            gateway_name=self.gateway_name,
        )

        if self.on_account:
            self.on_account(account)

        return account

    def query_position(self, symbol: str = "") -> list:
        """查询持仓"""
        positions = []
        for pos in self._positions.values():
            if symbol and pos.symbol != symbol:
                continue
            positions.append(pos)

            if self.on_position:
                self.on_position(pos)

        return positions

    def get_orders(self) -> dict:
        """获取所有订单"""
        return self._orders

    def get_order(self, order_id: str) -> Optional[OrderData]:
        """获取单个订单"""
        return self._orders.get(order_id)

    def subscribe(self, symbols: list):
        """订阅行情"""
        self.write_log(f"订阅行情: {symbols}")

    def simulate_trade(self, order_id: str, price: float, volume: int):
        """
        模拟成交 (用于测试)
        - order_id: 订单ID
        - price: 成交价格
        - volume: 成交数量
        """
        order = self._orders.get(order_id)
        if not order:
            self.write_error(f"模拟成交失败,订单不存在: {order_id}")
            return

        order.traded = volume
        order.status = OrderStatus.ALL_TRADED if volume >= order.volume else OrderStatus.PART_TRADED
        order.update_time = datetime.now()

        if self.on_order:
            self.on_order(order)

        # 生成成交记录
        trade = TradeData(
            symbol=order.symbol,
            exchange=order.exchange,
            order_id=order_id,
            trade_id=f"trade_{order_id}",
            direction=order.direction,
            offset=order.offset,
            price=price,
            volume=volume,
            trade_time=datetime.now(),
            gateway_name=self.gateway_name,
        )

        if self.on_trade:
            self.on_trade(trade)

        # 更新持仓
        self._update_position(order.symbol, order.exchange, order.direction, volume, price)

        self.write_log(
            f"模拟成交: {order.symbol} "
            f"{'买入' if order.direction == OrderDirection.BUY else '卖出'} "
            f"{volume}手 @ {price}"
        )

    def _update_position(self, symbol: str, exchange: str, direction: OrderDirection, volume: int, price: float):
        """更新持仓"""
        key = f"{symbol}_{direction.value}"
        pos = self._positions.get(key)

        if pos:
            # 更新现有持仓
            total_cost = pos.price * pos.volume + price * volume
            pos.volume += volume
            pos.price = total_cost / pos.volume
        else:
            # 新建持仓
            pos = PositionData(
                symbol=symbol,
                exchange=exchange,
                direction=direction,
                volume=volume,
                price=price,
                gateway_name=self.gateway_name,
            )
            self._positions[key] = pos

        if self.on_position:
            self.on_position(pos)
