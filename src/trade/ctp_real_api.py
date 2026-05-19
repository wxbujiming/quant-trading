"""
CTP (Commodity Trading Platform) API wrapper.

基于 ctp_bridge.dll (C++ bridge) + ctypes 调用 CTP API。
通过 MSVC 编译的 C++ 桥接 DLL 处理 C++ vtable 和 SPI 回调，
Python 端通过 ctypes 调用 C 风格导出函数。

所有外部接口与原 ctypes 方案保持兼容。
"""
import ctypes
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable


# ============================================================
# Bridge DLL 加载
# ============================================================

_bridge: Optional[ctypes.WinDLL] = None


def _find_bridge_dll() -> Optional[str]:
    """查找 ctp_bridge.dll"""
    search_dirs = [
        os.path.join(os.path.dirname(__file__), "..", "..", "ctp_bridge", "bin"),
        os.path.join(os.getcwd(), "ctp_bridge", "bin"),
    ]
    for d in search_dirs:
        p = os.path.join(d, "ctp_bridge.dll")
        if os.path.exists(p):
            return os.path.abspath(p)
    return None


def _load_bridge() -> ctypes.WinDLL:
    global _bridge
    if _bridge is not None:
        return _bridge

    dll_path = _find_bridge_dll()
    if not dll_path:
        raise RuntimeError(
            "ctp_bridge.dll not found. Build it first:\n"
            "  cd ctp_bridge && cl.exe /LD src/ctp_bridge.cpp ..."
        )

    # Add DLL directory to PATH for dependency resolution
    dll_dir = os.path.dirname(dll_path)
    os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")

    _bridge = ctypes.WinDLL(dll_path)
    _setup_func_types(_bridge)
    return _bridge


def is_ctp_available() -> bool:
    """检查 CTP bridge DLL 是否可用"""
    try:
        _load_bridge()
        return True
    except Exception:
        return False


def get_ctp_version() -> str:
    """获取 CTP API 版本号"""
    bridge = _load_bridge()
    bridge.ctp_get_api_version.restype = ctypes.c_char_p
    ver = bridge.ctp_get_api_version()
    return ver.decode("ascii", errors="ignore") if ver else "unknown"


# ============================================================
# Bridge DLL 函数签名配置
# ============================================================

def _setup_func_types(dll: ctypes.WinDLL):
    """配置所有导出函数的参数/返回类型"""
    # Trader API
    dll.ctp_trader_create.restype = ctypes.c_void_p
    dll.ctp_trader_create.argtypes = [ctypes.c_char_p]

    dll.ctp_trader_destroy.argtypes = [ctypes.c_void_p]
    dll.ctp_trader_register_front.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    dll.ctp_trader_init.argtypes = [ctypes.c_void_p]
    dll.ctp_trader_release.argtypes = [ctypes.c_void_p]

    dll.ctp_trader_req_user_login.restype = ctypes.c_int
    dll.ctp_trader_req_user_login.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
        ctypes.c_char_p, ctypes.c_int,
    ]
    dll.ctp_trader_req_user_logout.restype = ctypes.c_int
    dll.ctp_trader_req_user_logout.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int,
    ]
    dll.ctp_trader_req_settlement_info_confirm.restype = ctypes.c_int
    dll.ctp_trader_req_settlement_info_confirm.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int,
    ]
    dll.ctp_trader_req_qry_trading_account.restype = ctypes.c_int
    dll.ctp_trader_req_qry_trading_account.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int,
    ]
    dll.ctp_trader_req_qry_investor_position.restype = ctypes.c_int
    dll.ctp_trader_req_qry_investor_position.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
        ctypes.c_char_p, ctypes.c_int,
    ]
    dll.ctp_trader_req_order_insert.restype = ctypes.c_int
    dll.ctp_trader_req_order_insert.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
    ]
    dll.ctp_trader_req_order_action.restype = ctypes.c_int
    dll.ctp_trader_req_order_action.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
    ]

    # Callback setters (trader)
    dll.ctp_trader_set_on_front_connected.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    dll.ctp_trader_set_on_front_disconnected.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    dll.ctp_trader_set_on_rsp_user_login.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    dll.ctp_trader_set_on_rsp_settlement_confirm.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    dll.ctp_trader_set_on_rsp_qry_account.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    dll.ctp_trader_set_on_rsp_qry_position.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    dll.ctp_trader_set_on_rtn_order.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    dll.ctp_trader_set_on_rtn_trade.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    # MdApi
    dll.ctp_md_create.restype = ctypes.c_void_p
    dll.ctp_md_create.argtypes = [ctypes.c_char_p]
    dll.ctp_md_destroy.argtypes = [ctypes.c_void_p]
    dll.ctp_md_register_front.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    dll.ctp_md_init.argtypes = [ctypes.c_void_p]
    dll.ctp_md_release.argtypes = [ctypes.c_void_p]
    dll.ctp_md_subscribe.restype = ctypes.c_int
    dll.ctp_md_subscribe.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    dll.ctp_md_req_user_login.restype = ctypes.c_int
    dll.ctp_md_req_user_login.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
        ctypes.c_char_p, ctypes.c_int,
    ]

    dll.ctp_md_set_on_front_connected.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    dll.ctp_md_set_on_rsp_user_login.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    dll.ctp_md_set_on_rtn_depth_market_data.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    dll.ctp_get_api_version.restype = ctypes.c_char_p


# ============================================================
# CTP 数据结构 (ctypes)
# ============================================================

TErrorID = ctypes.c_int
TErrorMsg = ctypes.c_char * 81
TBrokerID = ctypes.c_char * 11
TUserID = ctypes.c_char * 16
TPassword = ctypes.c_char * 41
TInstrumentID = ctypes.c_char * 31
TOrderRef = ctypes.c_char * 13
TTradingDay = ctypes.c_char * 9
TExchangeID = ctypes.c_char * 9
TOrderLocalID = ctypes.c_char * 13
TTradeID = ctypes.c_char * 21
TProductInfo = ctypes.c_char * 11
TProtocolInfo = ctypes.c_char * 11
TMacAddress = ctypes.c_char * 21
TIPAddress = ctypes.c_char * 16
TLoginRemark = ctypes.c_char * 36
TInvestorID = ctypes.c_char * 16
TBusinessUnit = ctypes.c_char * 21
TParticipantID = ctypes.c_char * 11
TClientID = ctypes.c_char * 11
TExchangeInstID = ctypes.c_char * 31
TVolume = ctypes.c_int
TPrice = ctypes.c_double
TFrontID = ctypes.c_int
TSessionID = ctypes.c_int
TSequenceNo = ctypes.c_int
TTime = ctypes.c_char * 9
TDate = ctypes.c_char * 9
TOrderSysID = ctypes.c_char * 21
TInvestUnitID = ctypes.c_char * 17
TAccountID = ctypes.c_char * 13
TCurrencyID = ctypes.c_char * 4
TCombOffsetFlag = ctypes.c_char * 3
TCombHedgeFlag = ctypes.c_char * 3
TForceCloseReason = ctypes.c_char * 3
TActionFlag = ctypes.c_char
TVolumeMultiple = ctypes.c_int
TPriceTick = ctypes.c_double
TRatio = ctypes.c_double
TChar = ctypes.c_char
TInt = ctypes.c_int
TDouble = ctypes.c_double


class CThostFtdcRspInfoField(ctypes.Structure):
    """响应信息"""
    _fields_ = [("ErrorID", TErrorID), ("ErrorMsg", TErrorMsg)]


class CThostFtdcRspUserLoginField(ctypes.Structure):
    """用户登录响应"""
    _fields_ = [
        ("TradingDay", TTradingDay), ("LoginTime", TTime),
        ("BrokerID", TBrokerID), ("UserID", TUserID),
        ("SystemName", ctypes.c_char * 41),
        ("FrontID", TFrontID), ("SessionID", TSessionID),
        ("OrderRef", TOrderRef),
        ("SHFETime", TTime), ("DCETime", TTime),
        ("CZCETime", TTime), ("FFEXTime", TTime), ("INETime", TTime),
    ]


class CThostFtdcSettlementInfoConfirmField(ctypes.Structure):
    """结算确认"""
    _fields_ = [
        ("BrokerID", TBrokerID), ("InvestorID", TInvestorID),
        ("ConfirmDate", TDate), ("ConfirmTime", TTime),
        ("SettlementID", TInt), ("AccountID", TAccountID),
        ("CurrencyID", TCurrencyID),
    ]


class CThostFtdcInputOrderField(ctypes.Structure):
    """输入订单"""
    _fields_ = [
        ("BrokerID", TBrokerID), ("InvestorID", TInvestorID),
        ("InstrumentID", TInstrumentID), ("OrderRef", TOrderRef),
        ("UserID", TUserID), ("OrderPriceType", TChar),
        ("Direction", TChar),
        ("CombOffsetFlag", TCombOffsetFlag),
        ("CombHedgeFlag", TCombHedgeFlag),
        ("LimitPrice", TPrice), ("VolumeTotalOriginal", TVolume),
        ("TimeCondition", TChar), ("GTDDate", TDate),
        ("VolumeCondition", TChar), ("MinVolume", TVolume),
        ("ContingentCondition", TChar), ("StopPrice", TPrice),
        ("ForceCloseReason", TForceCloseReason),
        ("IsAutoSuspend", TInt), ("BusinessUnit", TBusinessUnit),
        ("RequestID", TInt), ("UserForceClose", TInt),
        ("IsSwapOrder", TInt), ("ExchangeID", TExchangeID),
        ("InvestUnitID", TInvestUnitID), ("AccountID", TAccountID),
        ("CurrencyID", TCurrencyID), ("ClientID", TClientID),
        ("IPAddress", TIPAddress), ("MacAddress", TMacAddress),
    ]


class CThostFtdcInputOrderActionField(ctypes.Structure):
    """输入订单操作"""
    _fields_ = [
        ("BrokerID", TBrokerID), ("InvestorID", TInvestorID),
        ("OrderActionRef", TInt), ("OrderRef", TOrderRef),
        ("RequestID", TInt), ("FrontID", TFrontID),
        ("SessionID", TSessionID), ("ExchangeID", TExchangeID),
        ("OrderSysID", TOrderSysID), ("ActionFlag", TActionFlag),
        ("LimitPrice", TPrice), ("VolumeChange", TVolume),
        ("UserID", TUserID), ("InstrumentID", TInstrumentID),
        ("InvestUnitID", TInvestUnitID),
        ("IPAddress", TIPAddress), ("MacAddress", TMacAddress),
    ]


class CThostFtdcOrderField(ctypes.Structure):
    """订单"""
    _fields_ = [
        ("BrokerID", TBrokerID), ("InvestorID", TInvestorID),
        ("InstrumentID", TInstrumentID), ("OrderRef", TOrderRef),
        ("UserID", TUserID), ("OrderPriceType", TChar),
        ("Direction", TChar),
        ("CombOffsetFlag", TCombOffsetFlag),
        ("CombHedgeFlag", TCombHedgeFlag),
        ("LimitPrice", TPrice), ("VolumeTotalOriginal", TVolume),
        ("VolumeTraded", TVolume), ("VolumeTotal", TVolume),
        ("OrderDate", TDate), ("OrderTime", TTime),
        ("CancelTime", TTime), ("ActiveTime", TTime),
        ("SuspendTime", TTime), ("UpdateTime", TTime),
        ("StatusMsg", ctypes.c_char * 81),
        ("OrderLocalID", TOrderLocalID), ("ExchangeID", TExchangeID),
        ("ParticipantID", TParticipantID), ("ClientID", TClientID),
        ("ExchangeInstID", TExchangeInstID), ("TraderID", TUserID),
        ("InstallID", TInt), ("OrderSubmitStatus", TChar),
        ("NotifySequence", TSequenceNo), ("TradingDay", TTradingDay),
        ("SettlementID", TInt), ("OrderSysID", TOrderSysID),
        ("OrderSource", TChar), ("OrderStatus", TChar),
        ("OrderType", TChar),
        ("VolumeTradedPart", TVolume),
        ("VolumeTradedTotal", TVolume), ("RequestID", TInt),
        ("BusinessUnit", TBusinessUnit), ("OffsetFlag", TChar),
        ("HedgeFlag", TChar), ("OrderLocalGroupID", TInt),
        ("CancelUserID", TUserID),
        ("RelativeOrderSysID", TOrderSysID),
        ("ZTTotalTradedVolume", TVolume), ("IsSwapOrder", TInt),
        ("BranchID", TBusinessUnit), ("InvestUnitID", TInvestUnitID),
        ("AccountID", TAccountID), ("CurrencyID", TCurrencyID),
        ("ClientID", TClientID),
        ("IPAddress", TIPAddress), ("MacAddress", TMacAddress),
    ]


class CThostFtdcTradeField(ctypes.Structure):
    """成交"""
    _fields_ = [
        ("BrokerID", TBrokerID), ("InvestorID", TInvestorID),
        ("InstrumentID", TInstrumentID), ("OrderRef", TOrderRef),
        ("UserID", TUserID), ("ExchangeID", TExchangeID),
        ("TradeID", TTradeID), ("Direction", TChar),
        ("OrderSysID", TOrderSysID), ("ParticipantID", TParticipantID),
        ("ClientID", TClientID), ("TradingRole", TChar),
        ("ExchangeInstID", TExchangeInstID), ("OffsetFlag", TChar),
        ("HedgeFlag", TChar),
        ("Price", TPrice), ("Volume", TVolume),
        ("TradeDate", TDate), ("TradeTime", TTime),
        ("TradeType", TChar), ("SettlementID", TInt),
        ("BrokerOrderSeq", TSequenceNo), ("OrderLocalID", TOrderLocalID),
        ("ClearingPartID", TParticipantID),
        ("BusinessUnit", TBusinessUnit), ("SequenceNo", TSequenceNo),
        ("TradingDay", TTradingDay),
        ("SettlementID", TInt), ("BrokerSettlement", TInt),
        ("ParticipantID", TParticipantID), ("UserID", TUserID),
        ("InvestUnitID", TInvestUnitID), ("AccountID", TAccountID),
        ("CurrencyID", TCurrencyID), ("ClientID", TClientID),
        ("IPAddress", TIPAddress), ("MacAddress", TMacAddress),
    ]


class CThostFtdcTradingAccountField(ctypes.Structure):
    """资金账户"""
    _fields_ = [
        ("BrokerID", TBrokerID), ("AccountID", TAccountID),
        ("PreMortgage", TDouble), ("PreCredit", TDouble),
        ("PreDeposit", TDouble), ("PreBalance", TDouble),
        ("PreMargin", TDouble), ("InterestBase", TDouble),
        ("Interest", TDouble), ("Deposit", TDouble),
        ("Withdraw", TDouble), ("FrozenMargin", TDouble),
        ("FrozenCash", TDouble), ("FrozenCommission", TDouble),
        ("CurrMargin", TDouble), ("CashIn", TDouble),
        ("Commission", TDouble), ("CloseProfit", TDouble),
        ("PositionProfit", TDouble), ("Balance", TDouble),
        ("Available", TDouble), ("WithdrawQuota", TDouble),
        ("Reserve", TDouble), ("TradingDay", TTradingDay),
        ("SettlementID", TInt),
        ("Credit", TDouble), ("Mortgage", TDouble),
        ("ExchangeMargin", TDouble),
        ("DeliveryMargin", TDouble),
        ("ExchangeDeliveryMargin", TDouble),
        ("ReserveBalance", TDouble), ("CurrencyID", TCurrencyID),
        ("PreFundMortgageIn", TDouble),
        ("PreFundMortgageOut", TDouble),
        ("FundMortgageIn", TDouble), ("FundMortgageOut", TDouble),
        ("FundMortgageAvailable", TDouble),
        ("MortgageableFund", TDouble),
        ("SpecProductMargin", TDouble),
        ("SpecProductFrozenMargin", TDouble),
        ("SpecProductCommission", TDouble),
        ("SpecProductFrozenCommission", TDouble),
        ("SpecProductPositionProfit", TDouble),
        ("SpecProductCloseProfit", TDouble),
        ("BizType", TChar),
        ("FrozenSwap", TDouble), ("RemainSwap", TDouble),
    ]


class CThostFtdcInvestorPositionField(ctypes.Structure):
    """投资者持仓"""
    _fields_ = [
        ("InstrumentID", TInstrumentID), ("BrokerID", TBrokerID),
        ("InvestorID", TInvestorID), ("PosiDirection", TChar),
        ("HedgeFlag", TChar), ("PositionDate", TChar),
        ("YdPosition", TVolume), ("Position", TVolume),
        ("LongFrozen", TVolume), ("ShortFrozen", TVolume),
        ("LongFrozenAmount", TDouble),
        ("ShortFrozenAmount", TDouble),
        ("OpenVolume", TVolume), ("CloseVolume", TVolume),
        ("OpenAmount", TDouble), ("CloseAmount", TDouble),
        ("PositionCost", TDouble), ("PreMargin", TDouble),
        ("UseMargin", TDouble), ("FrozenMargin", TDouble),
        ("FrozenCash", TDouble), ("FrozenCommission", TDouble),
        ("CashIn", TDouble), ("Commission", TDouble),
        ("CloseProfit", TDouble), ("PositionProfit", TDouble),
        ("PreSettlementPrice", TPrice),
        ("SettlementPrice", TPrice), ("TradingDay", TTradingDay),
        ("SettlementID", TInt), ("OpenCost", TDouble),
        ("ExchangeMargin", TDouble), ("CombPosition", TVolume),
        ("CombLongFrozen", TVolume),
        ("CombShortFrozen", TVolume),
        ("CloseProfitByDate", TDouble),
        ("CloseProfitByTrade", TDouble),
        ("TodayPosition", TVolume),
        ("MarginRateByMoney", TRatio),
        ("MarginRateByVolume", TRatio),
        ("StrikeFrozen", TVolume),
        ("StrikeFrozenAmount", TDouble),
        ("AbandonFrozen", TVolume), ("ExchangeID", TExchangeID),
        ("YdStrikeFrozen", TVolume), ("InvestUnitID", TInvestUnitID),
        ("PositionCostOffset", TDouble),
        ("TasPosition", TVolume), ("TasPositionCost", TDouble),
        ("TasOpenVolume", TVolume), ("PositionAmount", TDouble),
    ]


class CThostFtdcDepthMarketDataField(ctypes.Structure):
    """深度行情"""
    _fields_ = [
        ("TradingDay", TTradingDay), ("InstrumentID", TInstrumentID),
        ("ExchangeID", TExchangeID), ("ExchangeInstID", TExchangeInstID),
        ("LastPrice", TPrice), ("PreSettlementPrice", TPrice),
        ("PreClosePrice", TPrice), ("PreOpenInterest", TDouble),
        ("OpenPrice", TPrice), ("HighestPrice", TPrice),
        ("LowestPrice", TPrice), ("Volume", TVolume),
        ("Turnover", TDouble), ("OpenInterest", TDouble),
        ("ClosePrice", TPrice), ("SettlementPrice", TPrice),
        ("UpperLimitPrice", TPrice), ("LowerLimitPrice", TPrice),
        ("PreDelta", TDouble), ("CurrDelta", TDouble),
        ("BidPrice1", TPrice), ("BidVolume1", TVolume),
        ("AskPrice1", TPrice), ("AskVolume1", TVolume),
        ("BidPrice2", TPrice), ("BidVolume2", TVolume),
        ("AskPrice2", TPrice), ("AskVolume2", TVolume),
        ("BidPrice3", TPrice), ("BidVolume3", TVolume),
        ("AskPrice3", TPrice), ("AskVolume3", TVolume),
        ("BidPrice4", TPrice), ("BidVolume4", TVolume),
        ("AskPrice4", TPrice), ("AskVolume4", TVolume),
        ("BidPrice5", TPrice), ("BidVolume5", TVolume),
        ("AskPrice5", TPrice), ("AskVolume5", TVolume),
        ("AveragePrice", TPrice), ("ActionDay", TTradingDay),
    ]


# ============================================================
# 常量 (保持与原接口兼容)
# ============================================================

# ============================================================
# 常量
# ============================================================

THOST_FTDC_D_Buy = b'0'
THOST_FTDC_D_Sell = b'1'
THOST_FTDC_OF_Open = b'0'
THOST_FTDC_OF_Close = b'1'
THOST_FTDC_OF_CloseToday = b'3'
THOST_FTDC_OST_AllTraded = b'0'
THOST_FTDC_OST_PartTradedQueueing = b'1'
THOST_FTDC_OST_PartTradedNotQueueing = b'2'
THOST_FTDC_OST_NoTradeQueueing = b'3'
THOST_FTDC_OST_NoTradeNotQueueing = b'4'
THOST_FTDC_OST_Canceled = b'5'
THOST_FTDC_PD_Long = b'2'
THOST_FTDC_PD_Short = b'3'
THOST_FTDC_AF_Delete = b'0'


class CTPDirection:
    Buy = THOST_FTDC_D_Buy
    Sell = THOST_FTDC_D_Sell


class CTPOffset:
    Open = THOST_FTDC_OF_Open
    Close = THOST_FTDC_OF_Close
    CloseToday = THOST_FTDC_OF_CloseToday


class CTPOrderStatus:
    AllTraded = THOST_FTDC_OST_AllTraded
    PartTradedQueueing = THOST_FTDC_OST_PartTradedQueueing
    PartTradedNotQueueing = THOST_FTDC_OST_PartTradedNotQueueing
    NoTradeQueueing = THOST_FTDC_OST_NoTradeQueueing
    NoTradeNotQueueing = THOST_FTDC_OST_NoTradeNotQueueing
    Canceled = THOST_FTDC_OST_Canceled
    Unknown = b'a'


class CTPPosiDirection:
    Long = THOST_FTDC_PD_Long
    Short = THOST_FTDC_PD_Short


class CTPActionFlag:
    Delete = THOST_FTDC_AF_Delete


# ============================================================
# Pythonic 数据结构
# ============================================================

@dataclass
class CtpLoginInfo:
    trading_day: str = ""
    login_time: str = ""
    broker_id: str = ""
    user_id: str = ""
    front_id: int = 0
    session_id: int = 0
    order_ref: str = ""
    system_name: str = ""


@dataclass
class CtpAccountInfo:
    account_id: str = ""
    balance: float = 0.0
    available: float = 0.0
    margin: float = 0.0
    frozen_margin: float = 0.0
    commission: float = 0.0
    close_profit: float = 0.0
    position_profit: float = 0.0
    currency_id: str = "CNY"
    pre_balance: float = 0.0
    deposit: float = 0.0
    withdraw: float = 0.0


@dataclass
class CtpPositionInfo:
    instrument_id: str = ""
    direction: bytes = b""
    position: int = 0
    yd_position: int = 0
    today_position: int = 0
    position_cost: float = 0.0
    use_margin: float = 0.0
    open_cost: float = 0.0
    settlement_price: float = 0.0
    position_profit: float = 0.0
    long_frozen: int = 0
    short_frozen: int = 0


@dataclass
class CtpOrderInfo:
    order_ref: str = ""
    order_status: bytes = b""
    direction: bytes = b""
    instrument_id: str = ""
    exchange_id: str = ""
    offset: bytes = b""
    limit_price: float = 0.0
    volume_original: int = 0
    volume_traded: int = 0
    front_id: int = 0
    session_id: int = 0


@dataclass
class CtpTradeInfo:
    instrument_id: str = ""
    exchange_id: str = ""
    order_ref: str = ""
    trade_id: str = ""
    direction: bytes = b""
    offset: bytes = b""
    price: float = 0.0
    volume: int = 0


# ============================================================
# 工具函数
# ============================================================

def _decode_bytes(raw) -> str:
    """将 ctypes char array 解码为字符串"""
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="ignore").strip("\x00").strip()
    if isinstance(raw, str):
        return raw.strip("\x00").strip()
    # ctypes char array
    try:
        val = raw.value if hasattr(raw, 'value') else bytes(raw)
        if isinstance(val, bytes):
            return val.decode("utf-8", errors="ignore").strip("\x00").strip()
        return str(val).strip("\x00").strip()
    except Exception:
        return str(raw)


# ============================================================
# SPI 回调持有者 (保持与 ctp_gateway.py 兼容)
# ============================================================

class TraderSpiCb:
    """交易 SPI 回调持有者"""
    def __init__(self):
        self.on_front_connected: Optional[Callable] = None
        self.on_front_disconnected: Optional[Callable] = None
        self.on_rsp_authenticate: Optional[Callable] = None
        self.on_rsp_user_login: Optional[Callable] = None
        self.on_rsp_user_logout: Optional[Callable] = None
        self.on_rsp_settlement_confirm: Optional[Callable] = None
        self.on_rsp_order_insert: Optional[Callable] = None
        self.on_rsp_order_action: Optional[Callable] = None
        self.on_rsp_error: Optional[Callable] = None
        self.on_rtn_order: Optional[Callable] = None
        self.on_rtn_trade: Optional[Callable] = None
        self.on_rsp_qry_account: Optional[Callable] = None
        self.on_rsp_qry_position: Optional[Callable] = None


class MdSpiCb:
    """行情 SPI 回调持有者"""
    def __init__(self):
        self.on_front_connected: Optional[Callable] = None
        self.on_front_disconnected: Optional[Callable] = None
        self.on_rsp_user_login: Optional[Callable] = None
        self.on_rtn_depth_market_data: Optional[Callable] = None


# ============================================================
# CTP 交易 API (基于 bridge DLL)
# ============================================================

class CtpTraderApi:
    """CTP 交易接口 (基于 ctp_bridge.dll)"""

    def __init__(self, flow_dir: str = ""):
        dll = _load_bridge()
        fd = flow_dir.encode("utf-8") if flow_dir else b"."
        self._handle = dll.ctp_trader_create(fd)
        if not self._handle:
            raise RuntimeError("Failed to create CTP trader API (null handle)")
        self._spi: Optional[TraderSpiCb] = None
        self._callbacks_set = False

    def register_spi(self, spi: TraderSpiCb):
        """注册 SPI 回调"""
        self._spi = spi
        self._register_callbacks()

    def _register_callbacks(self):
        """注册 C 回调 → Python 转发"""
        if self._callbacks_set or not self._spi:
            return
        dll = _load_bridge()

        # CFUNCTYPE must be kept alive as long as callbacks are active
        self._cb_front_connected = ctypes.CFUNCTYPE(None)(
            self._on_front_connected)
        self._cb_front_disconnected = ctypes.CFUNCTYPE(None, ctypes.c_int)(
            self._on_front_disconnected)
        self._cb_rsp_user_login = ctypes.CFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int)(
            self._on_rsp_user_login)
        self._cb_rsp_settlement_confirm = ctypes.CFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int)(
            self._on_rsp_settlement_confirm)
        self._cb_rsp_qry_account = ctypes.CFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int)(
            self._on_rsp_qry_account)
        self._cb_rsp_qry_position = ctypes.CFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int)(
            self._on_rsp_qry_position)
        self._cb_rtn_order = ctypes.CFUNCTYPE(None, ctypes.c_void_p)(
            self._on_rtn_order)
        self._cb_rtn_trade = ctypes.CFUNCTYPE(None, ctypes.c_void_p)(
            self._on_rtn_trade)

        dll.ctp_trader_set_on_front_connected(self._handle, self._cb_front_connected)
        dll.ctp_trader_set_on_front_disconnected(self._handle, self._cb_front_disconnected)
        dll.ctp_trader_set_on_rsp_user_login(self._handle, self._cb_rsp_user_login)
        dll.ctp_trader_set_on_rsp_settlement_confirm(self._handle, self._cb_rsp_settlement_confirm)
        dll.ctp_trader_set_on_rsp_qry_account(self._handle, self._cb_rsp_qry_account)
        dll.ctp_trader_set_on_rsp_qry_position(self._handle, self._cb_rsp_qry_position)
        dll.ctp_trader_set_on_rtn_order(self._handle, self._cb_rtn_order)
        dll.ctp_trader_set_on_rtn_trade(self._handle, self._cb_rtn_trade)

        self._callbacks_set = True

    # ---- Callback forwarders (called from CTP background threads) ----

    def _on_front_connected(self):
        if self._spi and self._spi.on_front_connected:
            self._spi.on_front_connected()

    def _on_front_disconnected(self, reason: int):
        if self._spi and self._spi.on_front_disconnected:
            self._spi.on_front_disconnected(reason)

    def _on_rsp_user_login(self, data_ptr, error_ptr, req_id, is_last):
        if error_ptr:
            err = ctypes.cast(error_ptr, ctypes.POINTER(CThostFtdcRspInfoField))[0]
            if err.ErrorID != 0:
                if self._spi and self._spi.on_rsp_error:
                    self._spi.on_rsp_error(err.ErrorID, _decode_bytes(err.ErrorMsg))
                return
        if data_ptr and self._spi and self._spi.on_rsp_user_login:
            raw = ctypes.cast(data_ptr, ctypes.POINTER(CThostFtdcRspUserLoginField))[0]
            info = CtpLoginInfo(
                trading_day=_decode_bytes(raw.TradingDay),
                login_time=_decode_bytes(raw.LoginTime),
                broker_id=_decode_bytes(raw.BrokerID),
                user_id=_decode_bytes(raw.UserID),
                front_id=raw.FrontID,
                session_id=raw.SessionID,
                order_ref=_decode_bytes(raw.OrderRef),
                system_name=_decode_bytes(raw.SystemName),
            )
            self._spi.on_rsp_user_login(info)

    def _on_rsp_settlement_confirm(self, data_ptr, error_ptr, req_id, is_last):
        if error_ptr:
            err = ctypes.cast(error_ptr, ctypes.POINTER(CThostFtdcRspInfoField))[0]
            if err.ErrorID != 0:
                if self._spi and self._spi.on_rsp_error:
                    self._spi.on_rsp_error(err.ErrorID, _decode_bytes(err.ErrorMsg))
                return
        if self._spi and self._spi.on_rsp_settlement_confirm:
            self._spi.on_rsp_settlement_confirm()

    def _on_rsp_qry_account(self, data_ptr, error_ptr, req_id, is_last):
        if error_ptr:
            err = ctypes.cast(error_ptr, ctypes.POINTER(CThostFtdcRspInfoField))[0]
            if err.ErrorID != 0:
                if self._spi and self._spi.on_rsp_error:
                    self._spi.on_rsp_error(err.ErrorID, _decode_bytes(err.ErrorMsg))
                return
        if data_ptr and self._spi and self._spi.on_rsp_qry_account:
            raw = ctypes.cast(data_ptr, ctypes.POINTER(CThostFtdcTradingAccountField))[0]
            info = CtpAccountInfo(
                account_id=_decode_bytes(raw.AccountID),
                balance=raw.Balance,
                available=raw.Available,
                margin=raw.CurrMargin,
                frozen_margin=raw.FrozenMargin,
                commission=raw.Commission,
                close_profit=raw.CloseProfit,
                position_profit=raw.PositionProfit,
                currency_id=_decode_bytes(raw.CurrencyID),
                pre_balance=raw.PreBalance,
                deposit=raw.Deposit,
                withdraw=raw.Withdraw,
            )
            self._spi.on_rsp_qry_account(info, bool(is_last))

    def _on_rsp_qry_position(self, data_ptr, error_ptr, req_id, is_last):
        if error_ptr:
            err = ctypes.cast(error_ptr, ctypes.POINTER(CThostFtdcRspInfoField))[0]
            if err.ErrorID != 0:
                if self._spi and self._spi.on_rsp_error:
                    self._spi.on_rsp_error(err.ErrorID, _decode_bytes(err.ErrorMsg))
                return
        if data_ptr and self._spi and self._spi.on_rsp_qry_position:
            raw = ctypes.cast(data_ptr, ctypes.POINTER(CThostFtdcInvestorPositionField))[0]
            info = CtpPositionInfo(
                instrument_id=_decode_bytes(raw.InstrumentID),
                direction=raw.PosiDirection if raw.PosiDirection != b'\x00' else b"",
                position=raw.Position,
                yd_position=raw.YdPosition,
                today_position=max(0, raw.Position - raw.YdPosition),
                position_cost=raw.PositionCost,
                use_margin=raw.UseMargin,
                open_cost=raw.OpenCost,
                settlement_price=raw.SettlementPrice,
                position_profit=raw.PositionProfit,
                long_frozen=raw.LongFrozen,
                short_frozen=raw.ShortFrozen,
            )
            self._spi.on_rsp_qry_position(info, bool(is_last))

    def _on_rtn_order(self, data_ptr):
        if data_ptr and self._spi and self._spi.on_rtn_order:
            raw = ctypes.cast(data_ptr, ctypes.POINTER(CThostFtdcOrderField))[0]
            info = CtpOrderInfo(
                order_ref=_decode_bytes(raw.OrderRef),
                order_status=raw.OrderStatus if raw.OrderStatus != b'\x00' else b"",
                direction=raw.Direction if raw.Direction != b'\x00' else b"",
                instrument_id=_decode_bytes(raw.InstrumentID),
                exchange_id=_decode_bytes(raw.ExchangeID),
                offset=raw.OffsetFlag if raw.OffsetFlag != b'\x00' else b"0",
                limit_price=raw.LimitPrice,
                volume_original=raw.VolumeTotalOriginal,
                volume_traded=raw.VolumeTraded,
                front_id=raw.FrontID,
                session_id=raw.SessionID,
            )
            self._spi.on_rtn_order(info)

    def _on_rtn_trade(self, data_ptr):
        if data_ptr and self._spi and self._spi.on_rtn_trade:
            raw = ctypes.cast(data_ptr, ctypes.POINTER(CThostFtdcTradeField))[0]
            info = CtpTradeInfo(
                instrument_id=_decode_bytes(raw.InstrumentID),
                exchange_id=_decode_bytes(raw.ExchangeID),
                order_ref=_decode_bytes(raw.OrderRef),
                trade_id=_decode_bytes(raw.TradeID),
                direction=raw.Direction if raw.Direction != b'\x00' else b"",
                offset=raw.OffsetFlag if raw.OffsetFlag != b'\x00' else b"",
                price=raw.Price,
                volume=raw.Volume,
            )
            self._spi.on_rtn_trade(info)

    # ---- API 方法转发 ----

    def register_front(self, address: str):
        dll = _load_bridge()
        dll.ctp_trader_register_front(self._handle, address.encode("utf-8"))

    def init(self):
        dll = _load_bridge()
        dll.ctp_trader_init(self._handle)

    def release(self):
        if self._handle:
            dll = _load_bridge()
            dll.ctp_trader_destroy(self._handle)
            self._handle = None

    def reinit(self, flow_dir: str = "") -> bool:
        """
        释放旧 API 并重新创建（用于断线重连）

        Args:
            flow_dir: 新的 flow 目录，为空则使用内存模式

        Returns:
            是否成功
        """
        self.release()
        self._callbacks_set = False
        try:
            dll = _load_bridge()
            fd = flow_dir.encode("utf-8") if flow_dir else b"."
            self._handle = dll.ctp_trader_create(fd)
            if not self._handle:
                return False
            if self._spi:
                self._register_callbacks()
            return True
        except Exception:
            return False

    def req_user_login(self, broker_id: str, user_id: str, password: str, req_id: int) -> int:
        dll = _load_bridge()
        return dll.ctp_trader_req_user_login(
            self._handle,
            broker_id.encode("utf-8"),
            user_id.encode("utf-8"),
            password.encode("utf-8"),
            req_id,
        )

    def req_user_logout(self, broker_id: str, user_id: str, req_id: int) -> int:
        dll = _load_bridge()
        return dll.ctp_trader_req_user_logout(
            self._handle,
            broker_id.encode("utf-8"),
            user_id.encode("utf-8"),
            req_id,
        )

    def req_settlement_info_confirm(self, broker_id: str, investor_id: str, req_id: int) -> int:
        dll = _load_bridge()
        return dll.ctp_trader_req_settlement_info_confirm(
            self._handle,
            broker_id.encode("utf-8"),
            investor_id.encode("utf-8"),
            req_id,
        )

    def req_qry_trading_account(self, broker_id: str, investor_id: str, req_id: int) -> int:
        dll = _load_bridge()
        return dll.ctp_trader_req_qry_trading_account(
            self._handle,
            broker_id.encode("utf-8"),
            investor_id.encode("utf-8"),
            req_id,
        )

    def req_qry_investor_position(self, broker_id: str, investor_id: str, symbol: str, req_id: int) -> int:
        dll = _load_bridge()
        return dll.ctp_trader_req_qry_investor_position(
            self._handle,
            broker_id.encode("utf-8"),
            investor_id.encode("utf-8"),
            symbol.encode("utf-8"),
            req_id,
        )

    def req_order_insert(self, order_field, req_id: int) -> int:
        dll = _load_bridge()
        if isinstance(order_field, dict):
            field = CThostFtdcInputOrderField()
            for key, val in order_field.items():
                self._set_field(field, key, val)
            return dll.ctp_trader_req_order_insert(self._handle, ctypes.byref(field), req_id)
        return dll.ctp_trader_req_order_insert(self._handle, ctypes.byref(order_field), req_id)

    def req_order_action(self, action_field, req_id: int) -> int:
        dll = _load_bridge()
        if isinstance(action_field, dict):
            field = CThostFtdcInputOrderActionField()
            for key, val in action_field.items():
                self._set_field(field, key, val)
            return dll.ctp_trader_req_order_action(self._handle, ctypes.byref(field), req_id)
        return dll.ctp_trader_req_order_action(self._handle, ctypes.byref(action_field), req_id)

    @staticmethod
    def _set_field(struct, key: str, value):
        """设置 ctypes struct 的字段值"""
        if value is None:
            return
        if isinstance(value, str):
            setattr(struct, key, value.encode("utf-8"))
        elif isinstance(value, bytes):
            setattr(struct, key, value)
        else:
            setattr(struct, key, value)

    def __del__(self):
        self.release()


# ============================================================
# CTP 行情 API (基于 bridge DLL)
# ============================================================

class CtpMdApi:
    """CTP 行情接口 (基于 ctp_bridge.dll)"""

    def __init__(self, flow_dir: str = ""):
        dll = _load_bridge()
        fd = flow_dir.encode("utf-8") if flow_dir else b"."
        self._handle = dll.ctp_md_create(fd)
        if not self._handle:
            raise RuntimeError("Failed to create CTP MD API (null handle)")
        self._spi: Optional[MdSpiCb] = None
        self._callbacks_set = False

    def register_spi(self, spi: MdSpiCb):
        self._spi = spi
        self._register_callbacks()

    def _register_callbacks(self):
        if self._callbacks_set or not self._spi:
            return
        dll = _load_bridge()

        self._cb_front_connected = ctypes.CFUNCTYPE(None)(self._on_front_connected)
        self._cb_rsp_user_login = ctypes.CFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int)(
            self._on_rsp_user_login)
        self._cb_rtn_depth_market_data = ctypes.CFUNCTYPE(None, ctypes.c_void_p)(
            self._on_rtn_depth_market_data)

        dll.ctp_md_set_on_front_connected(self._handle, self._cb_front_connected)
        dll.ctp_md_set_on_rsp_user_login(self._handle, self._cb_rsp_user_login)
        dll.ctp_md_set_on_rtn_depth_market_data(self._handle, self._cb_rtn_depth_market_data)
        self._callbacks_set = True

    def _on_front_connected(self):
        if self._spi and self._spi.on_front_connected:
            self._spi.on_front_connected()

    def _on_rsp_user_login(self, data_ptr, error_ptr, req_id, is_last):
        if self._spi and self._spi.on_rsp_user_login:
            raw = None
            if data_ptr:
                raw = ctypes.cast(data_ptr, ctypes.POINTER(CThostFtdcRspUserLoginField))[0]
            self._spi.on_rsp_user_login(raw)

    def _on_rtn_depth_market_data(self, data_ptr):
        if data_ptr and self._spi and self._spi.on_rtn_depth_market_data:
            raw = ctypes.cast(data_ptr, ctypes.POINTER(CThostFtdcDepthMarketDataField))[0]
            self._spi.on_rtn_depth_market_data(raw)

    def register_front(self, address: str):
        dll = _load_bridge()
        dll.ctp_md_register_front(self._handle, address.encode("utf-8"))

    def init(self):
        dll = _load_bridge()
        dll.ctp_md_init(self._handle)

    def release(self):
        if self._handle:
            dll = _load_bridge()
            dll.ctp_md_destroy(self._handle)
            self._handle = None

    def reinit(self, flow_dir: str = "") -> bool:
        """释放旧 API 并重新创建（用于断线重连）"""
        self.release()
        self._callbacks_set = False
        try:
            dll = _load_bridge()
            fd = flow_dir.encode("utf-8") if flow_dir else b"."
            self._handle = dll.ctp_md_create(fd)
            if not self._handle:
                return False
            if self._spi:
                self._register_callbacks()
            return True
        except Exception:
            return False

    def subscribe_market_data(self, symbol: str) -> int:
        dll = _load_bridge()
        return dll.ctp_md_subscribe(self._handle, symbol.encode("utf-8"))

    def req_user_login(self, broker_id: str, user_id: str, password: str, req_id: int) -> int:
        dll = _load_bridge()
        return dll.ctp_md_req_user_login(
            self._handle,
            broker_id.encode("utf-8"),
            user_id.encode("utf-8"),
            password.encode("utf-8"),
            req_id,
        )

    def __del__(self):
        self.release()


# ============================================================
# 兼容旧接口的字段类型 (dict 子类)
# ============================================================

class CThostFtdcInputOrderFieldDict(dict):
    """下单请求字段 (dict 子类, 保持旧接口兼容)"""
    def __getattr__(self, name):
        if name in self:
            return self[name]
        return ""

    def __setattr__(self, name, value):
        self[name] = value

    def to_dict(self) -> dict:
        return dict(self)
