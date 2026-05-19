"""
SimNow 真实接口连接测试
通过 ctypes CTP API 连接 SimNow 仿真交易环境

用法:
  python scripts/connect_simnow.py

凭据加载顺序:
  1. 环境变量 SIMNOW_USER_ID / SIMNOW_PASSWORD
  2. config/secrets.yaml (ctp 段)
  3. 默认值 263533
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import os
import time
import threading
from loguru import logger

# 关闭 loguru 默认 handler
logger.remove()
logger.add(sys.stderr, level="INFO")

from src.trade.ctp_gateway import CtpGateway
from src.trade.gateway import (
    OrderData, OrderDirection, OrderType, OrderStatus,
)
from src.core.config import Config


def load_credentials() -> dict:
    """按优先级加载凭据: 环境变量 > secrets.yaml > 默认值"""
    config = Config.load()

    user_id = os.getenv("SIMNOW_USER_ID") or config.live.user_id or "263533"
    password = os.getenv("SIMNOW_PASSWORD") or config.live.password or ""

    return {
        "real_mode": True,
        "broker_id": config.live.broker_id or "9999",
        "user_id": user_id,
        "password": password,
        "app_id": config.live.app_id or "simnow_client_test",
        "auth_code": config.live.auth_code or "0000000000000000",
        "environment": "simnow_7x24",
    }


def main():
    setting = load_credentials()

    if not setting["password"]:
        print("错误: 未设置 CTP 密码")
        print("  方式1: 编辑 config/secrets.yaml 填入 ctp.password")
        print("  方式2: set SIMNOW_PASSWORD=your_password")
        sys.exit(1)

    print("=" * 60)
    print(f"  SimNow 真实接口连接测试")
    print(f"  User: {setting['user_id']} @ Broker: 9999")
    print("=" * 60)

    # 结果记录
    results = {}
    connected_event = threading.Event()
    login_event = threading.Event()
    settlement_event = threading.Event()
    account_event = threading.Event()
    position_event = threading.Event()

    gateway = CtpGateway("SimNow", setting)

    # 接管回调记录事件
    original_on_connected = gateway._on_td_connected
    def on_td_connected_wrapper():
        original_on_connected()
        results["td_connected"] = True
        connected_event.set()
    gateway._on_td_connected = on_td_connected_wrapper

    # 包装 on_order 来记录订单回报
    gateway.on_order = lambda order: print(
        f"  [订单回报] {order.symbol} {order.direction} "
        f"{order.volume}手 @ {order.price} → {order.status}"
    )
    gateway.on_trade = lambda trade: print(
        f"  [成交回报] {trade.symbol} {trade.direction} "
        f"{trade.volume}手 @ {trade.price}"
    )
    gateway.on_tick = lambda tick: None
    gateway.on_error = lambda msg: print(f"  [错误] {msg}")

    # 登录成功后再包装一次
    original_on_login = gateway._on_real_login
    def on_login_wrapper(login_info):
        original_on_login(login_info)
        results["login_info"] = login_info
        login_event.set()
    gateway._on_real_login = on_login_wrapper

    original_on_settlement = gateway._on_settlement_confirmed
    def on_settlement_wrapper():
        original_on_settlement()
        results["settlement_confirmed"] = True
        settlement_event.set()
    gateway._on_settlement_confirmed = on_settlement_wrapper

    # 查询回调
    def _on_account(account):
        results["_last_account"] = account
        account_event.set()
    gateway.on_account = _on_account

    def _on_position(pos):
        results["position_result"] = pos
        position_event.set()
    gateway.on_position = _on_position

    print("\n[1/5] 连接 SimNow (真实模式)...")
    result = gateway.connect()
    print(f"  connect() 返回: {result}")

    if not result:
        print("  连接初始化失败!")
        gateway.close()
        sys.exit(1)

    # 等待 OnFrontConnected
    print("\n[2/5] 等待交易前置连接...")
    if connected_event.wait(timeout=10):
        print("  [OK] 交易前置已连接")
    else:
        print("  [FAIL] 交易前置连接超时 (10s)")

    # 等待登录响应
    print("\n[3/5] 等待登录响应...")
    if login_event.wait(timeout=10):
        info = results.get("login_info")
        print(f"  [OK] 登录成功: 交易日={info.trading_day}, "
              f"FrontID={info.front_id}, SessionID={info.session_id}")
    else:
        print("  [FAIL] 登录超时 (10s)")

    # 等待结算确认
    print("\n[4/5] 等待结算确认...")
    if settlement_event.wait(timeout=10):
        print("  [OK] 结算确认完成")
    else:
        print("  [FAIL] 结算确认超时 (10s)")

    # 查询账户和持仓
    print("\n[5/5] 查询账户与持仓...")
    account_event.clear()
    position_event.clear()

    gateway.query_account()
    gateway.query_position()

    if account_event.wait(timeout=5):
        acc = results.get("_last_account", None)
        if acc:
            print(f"  [OK] 账户余额: {acc.balance:.2f}")
            print(f"       可用资金: {acc.available:.2f}")
            print(f"       持仓保证金: {acc.margin:.2f}")
            print(f"       浮动盈亏: {acc.pnl:.2f}")
    else:
        print("  [--] 账户查询超时 (可忽略)")

    if position_event.wait(timeout=5):
        print(f"  [OK] 持仓数据已收到")
    else:
        print("  [--] 持仓查询超时 (可忽略)")

    # 尝试订阅行情
    print("\n  --- 行情订阅测试 ---")
    gateway.subscribe(["rb2510"])
    print("  已发送订阅请求: rb2510")
    time.sleep(1)

    # 关闭
    print("\n  --- 关闭连接 ---")
    gateway.close()
    print("  连接已关闭")

    # 结果汇总
    print("\n" + "=" * 60)
    all_ok = (
        results.get("td_connected") and
        results.get("login_info") and
        results.get("settlement_confirmed")
    )
    if all_ok:
        print("  [OK] SimNow 真实模式联调成功")
    else:
        print("  [FAIL] 联调失败: 部分步骤未完成")
        for k, v in [
                ("TD Connected", "OK" if results.get("td_connected") else "--"),
            ("Login", "OK" if results.get("login_info") else "--"),
            ("Settlement", "OK" if results.get("settlement_confirmed") else "--"),
        ]:
            print(f"     {k}: {'OK' if v else '--'}")
    print("=" * 60)

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
