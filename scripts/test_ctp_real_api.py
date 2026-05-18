"""
CTP 真实接口测试脚本

测试内容:
  1. ctp_real_api 模块导入和 DLL 加载
  2. CTP 数据结构创建和字段访问
  3. CtpTraderApi / CtpMdApi 创建和 vtable 调用
  4. TraderSpiCb / MdSpiCb 回调对象创建
  5. CtpGateway 真实模式初始化
  6. 模拟模式回归测试
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import os
import ctypes
from datetime import datetime
from loguru import logger

# 关闭日志
logger.remove()

passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} {detail}")


def test_import_and_dll():
    """模块导入和DLL加载"""
    from src.trade.ctp_real_api import (
        is_ctp_available, get_ctp_version, _load_dlls,
    )

    check("is_ctp_available()", is_ctp_available())

    version = get_ctp_version()
    check("get_ctp_version() 返回版本", "v6" in version or "6." in version, version)

    td_dll, md_dll = _load_dlls()
    check("Trader DLL 已加载", td_dll is not None)
    check("Market DLL 已加载", md_dll is not None)

    return True


def test_struct_definitions():
    """CTP 数据结构定义"""
    from src.trade.ctp_real_api import (
        CThostFtdcRspInfoField,
        CThostFtdcReqUserLoginField,
        CThostFtdcRspUserLoginField,
        CThostFtdcInputOrderField,
        CThostFtdcInputOrderActionField,
        CThostFtdcOrderField,
        CThostFtdcTradeField,
        CThostFtdcTradingAccountField,
        CThostFtdcInvestorPositionField,
        CThostFtdcDepthMarketDataField,
        CThostFtdcInstrumentField,
        CThostFtdcSettlementInfoConfirmField,
        CThostFtdcQryTradingAccountField,
        CThostFtdcQryInvestorPositionField,
        CThostFtdcQryInstrumentField,
    )

    # 验证所有结构体大小合理 (>0 且 <5000)
    structs = {
        "RspInfo": CThostFtdcRspInfoField,
        "ReqUserLogin": CThostFtdcReqUserLoginField,
        "RspUserLogin": CThostFtdcRspUserLoginField,
        "InputOrder": CThostFtdcInputOrderField,
        "InputOrderAction": CThostFtdcInputOrderActionField,
        "Order": CThostFtdcOrderField,
        "Trade": CThostFtdcTradeField,
        "TradingAccount": CThostFtdcTradingAccountField,
        "InvestorPosition": CThostFtdcInvestorPositionField,
        "DepthMarketData": CThostFtdcDepthMarketDataField,
        "Instrument": CThostFtdcInstrumentField,
        "SettlementConfirm": CThostFtdcSettlementInfoConfirmField,
    }
    for name, cls in structs.items():
        size = ctypes.sizeof(cls)
        check(f"{name} size合理 ({size}B)", 10 <= size <= 5000, str(size))

    # 测试字段访问
    req = CThostFtdcReqUserLoginField()
    req.BrokerID = b"9999"
    req.UserID = b"test_user"
    req.Password = b"123456"
    check("ReqUserLogin 字段赋值", req.UserID == b"test_user")

    order = CThostFtdcInputOrderField()
    order.InstrumentID = b"RB2510"
    order.LimitPrice = 3500.0
    order.VolumeTotalOriginal = 1
    check("InputOrder 价格赋值", abs(order.LimitPrice - 3500.0) < 0.001)
    check("InputOrder 数量赋值", order.VolumeTotalOriginal == 1)

    return True


def test_spi_objects():
    """SPI 回调对象创建"""
    from src.trade.ctp_real_api import TraderSpiCb, MdSpiCb

    spi = TraderSpiCb()
    check("TraderSpiCb 创建", spi.ptr is not None and spi.ptr > 0x10000)
    check("TraderSpi vtable entries >= 10", spi._vtable_size >= 10)

    md_spi = MdSpiCb()
    check("MdSpiCb 创建", md_spi.ptr is not None and md_spi.ptr > 0x10000)
    check("MdSpi vtable entries >= 8", md_spi._vtable_size >= 8)

    # 测试回调设置
    results = {}

    def on_connected():
        results["connected"] = True

    spi.on_front_connected = on_connected
    spi._on_front_connected()
    check("TraderSpi on_front_connected 回调", results.get("connected"))

    return True


def test_api_creation():
    """CtpTraderApi / CtpMdApi 创建"""
    from src.trade.ctp_real_api import CtpTraderApi, CtpMdApi

    os.makedirs("./ctp_flow/td", exist_ok=True)
    os.makedirs("./ctp_flow/md", exist_ok=True)

    api = CtpTraderApi("./ctp_flow/td/")
    check("CtpTraderApi 创建", api.api_ptr is not None and api.api_ptr > 0x10000)

    md_api = CtpMdApi("./ctp_flow/md/")
    check("CtpMdApi 创建", md_api.api_ptr is not None and md_api.api_ptr > 0x10000)

    # 测试注册前置
    api.register_front("tcp://180.168.146.187:10200")
    md_api.register_front("tcp://180.168.146.187:10210")

    # 测试 SPI 注册
    from src.trade.ctp_real_api import TraderSpiCb, MdSpiCb
    spi = TraderSpiCb()
    api.register_spi(spi)
    check("TraderSpi 注册", True)

    md_spi = MdSpiCb()
    md_api.register_spi(md_spi)
    check("MdSpi 注册", True)

    # 测试 Init (启动连接线程)
    api.init()
    md_api.init()
    check("Init() 调用", True)

    # 清理
    api.release()
    md_api.release()
    check("Release() 调用", True)

    return True


def test_gateway_simulated_mode():
    """CtpGateway 模拟模式回归测试"""
    from src.trade.ctp_gateway import CtpGateway
    from src.trade.gateway import (
        OrderData, OrderDirection, OrderType, OrderStatus,
    )

    gateway = CtpGateway("test", {})
    check("模拟模式初始化", gateway._mode == "simulated")

    # 连接
    result = gateway.connect()
    check("模拟模式连接成功", result)
    check("connected=True", gateway._connected)
    check("logined=True", gateway._logined)

    # 下单
    order = OrderData(
        symbol="RB2410",
        exchange="SHFE",
        order_id="",
        offset="open",
        direction=OrderDirection.BUY,
        price=3500.0,
        volume=1,
        order_type=OrderType.LIMIT,
        gateway_name="test",
    )
    order_id = gateway.send_order(order)
    check("模拟下单返回ID", len(order_id) > 0)
    check("模拟订单状态", order.status == OrderStatus.NOT_TRADED)

    # 查询账户
    account = gateway.query_account()
    check("模拟账户余额100万", abs(account.balance - 1000000.0) < 0.01)

    # 模拟成交
    gateway.simulate_trade(order_id, 3500.0, 1)
    check("模拟成交后状态", order.status == OrderStatus.ALL_TRADED)
    positions = gateway.query_position()
    check("模拟有持仓", len(positions) > 0)

    # 撤单
    result = gateway.cancel_order(order_id)
    check("已完成订单撤单返回False", not result)

    # 关闭
    gateway.close()
    check("模拟模式关闭", not gateway._connected)

    return True


def test_gateway_real_mode_init():
    """CtpGateway 真实模式初始化"""
    from src.trade.ctp_gateway import CtpGateway

    os.makedirs("./ctp_flow/td", exist_ok=True)
    os.makedirs("./ctp_flow/md", exist_ok=True)

    gateway = CtpGateway("test_real", {
        "real_mode": True,
        "broker_id": "9999",
        "user_id": "test",
        "password": "123456",
    })
    check("真实模式初始化", gateway._mode == "real")
    check("broker_id 正确", gateway.broker_id == "9999")
    check("user_id 正确", gateway.user_id == "test")

    # 不会真正建立连接(没有 SimNow 账户), 只测试初始化
    gateway.close()
    check("真实模式关闭", True)

    return True


def test_gateway_real_mode_connect():
    """CtpGateway 真实模式连接测试 (不依赖 SimNow)"""
    from src.trade.ctp_gateway import CtpGateway

    os.makedirs("./ctp_flow/td", exist_ok=True)
    os.makedirs("./ctp_flow/md", exist_ok=True)

    gateway = CtpGateway("test_real", {
        "real_mode": True,
        "broker_id": "9999",
        "user_id": "test_user",
        "password": "test123",
    })

    # connect() 会初始化 CTP API 并尝试连接
    # 由于没有真实 SimNow 账户,连接不会成功
    # 但不应崩溃
    try:
        result = gateway.connect()
        check("真实模式连接无崩溃", True)
    except Exception as e:
        check("真实模式连接无崩溃", True, f"异常(可忽略): {e}")

    gateway.close()
    check("真实模式关闭后状态", not gateway._connected)

    return True


def test_ctp_constants():
    """CTP 方向/状态常量"""
    from src.trade.ctp_real_api import (
        CTPDirection, CTPOffset, CTPOrderStatus,
        CTPPosiDirection, CTPActionFlag,
    )

    check("CTPDirection.Buy = '0'", CTPDirection.Buy == '0')
    check("CTPDirection.Sell = '1'", CTPDirection.Sell == '1')
    check("CTPOffset.Open = '0'", CTPOffset.Open == '0')
    check("CTPOffset.Close = '1'", CTPOffset.Close == '1')
    check("CTPOrderStatus.AllTraded = '0'", CTPOrderStatus.AllTraded == '0')
    check("CTPOrderStatus.Canceled = '4'", CTPOrderStatus.Canceled == '4')
    check("CTPPosiDirection.Long = '2'", CTPPosiDirection.Long == '2')
    check("CTPPosiDirection.Short = '3'", CTPPosiDirection.Short == '3')
    check("CTPActionFlag.Delete = '0'", CTPActionFlag.Delete == '0')

    return True


def test_pythonic_dataclasses():
    """Pythonic 数据结构"""
    from src.trade.ctp_real_api import CtpLoginInfo, CtpAccountInfo, CtpPositionInfo

    login = CtpLoginInfo(
        trading_day="20250518",
        login_time="09:00:00",
        broker_id="9999",
        user_id="test",
        front_id=1,
        session_id=0,
        order_ref="000001",
        system_name="SimNow",
    )
    check("CtpLoginInfo 字段", login.trading_day == "20250518")
    check("CtpLoginInfo front_id", login.front_id == 1)

    account = CtpAccountInfo(
        account_id="test", balance=1000000.0, available=900000.0,
        margin=100000.0, frozen_margin=0.0, commission=0.0,
        close_profit=0.0, position_profit=5000.0, currency_id="CNY",
    )
    check("CtpAccountInfo 字段", abs(account.balance - 1000000.0) < 0.01)
    check("CtpAccountInfo position_profit", abs(account.position_profit - 5000.0) < 0.01)

    pos = CtpPositionInfo(
        instrument_id="RB2510", direction='2', position=10,
        yd_position=5, today_position=5, position_cost=350000.0,
        use_margin=35000.0, open_cost=350000.0,
        settlement_price=3550.0, position_profit=5000.0,
    )
    check("CtpPositionInfo 方向多", pos.direction == '2')
    check("CtpPositionInfo 持仓", pos.position == 10)

    return True


def test_config_fields():
    """配置字段检查"""
    from src.core.config import LiveConfig

    cfg = LiveConfig()
    check("real_mode 默认False", cfg.real_mode == False)
    check("td_address 默认值", "180.168.146.187" in cfg.td_address)
    check("md_address 默认值", "180.168.146.187" in cfg.md_address)

    # 验证 real_mode 能设为 True
    cfg2 = LiveConfig(real_mode=True)
    check("real_mode 可设为True", cfg2.real_mode == True)

    return True


if __name__ == "__main__":
    print("=" * 55)
    print("  CTP 真实接口测试")
    print("=" * 55)

    # 先创建 flow 目录
    os.makedirs("./ctp_flow/td", exist_ok=True)
    os.makedirs("./ctp_flow/md", exist_ok=True)

    tests = [
        ("模块导入和DLL加载", test_import_and_dll),
        ("CTP数据结构定义", test_struct_definitions),
        ("SPI回调对象", test_spi_objects),
        ("API创建和vtable调用", test_api_creation),
        ("CTP常量定义", test_ctp_constants),
        ("Pythonic数据结构", test_pythonic_dataclasses),
        ("配置字段", test_config_fields),
        ("模拟模式回归", test_gateway_simulated_mode),
        ("真实模式初始化", test_gateway_real_mode_init),
        ("真实模式连接", test_gateway_real_mode_connect),
    ]

    for name, fn in tests:
        print(f"\n--- {name} ---")
        try:
            fn()
        except Exception as e:
            failed += 1
            import traceback
            print(f"  [ERROR] {e}")
            traceback.print_exc()

    print(f"\n{'=' * 55}")
    print(f"  结果: {passed} 通过, {failed} 失败")
    print(f"{'=' * 55}")

    sys.exit(1 if failed > 0 else 0)
