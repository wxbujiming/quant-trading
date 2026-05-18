"""
ctypes-based CTP (Commodity Trading Platform) API wrapper.

直接通过 ctypes 调用 CTP DLL，无需 vnpy_ctp 编译扩展。
支持 CTP 6.7.x API (thosttraderapi_se.dll / thostmduserapi_se.dll)。
"""

import ctypes
import ctypes.wintypes
import os
import struct
from typing import Optional, Callable, Any
from dataclasses import dataclass
from datetime import datetime, timezone
from loguru import logger

# ============================================================
# DLL 加载
# ============================================================

_td_dll: Optional[ctypes.WinDLL] = None
_md_dll: Optional[ctypes.WinDLL] = None

# CTP DLL 搜索路径
_CTP_DLL_PATHS = [
    # vnpy_ctp 安装路径
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "..", ".venv", "Lib", "site-packages", "vnpy_ctp", "api"),
    # 系统 site-packages
    "D:/software/python/Lib/site-packages/vnpy_ctp/api",
    # 当前目录
    os.getcwd(),
]


def _find_ctp_dll_dir() -> Optional[str]:
    """查找包含 CTP DLL 的目录"""
    for path in _CTP_DLL_PATHS:
        dll_path = os.path.join(path, "thosttraderapi_se.dll")
        if os.path.exists(dll_path):
            return os.path.abspath(path)
    return None


def _load_dlls() -> tuple[ctypes.WinDLL, ctypes.WinDLL]:
    """加载 CTP DLL，返回 (td_dll, md_dll)"""
    global _td_dll, _md_dll

    if _td_dll is not None:
        return _td_dll, _md_dll

    # 查找 DLL 目录
    dll_dir = _find_ctp_dll_dir()
    if dll_dir:
        # Python 3.8+ 需要将 DLL 目录加入搜索路径
        try:
            ctypes.windll.kernel32.SetDllDirectoryW(dll_dir)
        except Exception:
            os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")
        logger.debug(f"[CTP] DLL directory: {dll_dir}")
    else:
        logger.warning("[CTP] CTP DLL directory not found, trying default search path")

    _td_dll = ctypes.WinDLL("thosttraderapi_se.dll")
    _md_dll = ctypes.WinDLL("thostmduserapi_se.dll")
    return _td_dll, _md_dll


# ============================================================
# CTP 字段类型 (对应 ThostFtdcUserApiStruct.h 中的 typedef)
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
TProductClass = ctypes.c_char * 9
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
TOrderStatus = ctypes.c_char  # '0'=AllTraded, '1'=PartTraded...
TOrderSubmitStatus = ctypes.c_char
TActionFlag = ctypes.c_char
TVolumeMultiple = ctypes.c_int
TPriceTick = ctypes.c_double
TUpperLimitPrice = ctypes.c_double
TLowerLimitPrice = ctypes.c_double
TProductName = ctypes.c_char * 21
TMaxMarginSideRatio = ctypes.c_double
TRatio = ctypes.c_double
TYear = ctypes.c_int
TMonth = ctypes.c_int
TIsLast = ctypes.c_bool  # 注意: CTP bool 是 int, 但 c_bool 可以工作
TChar = ctypes.c_char
TInt = ctypes.c_int
TDouble = ctypes.c_double

# ============================================================
# CTP 数据结构定义 (对应 ThostFtdcUserApiStruct.h)
# ============================================================


class CThostFtdcRspInfoField(ctypes.Structure):
    """响应信息"""
    _fields_ = [
        ("ErrorID", TErrorID),
        ("ErrorMsg", TErrorMsg),
    ]


class CThostFtdcReqUserLoginField(ctypes.Structure):
    """用户登录请求"""
    _fields_ = [
        ("BrokerID", TBrokerID),
        ("UserID", TUserID),
        ("Password", TPassword),
        ("UserProductInfo", TProductInfo),
        ("InterfaceProductInfo", TProductInfo),
        ("ProtocolInfo", TProtocolInfo),
        ("MacAddress", TMacAddress),
        ("ClientIPAddress", TIPAddress),
        ("LoginRemark", TLoginRemark),
    ]


class CThostFtdcRspUserLoginField(ctypes.Structure):
    """用户登录响应"""
    _fields_ = [
        ("TradingDay", TTradingDay),
        ("LoginTime", TTime),
        ("BrokerID", TBrokerID),
        ("UserID", TUserID),
        ("SystemName", ctypes.c_char * 41),
        ("FrontID", TFrontID),
        ("SessionID", TSessionID),
        ("OrderRef", TOrderRef),
        ("SHFETime", TTime),
        ("DCETime", TTime),
        ("CZCETime", TTime),
        ("FFEXTime", TTime),
        ("INETime", TTime),
    ]


class CThostFtdcUserLogoutField(ctypes.Structure):
    """用户登出请求"""
    _fields_ = [
        ("BrokerID", TBrokerID),
        ("UserID", TUserID),
    ]


class CThostFtdcSettlementInfoConfirmField(ctypes.Structure):
    """结算确认"""
    _fields_ = [
        ("BrokerID", TBrokerID),
        ("InvestorID", TInvestorID),
        ("ConfirmDate", TDate),
        ("ConfirmTime", TTime),
        ("SettlementID", TInt),
        ("AccountID", TAccountID),
        ("CurrencyID", TCurrencyID),
    ]


class CThostFtdcInputOrderField(ctypes.Structure):
    """输入订单"""
    _fields_ = [
        ("BrokerID", TBrokerID),
        ("InvestorID", TInvestorID),
        ("InstrumentID", TInstrumentID),
        ("OrderRef", TOrderRef),
        ("UserID", TUserID),
        ("OrderPriceType", TChar),
        ("Direction", TChar),
        ("CombOffsetFlag", TCombOffsetFlag),
        ("CombHedgeFlag", TCombHedgeFlag),
        ("LimitPrice", TPrice),
        ("VolumeTotalOriginal", TVolume),
        ("TimeCondition", TChar),
        ("GTDDate", TDate),
        ("VolumeCondition", TChar),
        ("MinVolume", TVolume),
        ("ContingentCondition", TChar),
        ("StopPrice", TPrice),
        ("ForceCloseReason", TForceCloseReason),
        ("IsAutoSuspend", TInt),
        ("BusinessUnit", TBusinessUnit),
        ("RequestID", TInt),
        ("UserForceClose", TInt),
        ("IsSwapOrder", TInt),
        ("ExchangeID", TExchangeID),
        ("InvestUnitID", TInvestUnitID),
        ("AccountID", TAccountID),
        ("CurrencyID", TCurrencyID),
        ("ClientID", TClientID),
        ("IPAddress", TIPAddress),
        ("MacAddress", TMacAddress),
    ]


class CThostFtdcInputOrderActionField(ctypes.Structure):
    """输入订单操作"""
    _fields_ = [
        ("BrokerID", TBrokerID),
        ("InvestorID", TInvestorID),
        ("OrderActionRef", TInt),
        ("OrderRef", TOrderRef),
        ("RequestID", TInt),
        ("FrontID", TFrontID),
        ("SessionID", TSessionID),
        ("ExchangeID", TExchangeID),
        ("OrderSysID", TOrderSysID),
        ("ActionFlag", TActionFlag),
        ("LimitPrice", TPrice),
        ("VolumeChange", TVolume),
        ("UserID", TUserID),
        ("InstrumentID", TInstrumentID),
        ("InvestUnitID", TInvestUnitID),
        ("IPAddress", TIPAddress),
        ("MacAddress", TMacAddress),
    ]


class CThostFtdcOrderField(ctypes.Structure):
    """订单"""
    _fields_ = [
        ("BrokerID", TBrokerID),
        ("InvestorID", TInvestorID),
        ("InstrumentID", TInstrumentID),
        ("OrderRef", TOrderRef),
        ("UserID", TUserID),
        ("OrderPriceType", TChar),
        ("Direction", TChar),
        ("CombOffsetFlag", TCombOffsetFlag),
        ("CombHedgeFlag", TCombHedgeFlag),
        ("LimitPrice", TPrice),
        ("VolumeTotalOriginal", TVolume),
        ("VolumeTraded", TVolume),
        ("VolumeTotal", TVolume),
        ("OrderDate", TDate),
        ("OrderTime", TTime),
        ("CancelTime", TTime),
        ("ActiveTime", TTime),
        ("SuspendTime", TTime),
        ("UpdateTime", TTime),
        ("StatusMsg", ctypes.c_char * 81),
        ("OrderLocalID", TOrderLocalID),
        ("ExchangeID", TExchangeID),
        ("ParticipantID", TParticipantID),
        ("ClientID", TClientID),
        ("ExchangeInstID", TExchangeInstID),
        ("TraderID", TUserID),
        ("InstallID", TInt),
        ("OrderSubmitStatus", TOrderSubmitStatus),
        ("NotifySequence", TSequenceNo),
        ("TradingDay", TTradingDay),
        ("SettlementID", TInt),
        ("OrderSysID", TOrderSysID),
        ("OrderSource", TChar),
        ("OrderStatus", TOrderStatus),
        ("OrderType", TChar),
        ("VolumeTradedPart", TVolume),
        ("VolumeTradedTotal", TVolume),
        ("RequestID", TInt),
        ("BusinessUnit", TBusinessUnit),
        ("OffsetFlag", TChar),
        ("HedgeFlag", TChar),
        ("OrderLocalGroupID", TInt),
        ("CancelUserID", TUserID),
        ("RelativeOrderSysID", TOrderSysID),
        ("ZTTotalTradedVolume", TVolume),
        ("IsSwapOrder", TInt),
        ("BranchID", TBusinessUnit),
        ("InvestUnitID", TInvestUnitID),
        ("AccountID", TAccountID),
        ("CurrencyID", TCurrencyID),
        ("ClientID", TClientID),
        ("IPAddress", TIPAddress),
        ("MacAddress", TMacAddress),
    ]


class CThostFtdcTradeField(ctypes.Structure):
    """成交"""
    _fields_ = [
        ("BrokerID", TBrokerID),
        ("InvestorID", TInvestorID),
        ("InstrumentID", TInstrumentID),
        ("OrderRef", TOrderRef),
        ("UserID", TUserID),
        ("ExchangeID", TExchangeID),
        ("TradeID", TTradeID),
        ("Direction", TChar),
        ("OrderSysID", TOrderSysID),
        ("ParticipantID", TParticipantID),
        ("ClientID", TClientID),
        ("TradingRole", TChar),
        ("ExchangeInstID", TExchangeInstID),
        ("OffsetFlag", TChar),
        ("HedgeFlag", TChar),
        ("Price", TPrice),
        ("Volume", TVolume),
        ("TradeDate", TDate),
        ("TradeTime", TTime),
        ("TradeType", TChar),
        ("SettlementID", TInt),
        ("BrokerOrderSeq", TSequenceNo),
        ("OrderLocalID", TOrderLocalID),
        ("ClearingPartID", TParticipantID),
        ("BusinessUnit", TBusinessUnit),
        ("SequenceNo", TSequenceNo),
        ("TradingDay", TTradingDay),
        ("SettlementID", TInt),
        ("BrokerSettlement", TInt),
        ("ParticipantID", TParticipantID),
        ("UserID", TUserID),
        ("InvestUnitID", TInvestUnitID),
        ("AccountID", TAccountID),
        ("CurrencyID", TCurrencyID),
        ("ClientID", TClientID),
        ("IPAddress", TIPAddress),
        ("MacAddress", TMacAddress),
    ]


class CThostFtdcQryTradingAccountField(ctypes.Structure):
    """查询资金账户"""
    _fields_ = [
        ("BrokerID", TBrokerID),
        ("InvestorID", TInvestorID),
        ("CurrencyID", TCurrencyID),
        ("AccountID", TAccountID),
        ("BizType", TChar),
    ]


class CThostFtdcTradingAccountField(ctypes.Structure):
    """资金账户"""
    _fields_ = [
        ("BrokerID", TBrokerID),
        ("AccountID", TAccountID),
        ("PreMortgage", TDouble),
        ("PreCredit", TDouble),
        ("PreDeposit", TDouble),
        ("PreBalance", TDouble),
        ("PreMargin", TDouble),
        ("InterestBase", TDouble),
        ("Interest", TDouble),
        ("Deposit", TDouble),
        ("Withdraw", TDouble),
        ("FrozenMargin", TDouble),
        ("FrozenCash", TDouble),
        ("FrozenCommission", TDouble),
        ("CurrMargin", TDouble),
        ("CashIn", TDouble),
        ("Commission", TDouble),
        ("CloseProfit", TDouble),
        ("PositionProfit", TDouble),
        ("Balance", TDouble),
        ("Available", TDouble),
        ("WithdrawQuota", TDouble),
        ("Reserve", TDouble),
        ("TradingDay", TTradingDay),
        ("SettlementID", TInt),
        ("Credit", TDouble),
        ("Mortgage", TDouble),
        ("ExchangeMargin", TDouble),
        ("DeliveryMargin", TDouble),
        ("ExchangeDeliveryMargin", TDouble),
        ("ReserveBalance", TDouble),
        ("CurrencyID", TCurrencyID),
        ("PreFundMortgageIn", TDouble),
        ("PreFundMortgageOut", TDouble),
        ("FundMortgageIn", TDouble),
        ("FundMortgageOut", TDouble),
        ("FundMortgageAvailable", TDouble),
        ("MortgageableFund", TDouble),
        ("SpecProductMargin", TDouble),
        ("SpecProductFrozenMargin", TDouble),
        ("SpecProductCommission", TDouble),
        ("SpecProductFrozenCommission", TDouble),
        ("SpecProductPositionProfit", TDouble),
        ("SpecProductCloseProfit", TDouble),
        ("SpecProductPositionProfitByAlg", TDouble),
        ("SpecProductExchangeMargin", TDouble),
        ("BizType", TChar),
        ("FrozenSwap", TDouble),
        ("RemainSwap", TDouble),
    ]


class CThostFtdcQryInvestorPositionField(ctypes.Structure):
    """查询投资者持仓"""
    _fields_ = [
        ("BrokerID", TBrokerID),
        ("InvestorID", TInvestorID),
        ("InstrumentID", TInstrumentID),
        ("ExchangeID", TExchangeID),
        ("InvestUnitID", TInvestUnitID),
    ]


class CThostFtdcInvestorPositionField(ctypes.Structure):
    """投资者持仓"""
    _fields_ = [
        ("InstrumentID", TInstrumentID),
        ("BrokerID", TBrokerID),
        ("InvestorID", TInvestorID),
        ("PosiDirection", TChar),
        ("HedgeFlag", TChar),
        ("PositionDate", TChar),
        ("YdPosition", TVolume),
        ("Position", TVolume),
        ("LongFrozen", TVolume),
        ("ShortFrozen", TVolume),
        ("LongFrozenAmount", TDouble),
        ("ShortFrozenAmount", TDouble),
        ("OpenVolume", TVolume),
        ("CloseVolume", TVolume),
        ("OpenAmount", TDouble),
        ("CloseAmount", TDouble),
        ("PositionCost", TDouble),
        ("PreMargin", TDouble),
        ("UseMargin", TDouble),
        ("FrozenMargin", TDouble),
        ("FrozenCash", TDouble),
        ("FrozenCommission", TDouble),
        ("CashIn", TDouble),
        ("Commission", TDouble),
        ("CloseProfit", TDouble),
        ("PositionProfit", TDouble),
        ("PreSettlementPrice", TPrice),
        ("SettlementPrice", TPrice),
        ("TradingDay", TTradingDay),
        ("SettlementID", TInt),
        ("OpenCost", TDouble),
        ("ExchangeMargin", TDouble),
        ("CombPosition", TVolume),
        ("CombLongFrozen", TVolume),
        ("CombShortFrozen", TVolume),
        ("CloseProfitByDate", TDouble),
        ("CloseProfitByTrade", TDouble),
        ("TodayPosition", TVolume),
        ("MarginRateByMoney", TRatio),
        ("MarginRateByVolume", TRatio),
        ("StrikeFrozen", TVolume),
        ("StrikeFrozenAmount", TDouble),
        ("AbandonFrozen", TVolume),
        ("ExchangeID", TExchangeID),
        ("YdStrikeFrozen", TVolume),
        ("InvestUnitID", TInvestUnitID),
        ("PositionCostOffset", TDouble),
        ("TasPosition", TVolume),
        ("TasPositionCost", TDouble),
        ("TasOpenVolume", TVolume),
        ("PositionAmount", TDouble),
    ]


class CThostFtdcDepthMarketDataField(ctypes.Structure):
    """深度行情"""
    _fields_ = [
        ("TradingDay", TTradingDay),
        ("InstrumentID", TInstrumentID),
        ("ExchangeID", TExchangeID),
        ("ExchangeInstID", TExchangeInstID),
        ("LastPrice", TPrice),
        ("PreSettlementPrice", TPrice),
        ("PreClosePrice", TPrice),
        ("PreOpenInterest", TDouble),
        ("OpenPrice", TPrice),
        ("HighestPrice", TPrice),
        ("LowestPrice", TPrice),
        ("Volume", TVolume),
        ("Turnover", TDouble),
        ("OpenInterest", TDouble),
        ("ClosePrice", TPrice),
        ("SettlementPrice", TPrice),
        ("UpperLimitPrice", TPrice),
        ("LowerLimitPrice", TPrice),
        ("PreDelta", TDouble),
        ("CurrDelta", TDouble),
        ("BidPrice1", TPrice),
        ("BidVolume1", TVolume),
        ("AskPrice1", TPrice),
        ("AskVolume1", TVolume),
        ("BidPrice2", TPrice),
        ("BidVolume2", TVolume),
        ("AskPrice2", TPrice),
        ("AskVolume2", TVolume),
        ("BidPrice3", TPrice),
        ("BidVolume3", TVolume),
        ("AskPrice3", TPrice),
        ("AskVolume3", TVolume),
        ("BidPrice4", TPrice),
        ("BidVolume4", TVolume),
        ("AskPrice4", TPrice),
        ("AskVolume4", TVolume),
        ("BidPrice5", TPrice),
        ("BidVolume5", TVolume),
        ("AskPrice5", TPrice),
        ("AskVolume5", TVolume),
        ("AveragePrice", TPrice),
        ("ActionDay", TTradingDay),
    ]


class CThostFtdcSpecificInstrumentField(ctypes.Structure):
    """指定合约"""
    _fields_ = [
        ("InstrumentID", TInstrumentID),
    ]


class CThostFtdcQryInstrumentField(ctypes.Structure):
    """查询合约"""
    _fields_ = [
        ("InstrumentID", TInstrumentID),
        ("ExchangeID", TExchangeID),
        ("ExchangeInstID", TExchangeInstID),
        ("ProductID", TInstrumentID),
    ]


class CThostFtdcInstrumentField(ctypes.Structure):
    """合约信息"""
    _fields_ = [
        ("InstrumentID", TInstrumentID),
        ("ExchangeID", TExchangeID),
        ("InstrumentName", ctypes.c_char * 21),
        ("ExchangeInstID", TExchangeInstID),
        ("ProductID", TInstrumentID),
        ("ProductClass", TProductClass),
        ("DeliveryYear", TYear),
        ("DeliveryMonth", TMonth),
        ("MaxMarketOrderVolume", TVolume),
        ("MinMarketOrderVolume", TVolume),
        ("MaxLimitOrderVolume", TVolume),
        ("MinLimitOrderVolume", TVolume),
        ("VolumeMultiple", TVolumeMultiple),
        ("PriceTick", TPriceTick),
        ("CreateDate", TDate),
        ("OpenDate", TDate),
        ("ExpireDate", TDate),
        ("StartDelivDate", TDate),
        ("EndDelivDate", TDate),
        ("LifePhase", TChar),
        ("IsTrading", TInt),
        ("PositionType", TChar),
        ("PositionDateType", TChar),
        ("LongMarginRatio", TRatio),
        ("ShortMarginRatio", TRatio),
        ("MaxMarginSideRatio", TMaxMarginSideRatio),
        ("UnderlyingInstrID", TInstrumentID),
        ("StrikePrice", TPrice),
        ("OptionsType", TChar),
        ("UnderlyingMultiple", TDouble),
        ("CombinationType", TChar),
    ]


# ============================================================
# CTP 方向/类型常量 (常用)
# ============================================================

class CTPDirection:
    """买卖方向"""
    Buy = '0'
    Sell = '1'


class CTPOffset:
    """开平标志"""
    Open = '0'
    Close = '1'
    CloseToday = '3'
    CloseYesterday = '4'


class CTPOrderStatus:
    """订单状态"""
    AllTraded = '0'
    PartTradedQueueing = '1'
    PartTradedNotQueueing = '2'
    NoTradeQueueing = '3'
    NoTradeNotQueueing = '5'
    Canceled = '4'
    Unknown = 'a'
    NotTraded = 'i'


class CTPPosiDirection:
    """持仓方向"""
    Net = '1'
    Long = '2'
    Short = '3'


class CTPActionFlag:
    """操作标志"""
    Delete = '0'
    Modify = '3'


# ============================================================
# Pythonic 数据结构 (供上层使用)
# ============================================================

@dataclass
class CtpLoginInfo:
    """CTP 登录信息（从 RspUserLogin 提取）"""
    trading_day: str
    login_time: str
    broker_id: str
    user_id: str
    front_id: int
    session_id: int
    order_ref: str
    system_name: str


@dataclass
class CtpAccountInfo:
    """CTP 账户信息（从 TradingAccount 提取）"""
    account_id: str
    balance: float
    available: float
    margin: float
    frozen_margin: float
    commission: float
    close_profit: float
    position_profit: float
    currency_id: str


@dataclass
class CtpPositionInfo:
    """CTP 持仓信息"""
    instrument_id: str
    direction: str  # '2'=Long, '3'=Short
    position: int
    yd_position: int
    today_position: int
    position_cost: float
    use_margin: float
    open_cost: float
    settlement_price: float
    position_profit: float


@dataclass
class CtpOrderInfo:
    """CTP 订单信息"""
    instrument_id: str
    order_ref: str
    order_sys_id: str
    front_id: int
    session_id: int
    direction: str
    offset: str
    limit_price: float
    volume_original: int
    volume_traded: int
    volume_total: int
    order_status: str
    status_msg: str
    exchange_id: str
    order_local_id: str


@dataclass
class CtpTradeInfo:
    """CTP 成交信息"""
    instrument_id: str
    trade_id: str
    order_ref: str
    order_sys_id: str
    direction: str
    offset: str
    price: float
    volume: int
    trade_date: str
    trade_time: str
    exchange_id: str


# ============================================================
# 方法签名定义 (用于 vtable 调用)
# ============================================================

# void (Release, Init)
VOID_FUNC = ctypes.CFUNCTYPE(None, ctypes.c_void_p)
# int (Join, GetTradingDay)
INT_FUNC = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p)
# void RegisterFront(char*)
REG_FRONT_FUNC = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_char_p)
# void RegisterSpi(CThostFtdcTraderSpi*)
REG_SPI_FUNC = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)
# int ReqXxx(req, requestId)
REQ_INT_FUNC = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int)
# int ReqOrderInsert  (takes InputOrderField)
REQ_ORDER_FUNC = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int)
# void SubscribeMarketData(char*)
SUB_MD_FUNC = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_char_p)


# ============================================================
# CThostFtdcTraderSpi - 回调处理 (构造 Fake C++ 对象)
# ============================================================

class TraderSpiCb:
    """
    Trader SPI 回调处理器。
    创建一个可被 CTP API RegisterSpi 接受的"伪 C++ 对象"。

    MSVC x64 对象布局:
      [0] vtable_ptr (8 bytes) → 指向 vtable 数组
      vtable[0] = destructor (scalar deleting dtor)
      vtable[1] = OnFrontConnected
      vtable[2] = OnFrontDisconnected
      vtable[3] = OnHeartBeatWarning
      vtable[4] = OnRspAuthenticate
      ...
    """

    def __init__(self):
        # Python side callbacks
        self.on_front_connected: Optional[Callable] = None
        self.on_front_disconnected: Optional[Callable[[int], None]] = None
        self.on_rsp_user_login: Optional[Callable] = None
        self.on_rsp_order: Optional[Callable] = None
        self.on_rsp_error: Optional[Callable] = None
        self.on_rtn_order: Optional[Callable] = None
        self.on_rtn_trade: Optional[Callable] = None
        self.on_rsp_qry_account: Optional[Callable] = None
        self.on_rsp_qry_position: Optional[Callable] = None
        self.on_rsp_qry_instrument: Optional[Callable] = None
        self.on_rsp_authenticate: Optional[Callable] = None
        self.on_rsp_settlement_confirm: Optional[Callable] = None

        # 创建 vtable
        # CThostFtdcTraderSpi vtable 顺序 (CTP 6.7):
        # 0: ~CThostFtdcTraderSpi() (destructor)
        # 1: OnFrontConnected()
        # 2: OnFrontDisconnected(int nReason)
        # 3: OnHeartBeatWarning(int nTimeLapse)
        # 4: OnRspAuthenticate(CThostFtdcRspAuthenticateField*, CThostFtdcRspInfoField*, int, bool)
        # 5: OnRspUserLogin(CThostFtdcRspUserLoginField*, CThostFtdcRspInfoField*, int, bool)
        # 6: OnRspUserLogout(CThostFtdcUserLogoutField*, CThostFtdcRspInfoField*, int, bool)
        # 7: OnRspOrderInsert(CThostFtdcInputOrderField*, CThostFtdcRspInfoField*, int, bool)
        # 8: OnRspOrderAction(CThostFtdcInputOrderActionField*, CThostFtdcRspInfoField*, int, bool)
        # 9: OnRtnOrder(CThostFtdcOrderField*)
        # 10: OnRtnTrade(CThostFtdcTradeField*)
        # 11: OnErrRtnOrderInsert(CThostFtdcInputOrderField*, CThostFtdcRspInfoField*)
        # 12: OnErrRtnOrderAction(CThostFtdcInputOrderActionField*, CThostFtdcRspInfoField*)
        # 13: OnRspQryOrder(CThostFtdcOrderField*, CThostFtdcRspInfoField*, int, bool)
        # 14: OnRspQryTrade(CThostFtdcTradeField*, CThostFtdcRspInfoField*, int, bool)
        # 15: OnRspQryInvestorPosition(CThostFtdcInvestorPositionField*, CThostFtdcRspInfoField*, int, bool)
        # 16: OnRspQryTradingAccount(CThostFtdcTradingAccountField*, CThostFtdcRspInfoField*, int, bool)
        # 17: OnRspQryInstrument(CThostFtdcInstrumentField*, CThostFtdcRspInfoField*, int, bool)
        # 18: OnRspQryInvestor(CThostFtdcInvestorField*, CThostFtdcRspInfoField*, int, bool)
        # 19: OnRspSettlementInfoConfirm(CThostFtdcSettlementInfoConfirmField*, CThostFtdcRspInfoField*, int, bool)
        # ... more

        # 创建 C 回调函数对象（需要保持引用，防止 GC）
        self._cfunctions = []
        vtable_entries = []

        # [0] 析构函数 (不做任何事)
        dtor = ctypes.CFUNCTYPE(None, ctypes.c_void_p)(lambda self_ptr: None)
        self._cfunctions.append(dtor)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(dtor, ctypes.c_void_p).value))

        # [1] OnFrontConnected
        fn1 = ctypes.CFUNCTYPE(None, ctypes.c_void_p)(lambda self_ptr: self._on_front_connected())
        self._cfunctions.append(fn1)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn1, ctypes.c_void_p).value))

        # [2] OnFrontDisconnected
        fn2 = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_int)(
            lambda self_ptr, reason: self._on_front_disconnected(reason))
        self._cfunctions.append(fn2)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn2, ctypes.c_void_p).value))

        # [3] OnHeartBeatWarning
        fn3 = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_int)(
            lambda self_ptr, lapse: None)
        self._cfunctions.append(fn3)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn3, ctypes.c_void_p).value))

        # [4] OnRspAuthenticate
        fn4 = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_bool)(
            lambda self_ptr, data, info, req_id, is_last: self._on_rsp_authenticate(data, info, req_id, is_last))
        self._cfunctions.append(fn4)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn4, ctypes.c_void_p).value))

        # [5] OnRspUserLogin
        fn5 = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_bool)(
            lambda self_ptr, data, info, req_id, is_last: self._on_rsp_user_login(data, info, req_id, is_last))
        self._cfunctions.append(fn5)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn5, ctypes.c_void_p).value))

        # [6] OnRspUserLogout
        fn6 = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_bool)(
            lambda self_ptr, data, info, req_id, is_last: None)
        self._cfunctions.append(fn6)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn6, ctypes.c_void_p).value))

        # [7] OnRspOrderInsert
        fn7 = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_bool)(
            lambda self_ptr, data, info, req_id, is_last: self._on_rsp_order_insert(data, info, req_id, is_last))
        self._cfunctions.append(fn7)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn7, ctypes.c_void_p).value))

        # [8] OnRspOrderAction
        fn8 = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_bool)(
            lambda self_ptr, data, info, req_id, is_last: None)
        self._cfunctions.append(fn8)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn8, ctypes.c_void_p).value))

        # [9] OnRtnOrder
        fn9 = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)(
            lambda self_ptr, data: self._on_rtn_order(data))
        self._cfunctions.append(fn9)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn9, ctypes.c_void_p).value))

        # [10] OnRtnTrade
        fn10 = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)(
            lambda self_ptr, data: self._on_rtn_trade(data))
        self._cfunctions.append(fn10)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn10, ctypes.c_void_p).value))

        # [11] OnErrRtnOrderInsert
        fn11 = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(
            lambda self_ptr, data, info: None)
        self._cfunctions.append(fn11)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn11, ctypes.c_void_p).value))

        # [12] OnErrRtnOrderAction
        fn12 = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(
            lambda self_ptr, data, info: None)
        self._cfunctions.append(fn12)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn12, ctypes.c_void_p).value))

        # [13] OnRspQryOrder
        fn13 = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_bool)(
            lambda self_ptr, data, info, req_id, is_last: None)
        self._cfunctions.append(fn13)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn13, ctypes.c_void_p).value))

        # [14] OnRspQryTrade
        fn14 = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_bool)(
            lambda self_ptr, data, info, req_id, is_last: None)
        self._cfunctions.append(fn14)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn14, ctypes.c_void_p).value))

        # [15] OnRspQryInvestorPosition
        fn15 = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_bool)(
            lambda self_ptr, data, info, req_id, is_last: self._on_rsp_qry_position(data, info, req_id, is_last))
        self._cfunctions.append(fn15)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn15, ctypes.c_void_p).value))

        # [16] OnRspQryTradingAccount
        fn16 = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_bool)(
            lambda self_ptr, data, info, req_id, is_last: self._on_rsp_qry_account(data, info, req_id, is_last))
        self._cfunctions.append(fn16)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn16, ctypes.c_void_p).value))

        # [17] OnRspQryInstrument
        fn17 = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_bool)(
            lambda self_ptr, data, info, req_id, is_last: self._on_rsp_qry_instrument(data, info, req_id, is_last))
        self._cfunctions.append(fn17)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn17, ctypes.c_void_p).value))

        # [18] OnRspQryInvestor - 不做处理
        fn18 = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_bool)(
            lambda self_ptr, data, info, req_id, is_last: None)
        self._cfunctions.append(fn18)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn18, ctypes.c_void_p).value))

        # [19] OnRspSettlementInfoConfirm
        fn19 = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_bool)(
            lambda self_ptr, data, info, req_id, is_last: self._on_rsp_settlement_confirm(data, info, req_id, is_last))
        self._cfunctions.append(fn19)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn19, ctypes.c_void_p).value))

        # 创建 vtable 数组 (保持引用)
        self._vtable_array = (ctypes.c_void_p * len(vtable_entries))(*vtable_entries)
        self._vtable_size = len(vtable_entries)

        # 创建伪 C++ 对象
        # MSVC x64: 对象的前 8 字节指向 vtable
        obj_size = 8  # 只有 vtable 指针
        self._obj_mem = ctypes.create_string_buffer(obj_size)
        vtable_ptr = ctypes.cast(
            ctypes.pointer(self._vtable_array),
            ctypes.c_void_p
        ).value
        struct.pack_into('<Q', self._obj_mem, 0, vtable_ptr)

        # 获取对象指针
        self.ptr = ctypes.cast(self._obj_mem, ctypes.c_void_p).value

    # ---- 内部回调转发 ----

    def _on_front_connected(self):
        logger.info("[CTP] Trader Front connected")
        if self.on_front_connected:
            self.on_front_connected()

    def _on_front_disconnected(self, reason: int):
        logger.warning(f"[CTP] Trader Front disconnected: reason={reason}")
        if self.on_front_disconnected:
            self.on_front_disconnected(reason)

    def _on_rsp_authenticate(self, data_ptr, info_ptr, req_id, is_last):
        if info_ptr:
            info = ctypes.cast(info_ptr, ctypes.POINTER(CThostFtdcRspInfoField))[0]
            error_id = info.ErrorID
            if error_id != 0:
                logger.error(f"[CTP] Auth failed: {error_id} {info.ErrorMsg.decode('gbk', errors='ignore')}")
                return
        logger.info("[CTP] Auth successful")
        if self.on_rsp_authenticate:
            self.on_rsp_authenticate()

    def _on_rsp_user_login(self, data_ptr, info_ptr, req_id, is_last):
        if info_ptr:
            info = ctypes.cast(info_ptr, ctypes.POINTER(CThostFtdcRspInfoField))[0]
            if info.ErrorID != 0:
                logger.error(f"[CTP] Login failed: {info.ErrorID} {info.ErrorMsg.decode('gbk', errors='ignore')}")
                return
        if data_ptr:
            data = ctypes.cast(data_ptr, ctypes.POINTER(CThostFtdcRspUserLoginField))[0]
            login_info = CtpLoginInfo(
                trading_day=data.TradingDay.decode(),
                login_time=data.LoginTime.decode(),
                broker_id=data.BrokerID.decode(),
                user_id=data.UserID.decode(),
                front_id=data.FrontID,
                session_id=data.SessionID,
                order_ref=data.OrderRef.decode(),
                system_name=data.SystemName.decode(),
            )
            logger.info(f"[CTP] Login successful: {login_info.user_id}@{login_info.broker_id}")
            if self.on_rsp_user_login:
                self.on_rsp_user_login(login_info)

    def _on_rsp_order_insert(self, data_ptr, info_ptr, req_id, is_last):
        if info_ptr:
            info = ctypes.cast(info_ptr, ctypes.POINTER(CThostFtdcRspInfoField))[0]
            if info.ErrorID != 0:
                logger.error(f"[CTP] Order insert failed: {info.ErrorID} {info.ErrorMsg.decode('gbk', errors='ignore')}")
                if self.on_rsp_error:
                    self.on_rsp_error(info.ErrorID, info.ErrorMsg.decode('gbk', errors='ignore'))

    def _on_rtn_order(self, data_ptr):
        if data_ptr and self.on_rtn_order:
            data = ctypes.cast(data_ptr, ctypes.POINTER(CThostFtdcOrderField))[0]
            order = CtpOrderInfo(
                instrument_id=data.InstrumentID.decode(),
                order_ref=data.OrderRef.decode(),
                order_sys_id=data.OrderSysID.decode(),
                front_id=0,
                session_id=0,
                direction=chr(data.Direction) if isinstance(data.Direction, int) else data.Direction.decode(),
                offset=chr(data.OffsetFlag) if isinstance(data.OffsetFlag, int) else data.OffsetFlag.decode(),
                limit_price=data.LimitPrice,
                volume_original=data.VolumeTotalOriginal,
                volume_traded=data.VolumeTraded,
                volume_total=data.VolumeTotal,
                order_status=chr(data.OrderStatus) if isinstance(data.OrderStatus, int) else data.OrderStatus.decode(),
                status_msg=data.StatusMsg.decode('gbk', errors='ignore') if data.StatusMsg else '',
                exchange_id=data.ExchangeID.decode(),
                order_local_id=data.OrderLocalID.decode(),
            )
            self.on_rtn_order(order)

    def _on_rtn_trade(self, data_ptr):
        if data_ptr and self.on_rtn_trade:
            data = ctypes.cast(data_ptr, ctypes.POINTER(CThostFtdcTradeField))[0]
            trade = CtpTradeInfo(
                instrument_id=data.InstrumentID.decode(),
                trade_id=data.TradeID.decode(),
                order_ref=data.OrderRef.decode(),
                order_sys_id=data.OrderSysID.decode(),
                direction=chr(data.Direction) if isinstance(data.Direction, int) else data.Direction.decode(),
                offset=chr(data.OffsetFlag) if isinstance(data.OffsetFlag, int) else data.OffsetFlag.decode(),
                price=data.Price,
                volume=data.Volume,
                trade_date=data.TradeDate.decode(),
                trade_time=data.TradeTime.decode(),
                exchange_id=data.ExchangeID.decode(),
            )
            self.on_rtn_trade(trade)

    def _on_rsp_qry_account(self, data_ptr, info_ptr, req_id, is_last):
        if data_ptr and self.on_rsp_qry_account:
            data = ctypes.cast(data_ptr, ctypes.POINTER(CThostFtdcTradingAccountField))[0]
            account = CtpAccountInfo(
                account_id=data.AccountID.decode(),
                balance=data.Balance,
                available=data.Available,
                margin=data.CurrMargin,
                frozen_margin=data.FrozenMargin,
                commission=data.Commission,
                close_profit=data.CloseProfit,
                position_profit=data.PositionProfit,
                currency_id=data.CurrencyID.decode(),
            )
            self.on_rsp_qry_account(account, is_last)

    def _on_rsp_qry_position(self, data_ptr, info_ptr, req_id, is_last):
        if data_ptr and self.on_rsp_qry_position:
            data = ctypes.cast(data_ptr, ctypes.POINTER(CThostFtdcInvestorPositionField))[0]
            pos = CtpPositionInfo(
                instrument_id=data.InstrumentID.decode(),
                direction=chr(data.PosiDirection) if isinstance(data.PosiDirection, int) else data.PosiDirection.decode(),
                position=data.Position,
                yd_position=data.YdPosition,
                today_position=data.TodayPosition,
                position_cost=data.PositionCost,
                use_margin=data.UseMargin,
                open_cost=data.OpenCost,
                settlement_price=data.SettlementPrice,
                position_profit=data.PositionProfit,
            )
            self.on_rsp_qry_position(pos, is_last)

    def _on_rsp_qry_instrument(self, data_ptr, info_ptr, req_id, is_last):
        if data_ptr and self.on_rsp_qry_instrument:
            data = ctypes.cast(data_ptr, ctypes.POINTER(CThostFtdcInstrumentField))[0]
            self.on_rsp_qry_instrument(data, is_last)

    def _on_rsp_settlement_confirm(self, data_ptr, info_ptr, req_id, is_last):
        if info_ptr:
            info = ctypes.cast(info_ptr, ctypes.POINTER(CThostFtdcRspInfoField))[0]
            if info.ErrorID != 0:
                logger.error(f"[CTP] Settlement confirm failed: {info.ErrorID}")
                return
        logger.info("[CTP] Settlement confirmed")
        if self.on_rsp_settlement_confirm:
            self.on_rsp_settlement_confirm()


# ============================================================
# CThostFtdcMdSpi - 行情回调处理
# ============================================================

class MdSpiCb:
    """
    MD SPI 回调处理器。
    MSVC x64 对象布局与 TraderSpi 类似。
    """

    def __init__(self):
        self.on_front_connected: Optional[Callable] = None
        self.on_front_disconnected: Optional[Callable[[int], None]] = None
        self.on_rsp_user_login: Optional[Callable] = None
        self.on_rtn_depth_market_data: Optional[Callable] = None
        self.on_rsp_sub_market_data: Optional[Callable] = None
        self.on_rsp_error: Optional[Callable] = None

        self._cfunctions = []
        vtable_entries = []

        # CThostFtdcMdSpi vtable (CTP 6.7):
        # [0] ~CThostFtdcMdSpi()
        # [1] OnFrontConnected()
        # [2] OnFrontDisconnected(int)
        # [3] OnHeartBeatWarning(int)
        # [4] OnRspUserLogin(CThostFtdcRspUserLoginField*, CThostFtdcRspInfoField*, int, bool)
        # [5] OnRspUserLogout(CThostFtdcUserLogoutField*, CThostFtdcRspInfoField*, int, bool)
        # [6] OnRspQryMulticastInstrument(CThostFtdcMulticastInstrumentField*, CThostFtdcRspInfoField*, int, bool)
        # [7] OnRtnDepthMarketData(CThostFtdcDepthMarketDataField*)
        # [8] OnRspSubMarketData(CThostFtdcSpecificInstrumentField*, CThostFtdcRspInfoField*, int, bool)
        # [9] OnRspUnSubMarketData(...)
        # [10] OnRspSubForQuoteRspMarketData(...)
        # [11] OnRspUnSubForQuoteRspMarketData(...)

        dtor = ctypes.CFUNCTYPE(None, ctypes.c_void_p)(lambda p: None)
        self._cfunctions.append(dtor)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(dtor, ctypes.c_void_p).value))

        fn1 = ctypes.CFUNCTYPE(None, ctypes.c_void_p)(lambda p: self._on_front_connected())
        self._cfunctions.append(fn1)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn1, ctypes.c_void_p).value))

        fn2 = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_int)(lambda p, r: self._on_front_disconnected(r))
        self._cfunctions.append(fn2)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn2, ctypes.c_void_p).value))

        fn3 = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_int)(lambda p, l: None)
        self._cfunctions.append(fn3)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn3, ctypes.c_void_p).value))

        fn4 = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_bool)(
            lambda p, d, i, r, l: self._on_rsp_user_login(d, i, r, l))
        self._cfunctions.append(fn4)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn4, ctypes.c_void_p).value))

        fn5 = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_bool)(
            lambda p, d, i, r, l: None)
        self._cfunctions.append(fn5)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn5, ctypes.c_void_p).value))

        # [6] OnRspQryMulticastInstrument
        fn6 = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_bool)(
            lambda p, d, i, r, l: None)
        self._cfunctions.append(fn6)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn6, ctypes.c_void_p).value))

        # [7] OnRtnDepthMarketData
        fn7 = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)(
            lambda p, d: self._on_rtn_depth_market_data(d))
        self._cfunctions.append(fn7)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn7, ctypes.c_void_p).value))

        # [8] OnRspSubMarketData
        fn8 = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_bool)(
            lambda p, d, i, r, l: self._on_rsp_sub_market_data(d, i, r, l))
        self._cfunctions.append(fn8)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn8, ctypes.c_void_p).value))

        # [9] OnRspUnSubMarketData
        fn9 = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_bool)(
            lambda p, d, i, r, l: None)
        self._cfunctions.append(fn9)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn9, ctypes.c_void_p).value))

        # [10] OnRspSubForQuoteRspMarketData
        fn10 = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_bool)(
            lambda p, d, i, r, l: None)
        self._cfunctions.append(fn10)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn10, ctypes.c_void_p).value))

        # [11] OnRspUnSubForQuoteRspMarketData
        fn11 = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_bool)(
            lambda p, d, i, r, l: None)
        self._cfunctions.append(fn11)
        vtable_entries.append(ctypes.c_void_p(ctypes.cast(fn11, ctypes.c_void_p).value))

        self._vtable_array = (ctypes.c_void_p * len(vtable_entries))(*vtable_entries)
        self._vtable_size = len(vtable_entries)

        obj_size = 8
        self._obj_mem = ctypes.create_string_buffer(obj_size)
        vtable_ptr = ctypes.cast(ctypes.pointer(self._vtable_array), ctypes.c_void_p).value
        struct.pack_into('<Q', self._obj_mem, 0, vtable_ptr)
        self.ptr = ctypes.cast(self._obj_mem, ctypes.c_void_p).value

    def _on_front_connected(self):
        logger.info("[CTP] MD Front connected")
        if self.on_front_connected:
            self.on_front_connected()

    def _on_front_disconnected(self, reason: int):
        logger.warning(f"[CTP] MD Front disconnected: reason={reason}")
        if self.on_front_disconnected:
            self.on_front_disconnected(reason)

    def _on_rsp_user_login(self, data_ptr, info_ptr, req_id, is_last):
        if info_ptr:
            info = ctypes.cast(info_ptr, ctypes.POINTER(CThostFtdcRspInfoField))[0]
            if info.ErrorID != 0:
                logger.error(f"[CTP] MD login failed: {info.ErrorID}")
                return
        if data_ptr:
            data = ctypes.cast(data_ptr, ctypes.POINTER(CThostFtdcRspUserLoginField))[0]
            logger.info(f"[CTP] MD login successful: {data.UserID.decode()}")
            if self.on_rsp_user_login:
                self.on_rsp_user_login(data)

    def _on_rtn_depth_market_data(self, data_ptr):
        if data_ptr and self.on_rtn_depth_market_data:
            data = ctypes.cast(data_ptr, ctypes.POINTER(CThostFtdcDepthMarketDataField))[0]
            self.on_rtn_depth_market_data(data)

    def _on_rsp_sub_market_data(self, data_ptr, info_ptr, req_id, is_last):
        if info_ptr:
            info = ctypes.cast(info_ptr, ctypes.POINTER(CThostFtdcRspInfoField))[0]
            if info.ErrorID != 0:
                logger.error(f"[CTP] Subscribe failed: {info.ErrorID}")
                return
        if data_ptr and self.on_rsp_sub_market_data:
            data = ctypes.cast(data_ptr, ctypes.POINTER(CThostFtdcSpecificInstrumentField))[0]
            self.on_rsp_sub_market_data(data.InstrumentID.decode())


# ============================================================
# CThostFtdcTraderApi - CTP 交易 API 封装
# ============================================================

class CtpTraderApi:
    """
    通过 ctypes vtable 调用 CThostFtdcTraderApi 的包装类。

    CThostFtdcTraderApi vtable 索引 (CTP 6.7.x):
    [0] ~CThostFtdcTraderApi()
    [1] Release()
    [2] Init()
    [3] Join()
    [4] GetTradingDay()
    [5] RegisterFront(char*)
    [6] RegisterNameServer(char*)
    [7] RegisterFensUserInfo(...)
    [8] RegisterSpi(CThostFtdcTraderSpi*)
    [9] ReqUserLogin(...)
    [10] ReqUserLogout(...)
    [11] ReqOrderInsert(...)
    [12] ReqOrderAction(...)
    [13] ReqSettlementInfoConfirm(...)
    [14] ReqQryInstrument(...)
    [15] ReqQryTradingAccount(...)
    [16] ReqQryInvestorPosition(...)
    [17] ReqQryOrder(...)
    [18] ReqQryTrade(...)
    """

    def __init__(self, flow_path: str = ""):
        _load_dlls()
        self._flow_path = flow_path

        factory = _td_dll['?CreateFtdcTraderApi@CThostFtdcTraderApi@@SAPEAV1@PEBD_N@Z']
        factory.restype = ctypes.c_void_p
        factory.argtypes = [ctypes.c_char_p, ctypes.c_bool]

        self._api_ptr = factory(flow_path.encode('utf-8') if flow_path else b"", False)
        if not self._api_ptr or self._api_ptr < 0x10000:
            raise RuntimeError(f"Failed to create TraderApi, ptr={self._api_ptr}")

        # 读取 vtable
        vtable_data = ctypes.string_at(self._api_ptr, 8)
        self._vtable = struct.unpack('<Q', vtable_data)[0]

        # 缓存 vtable 函数指针
        self._vtable_funcs = (ctypes.c_void_p * 100).from_address(self._vtable)

        self._spi_cb: Optional[TraderSpiCb] = None

        logger.debug(f"[CTP] TraderApi created at {self._api_ptr:#x}, vtable at {self._vtable:#x}")

    @property
    def api_ptr(self) -> int:
        return self._api_ptr

    def _get_vtable_func(self, idx: int, ftype):
        """获取 vtable 中的函数指针并转换为指定类型"""
        ptr = self._vtable_funcs[idx]
        if not ptr:
            raise RuntimeError(f"vtable[{idx}] is NULL")
        return ftype(ptr)

    # ---- 生命周期 ----

    def release(self):
        """Release() - 释放 API"""
        func = self._get_vtable_func(1, VOID_FUNC)
        func(self._api_ptr)

    def init(self):
        """Init() - 初始化连接"""
        func = self._get_vtable_func(2, VOID_FUNC)
        func(self._api_ptr)
        logger.info("[CTP] TraderApi Init() called")

    def join(self) -> int:
        """Join() - 等待退出"""
        func = self._get_vtable_func(3, INT_FUNC)
        ret = func(self._api_ptr)
        return ret

    def get_trading_day(self) -> str:
        """GetTradingDay() - 获取交易日"""
        func = self._get_vtable_func(4, INT_FUNC)
        ret = func(self._api_ptr)
        # GetTradingDay 返回 char* (int as pointer)
        if ret:
            return ctypes.string_at(ret).decode()
        return ""

    # ---- 注册 ----

    def register_front(self, address: str):
        """RegisterFront() - 注册前置机地址"""
        if not address.startswith("tcp://"):
            address = "tcp://" + address
        func = self._get_vtable_func(5, REG_FRONT_FUNC)
        func(self._api_ptr, address.encode('utf-8'))
        logger.info(f"[CTP] Registered front: {address}")

    def register_spi(self, spi: TraderSpiCb):
        """RegisterSpi() - 注册回调"""
        self._spi_cb = spi
        func = self._get_vtable_func(8, REG_SPI_FUNC)
        func(self._api_ptr, ctypes.c_void_p(spi.ptr))
        logger.debug("[CTP] SPI registered")

    # ---- 请求 ----

    def req_user_login(self, broker_id: str, user_id: str, password: str, req_id: int = 1) -> int:
        """ReqUserLogin() - 登录"""
        req = CThostFtdcReqUserLoginField()
        req.BrokerID = broker_id.encode('utf-8')
        req.UserID = user_id.encode('utf-8')
        req.Password = password.encode('utf-8')
        func = self._get_vtable_func(9, REQ_INT_FUNC)
        ret = func(self._api_ptr, ctypes.byref(req), req_id)
        return ret

    def req_settlement_info_confirm(self, broker_id: str, investor_id: str, req_id: int = 2) -> int:
        """ReqSettlementInfoConfirm() - 确认结算单"""
        req = CThostFtdcSettlementInfoConfirmField()
        req.BrokerID = broker_id.encode('utf-8')
        req.InvestorID = investor_id.encode('utf-8')
        func = self._get_vtable_func(13, REQ_INT_FUNC)
        ret = func(self._api_ptr, ctypes.byref(req), req_id)
        return ret

    def req_order_insert(self, order_field: CThostFtdcInputOrderField, req_id: int) -> int:
        """ReqOrderInsert() - 下单"""
        func = self._get_vtable_func(11, REQ_ORDER_FUNC)
        ret = func(self._api_ptr, ctypes.byref(order_field), req_id)
        return ret

    def req_order_action(self, action_field: CThostFtdcInputOrderActionField, req_id: int) -> int:
        """ReqOrderAction() - 撤单"""
        func = self._get_vtable_func(12, REQ_INT_FUNC)
        ret = func(self._api_ptr, ctypes.byref(action_field), req_id)
        return ret

    def req_qry_trading_account(self, broker_id: str, investor_id: str, req_id: int = 10) -> int:
        """ReqQryTradingAccount() - 查询资金"""
        req = CThostFtdcQryTradingAccountField()
        req.BrokerID = broker_id.encode('utf-8')
        req.InvestorID = investor_id.encode('utf-8')
        func = self._get_vtable_func(15, REQ_INT_FUNC)
        ret = func(self._api_ptr, ctypes.byref(req), req_id)
        return ret

    def req_qry_investor_position(self, broker_id: str, investor_id: str, instrument_id: str = "", req_id: int = 11) -> int:
        """ReqQryInvestorPosition() - 查询持仓"""
        req = CThostFtdcQryInvestorPositionField()
        req.BrokerID = broker_id.encode('utf-8')
        req.InvestorID = investor_id.encode('utf-8')
        if instrument_id:
            req.InstrumentID = instrument_id.encode('utf-8')
        func = self._get_vtable_func(16, REQ_INT_FUNC)
        ret = func(self._api_ptr, ctypes.byref(req), req_id)
        return ret

    def req_qry_instrument(self, instrument_id: str = "", req_id: int = 12) -> int:
        """ReqQryInstrument() - 查询合约"""
        req = CThostFtdcQryInstrumentField()
        if instrument_id:
            req.InstrumentID = instrument_id.encode('utf-8')
        func = self._get_vtable_func(14, REQ_INT_FUNC)
        ret = func(self._api_ptr, ctypes.byref(req), req_id)
        return ret


# ============================================================
# CThostFtdcMdApi - CTP 行情 API 封装
# ============================================================

class CtpMdApi:
    """
    通过 ctypes vtable 调用 CThostFtdcMdApi 的包装类。

    CThostFtdcMdApi vtable 索引 (CTP 6.7.x):
    注意: MdApi 没有 RegisterFensUserInfo，所以比 TraderApi 少一个方法。
    [0] ~CThostFtdcMdApi()
    [1] Release()
    [2] Init()
    [3] Join()
    [4] GetTradingDay()
    [5] RegisterFront(char*)
    [6] RegisterNameServer(char*)
    [7] RegisterSpi(CThostFtdcMdSpi*)       ← 注意: 索引 [7] 不是 [8]!
    [8] ReqUserLogin(...)
    [9] ReqUserLogout(...)
    [10] SubscribeMarketData(char**, int)
    [11] UnSubscribeMarketData(char**, int)
    """

    def __init__(self, flow_path: str = ""):
        _load_dlls()
        self._flow_path = flow_path

        factory = _md_dll['?CreateFtdcMdApi@CThostFtdcMdApi@@SAPEAV1@PEBD_N1_N@Z']
        factory.restype = ctypes.c_void_p
        factory.argtypes = [ctypes.c_char_p, ctypes.c_bool, ctypes.c_bool, ctypes.c_bool]

        self._api_ptr = factory(flow_path.encode('utf-8') if flow_path else b"", False, False, False)
        if not self._api_ptr or self._api_ptr < 0x10000:
            raise RuntimeError(f"Failed to create MdApi, ptr={self._api_ptr}")

        vtable_data = ctypes.string_at(self._api_ptr, 8)
        self._vtable = struct.unpack('<Q', vtable_data)[0]
        self._vtable_funcs = (ctypes.c_void_p * 50).from_address(self._vtable)

        self._spi_cb: Optional[MdSpiCb] = None

        logger.debug(f"[CTP] MdApi created at {self._api_ptr:#x}, vtable at {self._vtable:#x}")

    @property
    def api_ptr(self) -> int:
        return self._api_ptr

    def _get_vtable_func(self, idx: int, ftype):
        ptr = self._vtable_funcs[idx]
        if not ptr:
            raise RuntimeError(f"vtable[{idx}] is NULL")
        return ftype(ptr)

    def release(self):
        func = self._get_vtable_func(1, VOID_FUNC)
        func(self._api_ptr)

    def init(self):
        func = self._get_vtable_func(2, VOID_FUNC)
        func(self._api_ptr)
        logger.info("[CTP] MdApi Init() called")

    def join(self) -> int:
        func = self._get_vtable_func(3, INT_FUNC)
        return func(self._api_ptr)

    def register_front(self, address: str):
        if not address.startswith("tcp://"):
            address = "tcp://" + address
        func = self._get_vtable_func(5, REG_FRONT_FUNC)
        func(self._api_ptr, address.encode('utf-8'))
        logger.info(f"[CTP] MD Registered front: {address}")

    def register_spi(self, spi: MdSpiCb):
        self._spi_cb = spi
        func = self._get_vtable_func(7, REG_SPI_FUNC)
        func(self._api_ptr, ctypes.c_void_p(spi.ptr))
        logger.debug("[CTP] MD SPI registered")

    def req_user_login(self, broker_id: str, user_id: str, password: str, req_id: int = 1) -> int:
        req = CThostFtdcReqUserLoginField()
        req.BrokerID = broker_id.encode('utf-8')
        req.UserID = user_id.encode('utf-8')
        req.Password = password.encode('utf-8')
        func = self._get_vtable_func(8, REQ_INT_FUNC)
        ret = func(self._api_ptr, ctypes.byref(req), req_id)
        return ret

    def subscribe_market_data(self, instrument_id: str) -> int:
        """SubscribeMarketData() - 订阅行情"""
        SUB_MD_FUNC = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_char_p), ctypes.c_int)
        func = self._get_vtable_func(10, SUB_MD_FUNC)
        id_bytes = instrument_id.encode('utf-8')
        id_array = (ctypes.c_char_p * 1)(id_bytes)
        ret = func(self._api_ptr, id_array, 1)
        return ret


# ============================================================
# 便利函数: 检查 CTP DLL 是否可用
# ============================================================

def is_ctp_available() -> bool:
    """检查 CTP DLL 是否可加载"""
    try:
        _load_dlls()
        return True
    except Exception as e:
        logger.warning(f"CTP DLL not available: {e}")
        return False


def get_ctp_version() -> str:
    """获取 CTP API 版本"""
    try:
        dll, _ = _load_dlls()
        func = dll['?GetApiVersion@CThostFtdcTraderApi@@SAPEBDXZ']
        func.restype = ctypes.c_char_p
        return func().decode()
    except Exception as e:
        return f"unknown ({e})"
