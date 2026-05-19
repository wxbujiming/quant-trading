"""
券商接口抽象基类
定义了所有券商接口必须实现的方法
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime


class OrderStatus(Enum):
    """订单状态"""
    SUBMITTING = "submitting"       # 提交中
    NOT_TRADED = "not_traded"       # 未成交
    PART_TRADED = "part_traded"     # 部分成交
    ALL_TRADED = "all_traded"       # 全部成交
    CANCELED = "canceled"           # 已取消
    REJECTED = "rejected"           # 已拒绝
    ERROR = "error"                 # 错误


class OrderDirection(Enum):
    """委托方向"""
    BUY = "buy"          # 买入/开多
    SELL = "sell"        # 卖出/平多
    SHORT = "short"      # 卖空/开空
    COVER = "cover"      # 买平/平空


class OrderType(Enum):
    """委托类型"""
    MARKET = "market"           # 市价单
    LIMIT = "limit"             # 限价单
    STOP = "stop"               # 止损单
    FAK = "fak"                 # 立即成交剩余撤销
    FOK = "fok"                 # 立即全部成交否则撤销


@dataclass
class OrderData:
    """订单数据"""
    symbol: str                 # 合约代码
    exchange: str               # 交易所
    order_id: str               # 订单ID
    direction: OrderDirection   # 方向
    offset: str                 # 开平标志
    price: float = 0.0          # 价格
    volume: int = 0             # 数量(手)
    traded: int = 0             # 已成交数量
    status: OrderStatus = OrderStatus.SUBMITTING
    order_type: OrderType = OrderType.LIMIT
    gateway_name: str = ""      # 接口名称
    create_time: datetime = field(default_factory=datetime.now)
    update_time: Optional[datetime] = None
    cancel_time: Optional[datetime] = None
    error_msg: str = ""

    def is_active(self) -> bool:
        """是否活跃(未完成)"""
        return self.status in (OrderStatus.SUBMITTING, OrderStatus.NOT_TRADED, OrderStatus.PART_TRADED)

    def is_finished(self) -> bool:
        """是否已完成"""
        return self.status in (OrderStatus.ALL_TRADED, OrderStatus.CANCELED, OrderStatus.REJECTED, OrderStatus.ERROR)


@dataclass
class TradeData:
    """成交数据"""
    symbol: str
    exchange: str
    order_id: str
    trade_id: str
    direction: OrderDirection
    offset: str
    price: float
    volume: int
    trade_time: datetime = field(default_factory=datetime.now)
    gateway_name: str = ""


@dataclass
class PositionData:
    """持仓数据"""
    symbol: str
    exchange: str
    direction: OrderDirection
    volume: int = 0              # 总持仓
    frozen: int = 0              # 冻结数量
    price: float = 0.0           # 持仓均价
    pnl: float = 0.0             # 浮动盈亏
    gateway_name: str = ""

    @property
    def available(self) -> int:
        """可用持仓"""
        return self.volume - self.frozen


@dataclass
class AccountData:
    """账户数据"""
    account_id: str = ""
    balance: float = 0.0          # 总资产
    frozen: float = 0.0           # 冻结资金
    available: float = 0.0        # 可用资金
    margin: float = 0.0           # 占用保证金
    pnl: float = 0.0              # 浮动盈亏
    gateway_name: str = ""


@dataclass
class ContractData:
    """合约数据"""
    symbol: str
    exchange: str
    name: str                     # 合约名称
    product_class: str = ""        # 产品类型
    size: int = 1                  # 合约乘数
    price_tick: float = 0.001      # 最小变动价位
    gateway_name: str = ""


@dataclass
class TickData:
    """TICK行情数据"""
    symbol: str
    exchange: str
    last_price: float = 0.0       # 最新价
    volume: int = 0               # 成交量
    open_interest: int = 0        # 持仓量
    # 五档买卖
    bid_price_1: float = 0.0
    bid_volume_1: int = 0
    ask_price_1: float = 0.0
    ask_volume_1: int = 0
    bid_price_2: float = 0.0
    bid_volume_2: int = 0
    ask_price_2: float = 0.0
    ask_volume_2: int = 0
    bid_price_3: float = 0.0
    bid_volume_3: int = 0
    ask_price_3: float = 0.0
    ask_volume_3: int = 0
    bid_price_4: float = 0.0
    bid_volume_4: int = 0
    ask_price_4: float = 0.0
    ask_volume_4: int = 0
    bid_price_5: float = 0.0
    bid_volume_5: int = 0
    ask_price_5: float = 0.0
    ask_volume_5: int = 0
    datetime: datetime = field(default_factory=datetime.now)
    gateway_name: str = ""


class BaseGateway(ABC):
    """券商接口抽象基类"""

    def __init__(self, gateway_name: str, setting: dict = None):
        self.gateway_name = gateway_name
        self.setting = setting or {}

        # 回调函数
        self.on_tick = None
        self.on_order = None
        self.on_trade = None
        self.on_position = None
        self.on_account = None
        self.on_contract = None
        self.on_error = None
        self.on_disconnected = None  # callback(reason_type: str, reason_code: int)

        # 状态
        self._connected = False
        self._logined = False

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def logined(self) -> bool:
        return self._logined

    @abstractmethod
    def connect(self) -> bool:
        """连接服务器"""
        ...

    @abstractmethod
    def close(self):
        """关闭连接"""
        ...

    @abstractmethod
    def send_order(self, order: OrderData) -> str:
        """发送订单，返回订单ID"""
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """撤销订单"""
        ...

    @abstractmethod
    def query_account(self) -> AccountData:
        """查询账户"""
        ...

    @abstractmethod
    def query_position(self, symbol: str = "") -> list:
        """查询持仓"""
        ...

    def subscribe(self, symbols: list):
        """订阅行情"""
        pass

    def write_log(self, msg: str):
        """写日志"""
        from loguru import logger
        logger.info(f"[{self.gateway_name}] {msg}")

    def write_error(self, msg: str):
        """写错误日志"""
        from loguru import logger
        logger.error(f"[{self.gateway_name}] {msg}")
