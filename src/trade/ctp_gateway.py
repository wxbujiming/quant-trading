"""
CTP (SimNow) 期货接口实现
支持两种模式:
  - simulated: 全内存模拟 (默认, 用于测试)
  - real: 通过 ctypes 调用 CTP DLL 连接真实交易环境
"""

import time
import os
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

ENVIRONMENTS = {
    "simnow": {
        "trade": ("182.254.243.31", 30001),
        "market": ("182.254.243.31", 30011),
        "name": "SimNow仿真交易",
    },
    "simnow_7x24": {
        "trade": ("182.254.243.31", 40001),
        "market": ("182.254.243.31", 40011),
        "name": "SimNow 7x24环境",
    },
}


class CtpGateway(BaseGateway):
    """CTP期货接口"""

    def __init__(self, gateway_name: str = "SimNow", setting: dict = None):
        super().__init__(gateway_name, setting)
        setting = setting or {}

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

        # 模式选择
        self._mode = "real" if setting.get("real_mode", False) else "simulated"

        # 模拟模式状态
        self._order_ref = 0
        self._orders: dict = {}
        self._positions: dict = {}
        self._contracts: dict = {}

        # 真实模式状态
        self._td_api = None
        self._md_api = None
        self._real_spi = None
        self._real_md_spi = None
        self._login_ready = False
        self._settlement_confirmed = False
        self._real_account: Optional[AccountData] = None
        self._real_positions: dict = {}
        self._real_orders: dict = {}
        self._req_id = 0
        self._order_ref_real = 0

        # 账户信息缓存
        self._cached_account: Optional[AccountData] = None

        logger.info(
            f"CTP接口初始化: {self.env_name}, "
            f"模式={'真实' if self._mode == 'real' else '模拟'}, "
            f"Broker={self.broker_id}, User={self.user_id}"
        )

    # --------------------------------------------------
    # 连接/断开
    # --------------------------------------------------

    def connect(self) -> bool:
        """连接CTP"""
        if self._mode == "real":
            return self._connect_real()
        return self._connect_simulated()

    def _connect_simulated(self) -> bool:
        """模拟模式连接"""
        self.write_log(f"正在连接 {self.env_name}...")
        self.write_log("注意: 当前使用模拟模式")
        self._connected = True
        self._logined = True
        self._on_connected()
        self._login()
        return True

    def _connect_real(self) -> bool:
        """真实模式连接"""
        from src.trade.ctp_real_api import (
            is_ctp_available, CtpTraderApi, CtpMdApi,
            TraderSpiCb, MdSpiCb,
        )

        if not is_ctp_available():
            self.write_error("CTP DLL 不可用，请确认 vnpy_ctp 已安装")
            return False

        self.write_log(f"正在连接 {self.env_name} (真实模式)...")

        try:
            # 创建 flow 目录
            os.makedirs("./ctp_flow/td", exist_ok=True)
            os.makedirs("./ctp_flow/md", exist_ok=True)

            # 创建 API 实例
            self._td_api = CtpTraderApi("./ctp_flow/td/")
            self._md_api = CtpMdApi("./ctp_flow/md/")

            # 创建并注册 SPI 回调
            self._real_spi = TraderSpiCb()
            self._real_md_spi = MdSpiCb()
            self._setup_spi_callbacks()
            self._td_api.register_spi(self._real_spi)
            self._md_api.register_spi(self._real_md_spi)

            # 注册前置地址
            td_addr = self.trade_addr
            md_addr = self.market_addr
            self._td_api.register_front(f"tcp://{td_addr}")
            self._md_api.register_front(f"tcp://{md_addr}")
            self.write_log(f"交易前置: {td_addr}")
            self.write_log(f"行情前置: {md_addr}")

            # 启动连接
            self._td_api.init()
            self._md_api.init()

            return True

        except Exception as e:
            self.write_error(f"CTP连接失败: {e}")
            logger.exception("[CTP] 连接异常")
            return False

    def close(self):
        """关闭连接"""
        if self._mode == "real" and self._td_api:
            self._td_api.release()
            self._td_api = None
        if self._mode == "real" and self._md_api:
            self._md_api.release()
            self._md_api = None
        self._connected = False
        self._logined = False
        self._login_ready = False
        self.write_log("连接已关闭")

    # --------------------------------------------------
    # SPI 回调设置 (真实模式)
    # --------------------------------------------------

    def _setup_spi_callbacks(self):
        """设置CTP回调处理"""
        if not self._real_spi or not self._real_md_spi:
            return

        spi = self._real_spi

        spi.on_front_connected = self._on_td_connected
        spi.on_front_disconnected = lambda r: self.write_log(f"交易前置断开: {r}")
        spi.on_rsp_authenticate = lambda: self._real_login()
        spi.on_rsp_user_login = self._on_real_login
        spi.on_rsp_settlement_confirm = lambda: self._on_settlement_confirmed()
        spi.on_rsp_error = lambda err_id, msg: self.write_error(f"CTP错误 [{err_id}]: {msg}")
        spi.on_rtn_order = self._on_real_order
        spi.on_rtn_trade = self._on_real_trade
        spi.on_rsp_qry_account = self._on_real_account
        spi.on_rsp_qry_position = self._on_real_position

        md_spi = self._real_md_spi
        md_spi.on_front_connected = lambda: self.write_log("行情前置已连接")
        md_spi.on_front_disconnected = lambda r: self.write_log(f"行情前置断开: {r}")
        md_spi.on_rsp_user_login = lambda d: self.write_log("行情登录成功")
        md_spi.on_rtn_depth_market_data = self._on_real_tick

    def _on_td_connected(self):
        """交易前置连接成功"""
        self.write_log("交易前置已连接")
        self._connected = True
        # 发起认证
        self._real_authenticate()

    def _real_authenticate(self):
        """CTP 认证"""
        # CTP 6.7 使用 app_id + auth_code 认证
        self.write_log(f"正在认证 (AppID: {self.app_id})...")
        # 认证通过后会自动触发 onRspAuthenticate → _real_login
        # 部分 SimNow 环境不需要认证，直接登录
        self._real_login()

    def _real_login(self):
        """CTP 登录"""
        if not self._td_api:
            return
        self._req_id += 1
        ret = self._td_api.req_user_login(
            self.broker_id, self.user_id, self.password, self._req_id
        )
        self.write_log(f"登录请求已发送 (ret={ret})")

    def _on_real_login(self, login_info):
        """登录成功回调"""
        self._logined = True
        self._login_ready = True
        self.write_log(
            f"登录成功: {login_info.user_id}@{login_info.broker_id}, "
            f"交易日={login_info.trading_day}, "
            f"FrontID={login_info.front_id}, SessionID={login_info.session_id}"
        )

        # 保存 front_id / session_id 用于订单号
        self._real_front_id = login_info.front_id
        self._real_session_id = login_info.session_id

        # 确认结算单
        self._req_id += 1
        self._td_api.req_settlement_info_confirm(
            self.broker_id, self.user_id, self._req_id
        )

    def _on_settlement_confirmed(self):
        """结算确认成功"""
        self._settlement_confirmed = True
        self.write_log("结算确认完成")

        # 查询账户和持仓
        self._req_id += 1
        self._td_api.req_qry_trading_account(self.broker_id, self.user_id, self._req_id)

        self._req_id += 1
        self._td_api.req_qry_investor_position(self.broker_id, self.user_id, "", self._req_id)

    # --------------------------------------------------
    # 订单操作
    # --------------------------------------------------

    def send_order(self, order: OrderData) -> str:
        """发送订单"""
        if self._mode == "real":
            return self._send_order_real(order)
        return self._send_order_simulated(order)

    def _send_order_simulated(self, order: OrderData) -> str:
        """模拟模式下单"""
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

    def _send_order_real(self, order: OrderData) -> str:
        """真实模式下单"""
        from src.trade.ctp_real_api import (
            CThostFtdcInputOrderField,
            CTPDirection, CTPOffset,
        )

        if not self._td_api or not self._login_ready:
            self.write_error("CTP未就绪,无法下单")
            return ""

        self._order_ref_real += 1
        order_ref = f"{self._order_ref_real:06d}"

        # 构建 CTP InputOrder
        ctp_order = CThostFtdcInputOrderField()
        ctp_order.BrokerID = self.broker_id.encode()
        ctp_order.InvestorID = self.user_id.encode()
        ctp_order.InstrumentID = order.symbol.encode()
        ctp_order.OrderRef = order_ref.encode()
        ctp_order.UserID = self.user_id.encode()

        # 方向
        if order.direction == OrderDirection.BUY:
            ctp_order.Direction = CTPDirection.Buy
        else:
            ctp_order.Direction = CTPDirection.Sell

        # 开平
        if order.offset == "open":
            ctp_order.CombOffsetFlag = CTPOffset.Open
        elif order.offset == "close":
            ctp_order.CombOffsetFlag = CTPOffset.Close
        elif order.offset == "close_today":
            ctp_order.CombOffsetFlag = CTPOffset.CloseToday
        else:
            ctp_order.CombOffsetFlag = CTPOffset.Open

        # 价格数量
        ctp_order.LimitPrice = order.price
        ctp_order.VolumeTotalOriginal = order.volume

        # 价格类型: LIMIT
        ctp_order.OrderPriceType = b'2'  # LIMIT
        # 条件: 立即
        ctp_order.ContingentCondition = b'1'
        # 强平原因: 非强平
        ctp_order.ForceCloseReason = b'0'
        # 自动挂起
        ctp_order.IsAutoSuspend = 0
        # 时间条件: GFD
        ctp_order.TimeCondition = b'3'
        # 数量条件: AV
        ctp_order.VolumeCondition = b'1'
        ctp_order.MinVolume = 1
        # 投机
        ctp_order.CombHedgeFlag = b'1'

        # 发送
        self._req_id += 1
        ret = self._td_api.req_order_insert(ctp_order, self._req_id)

        # 生成内部订单ID
        order_id = f"{self._real_front_id}_{self._real_session_id}_{order_ref}"
        order.order_id = order_id
        order.gateway_name = self.gateway_name
        order.status = OrderStatus.NOT_TRADED
        order.create_time = datetime.now()

        self._real_orders[order_id] = order

        self.write_log(
            f"[CTP] 下单: {order.symbol} "
            f"{'买入' if order.direction == OrderDirection.BUY else '卖出'} "
            f"{order.volume}手 @ {order.price} (ref={order_ref})"
        )

        if ret != 0:
            self.write_error(f"CTP下单失败: ret={ret}")
            order.status = OrderStatus.REJECTED
            if self.on_order:
                self.on_order(order)
            return ""

        if self.on_order:
            self.on_order(order)

        return order_id

    def cancel_order(self, order_id: str) -> bool:
        """撤销订单"""
        if self._mode == "real":
            return self._cancel_order_real(order_id)
        return self._cancel_order_simulated(order_id)

    def _cancel_order_simulated(self, order_id: str) -> bool:
        """模拟模式撤单"""
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

    def _cancel_order_real(self, order_id: str) -> bool:
        """真实模式撤单"""
        from src.trade.ctp_real_api import (
            CThostFtdcInputOrderActionField,
            CTPActionFlag,
        )

        if not self._td_api:
            return False

        # 解析 order_id → front_id, session_id, order_ref
        try:
            parts = order_id.split("_")
            front_id = int(parts[0]) if len(parts) >= 3 else 0
            session_id = int(parts[1]) if len(parts) >= 3 else 0
            order_ref = parts[2] if len(parts) >= 3 else order_id
        except (ValueError, IndexError):
            order_ref = order_id
            front_id = 0
            session_id = 0

        action = CThostFtdcInputOrderActionField()
        action.BrokerID = self.broker_id.encode()
        action.InvestorID = self.user_id.encode()
        action.OrderRef = order_ref.encode()
        action.FrontID = front_id
        action.SessionID = session_id
        action.ActionFlag = CTPActionFlag.Delete

        self._req_id += 1
        ret = self._td_api.req_order_action(action, self._req_id)

        if ret != 0:
            self.write_error(f"CTP撤单失败: ret={ret}")
            return False

        self.write_log(f"[CTP] 撤单请求已发送: {order_id}")
        return True

    # --------------------------------------------------
    # 查询
    # --------------------------------------------------

    def query_account(self) -> Optional[AccountData]:
        """查询账户"""
        if self._mode == "real":
            return self._query_account_real()
        return self._query_account_simulated()

    def _query_account_simulated(self) -> AccountData:
        """模拟模式查询账户"""
        account = AccountData(
            account_id=self.user_id,
            balance=1000000.0,
            frozen=0.0,
            available=1000000.0,
            margin=0.0,
            pnl=0.0,
            gateway_name=self.gateway_name,
        )
        if self.on_account:
            self.on_account(account)
        self._cached_account = account
        return account

    def _query_account_real(self) -> Optional[AccountData]:
        """真实模式查询账户"""
        if not self._td_api or not self._login_ready:
            return self._cached_account

        self._req_id += 1
        self._td_api.req_qry_trading_account(self.broker_id, self.user_id, self._req_id)

        # 返回缓存的账户数据（异步查询，数据通过回调更新）
        return self._cached_account

    def query_position(self, symbol: str = "") -> list:
        """查询持仓"""
        if self._mode == "real":
            return self._query_position_real(symbol)
        return self._query_position_simulated(symbol)

    def _query_position_simulated(self, symbol: str = "") -> list:
        """模拟模式查询持仓"""
        positions = []
        for pos in self._positions.values():
            if symbol and pos.symbol != symbol:
                continue
            positions.append(pos)
            if self.on_position:
                self.on_position(pos)
        return positions

    def _query_position_real(self, symbol: str = "") -> list:
        """真实模式查询持仓"""
        if not self._td_api or not self._login_ready:
            return list(self._real_positions.values())

        self._req_id += 1
        self._td_api.req_qry_investor_position(
            self.broker_id, self.user_id, symbol, self._req_id
        )
        return list(self._real_positions.values())

    # --------------------------------------------------
    # 行情订阅
    # --------------------------------------------------

    def subscribe(self, symbols: list):
        """订阅行情"""
        if self._mode == "real" and self._md_api:
            for symbol in symbols:
                ret = self._md_api.subscribe_market_data(symbol)
                self.write_log(f"[CTP] 订阅行情 {symbol}: ret={ret}")
        else:
            self.write_log(f"订阅行情: {symbols}")

    # --------------------------------------------------
    # 订单/持仓查询辅助
    # --------------------------------------------------

    def get_orders(self) -> dict:
        """获取所有订单"""
        return self._real_orders if self._mode == "real" else self._orders

    def get_order(self, order_id: str) -> Optional[OrderData]:
        """获取单个订单"""
        return self._real_orders.get(order_id) if self._mode == "real" else self._orders.get(order_id)

    # --------------------------------------------------
    # 真实模式回调处理
    # --------------------------------------------------

    def _on_real_order(self, order_info):
        """CTP 订单回报"""
        from src.trade.ctp_real_api import CTPOrderStatus

        order_id = f"{self._real_front_id}_{self._real_session_id}_{order_info.order_ref}"

        # 状态映射
        status_map = {
            CTPOrderStatus.AllTraded: OrderStatus.ALL_TRADED,
            CTPOrderStatus.PartTradedQueueing: OrderStatus.PART_TRADED,
            CTPOrderStatus.PartTradedNotQueueing: OrderStatus.PART_TRADED,
            CTPOrderStatus.NoTradeQueueing: OrderStatus.NOT_TRADED,
            CTPOrderStatus.NoTradeNotQueueing: OrderStatus.NOT_TRADED,
            CTPOrderStatus.Canceled: OrderStatus.CANCELED,
            CTPOrderStatus.Unknown: OrderStatus.ERROR,
        }
        status = status_map.get(order_info.order_status, OrderStatus.ERROR)

        # 方向映射
        from src.trade.ctp_real_api import CTPDirection
        direction = OrderDirection.BUY if order_info.direction == CTPDirection.Buy else OrderDirection.SELL

        order = OrderData(
            symbol=order_info.instrument_id,
            exchange=order_info.exchange_id,
            order_id=order_id,
            direction=direction,
            offset=order_info.offset,
            price=order_info.limit_price,
            volume=order_info.volume_original,
            traded=order_info.volume_traded,
            status=status,
            order_type=OrderType.LIMIT,
            gateway_name=self.gateway_name,
            create_time=datetime.now(),
        )

        self._real_orders[order_id] = order

        if self.on_order:
            self.on_order(order)

    def _on_real_trade(self, trade_info):
        """CTP 成交回报"""
        from src.trade.ctp_real_api import CTPDirection

        direction = OrderDirection.BUY if trade_info.direction == CTPDirection.Buy else OrderDirection.SELL

        trade = TradeData(
            symbol=trade_info.instrument_id,
            exchange=trade_info.exchange_id,
            order_id=f"{self._real_front_id}_{self._real_session_id}_{trade_info.order_ref}",
            trade_id=trade_info.trade_id,
            direction=direction,
            offset=trade_info.offset,
            price=trade_info.price,
            volume=trade_info.volume,
            trade_time=datetime.now(),
            gateway_name=self.gateway_name,
        )

        if self.on_trade:
            self.on_trade(trade)

        self.write_log(
            f"[CTP] 成交: {trade.symbol} "
            f"{'买入' if direction == OrderDirection.BUY else '卖出'} "
            f"{trade.volume}手 @ {trade.price}"
        )

    def _on_real_account(self, account_info, is_last: bool):
        """CTP 账户资金回调"""
        account = AccountData(
            account_id=account_info.account_id or self.user_id,
            balance=account_info.balance,
            frozen=account_info.frozen_margin + account_info.commission,
            available=account_info.available,
            margin=account_info.margin,
            pnl=account_info.position_profit + account_info.close_profit,
            gateway_name=self.gateway_name,
        )
        self._cached_account = account

        if is_last and self.on_account:
            self.on_account(account)

    def _on_real_position(self, position_info, is_last: bool):
        """CTP 持仓回调"""
        from src.trade.ctp_real_api import CTPPosiDirection

        direction = OrderDirection.BUY if position_info.direction == CTPPosiDirection.Long else OrderDirection.SELL

        pos = PositionData(
            symbol=position_info.instrument_id,
            exchange="",
            direction=direction,
            volume=position_info.position,
            frozen=position_info.position - (position_info.position - position_info.long_frozen if direction == OrderDirection.BUY else position_info.short_frozen),
            price=position_info.open_cost / position_info.position if position_info.position > 0 else 0,
            pnl=position_info.position_profit,
            gateway_name=self.gateway_name,
        )

        key = f"{pos.symbol}_{direction.value}"
        self._real_positions[key] = pos

        if is_last and self.on_position:
            for p in self._real_positions.values():
                self.on_position(p)

    def _on_real_tick(self, market_data):
        """CTP 行情 Tick 回调"""
        tick = TickData(
            symbol=market_data.InstrumentID.decode(),
            exchange=market_data.ExchangeID.decode(),
            last_price=market_data.LastPrice,
            volume=market_data.Volume,
            open_interest=market_data.OpenInterest,
            bid_price1=market_data.BidPrice1,
            bid_volume1=market_data.BidVolume1,
            ask_price1=market_data.AskPrice1,
            ask_volume1=market_data.AskVolume1,
            bid_price2=market_data.BidPrice2,
            bid_volume2=market_data.BidVolume2,
            ask_price2=market_data.AskPrice2,
            ask_volume2=market_data.AskVolume2,
            bid_price3=market_data.BidPrice3,
            bid_volume3=market_data.BidVolume3,
            ask_price3=market_data.AskPrice3,
            ask_volume3=market_data.AskVolume3,
            bid_price4=market_data.BidPrice4,
            bid_volume4=market_data.BidVolume4,
            ask_price4=market_data.AskPrice4,
            ask_volume4=market_data.AskVolume4,
            bid_price5=market_data.BidPrice5,
            bid_volume5=market_data.BidVolume5,
            ask_price5=market_data.AskPrice5,
            ask_volume5=market_data.AskVolume5,
            gateway_name=self.gateway_name,
        )

        if self.on_tick:
            self.on_tick(tick)

    # --------------------------------------------------
    # 模拟模式辅助 (保持向后兼容)
    # --------------------------------------------------

    def simulate_trade(self, order_id: str, price: float, volume: int):
        """模拟成交 (仅模拟模式)"""
        if self._mode == "real":
            self.write_error("真实模式不支持 simulate_trade")
            return

        order = self._orders.get(order_id)
        if not order:
            self.write_error(f"模拟成交失败,订单不存在: {order_id}")
            return

        order.traded = volume
        order.status = OrderStatus.ALL_TRADED if volume >= order.volume else OrderStatus.PART_TRADED
        order.update_time = datetime.now()

        if self.on_order:
            self.on_order(order)

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

        self._update_position(order.symbol, order.exchange, order.direction, volume, price)

        self.write_log(
            f"模拟成交: {order.symbol} "
            f"{'买入' if order.direction == OrderDirection.BUY else '卖出'} "
            f"{volume}手 @ {price}"
        )

    def _update_position(self, symbol: str, exchange: str, direction: OrderDirection, volume: int, price: float):
        """更新持仓 (仅模拟模式)"""
        key = f"{symbol}_{direction.value}"
        pos = self._positions.get(key)

        if pos:
            total_cost = pos.price * pos.volume + price * volume
            pos.volume += volume
            pos.price = total_cost / pos.volume
        else:
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

    # --------------------------------------------------
    # 连接回调 (保持模拟模式兼容)
    # --------------------------------------------------

    def _on_connected(self):
        """连接成功回调"""
        self.write_log(f"连接成功: {self.env_name}")

    def _login(self):
        """登录 (模拟模式)"""
        self.write_log(f"用户 {self.user_id} 登录成功 (仿真模式)")
