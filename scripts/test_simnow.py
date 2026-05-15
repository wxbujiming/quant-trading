"""
SimNow 期货接口对接测试
运行方式: python scripts/test_simnow.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.logger import setup_logger
from src.trade.ctp_gateway import CtpGateway
from src.trade.order_manager import OrderManager
from src.trade.position_manager import PositionManager
from src.trade.risk_manager import RiskManager


def main():
    """测试 SimNow 对接"""
    print("=" * 60)
    print("   SimNow 期货接口对接测试")
    print("=" * 60)

    # 配置 SimNow 信息
    setting = {
        "broker_id": "9999",
        "user_id": "263533",
        "password": "4@W2NkSA*&6w1##8",
        "app_id": "simnow_client_test",
        "auth_code": "0000000000000000",
        "environment": "simnow",      # simnow / simnow_7x24
    }

    # 1. 创建网关
    print("\n[1/5] 初始化CTP网关...")
    gateway = CtpGateway("SimNow", setting)

    # 2. 连接
    print("\n[2/5] 连接SimNow...")
    if not gateway.connect():
        print("!! 连接失败!")
        return
    print("OK 连接成功 (仿真模式)")

    # 3. 创建风控系统
    print("\n[3/5] 初始化风控系统...")
    risk = RiskManager(gateway, initial_cash=1000000.0)
    risk.print_risk_status()

    # 4. 测试下单和成交
    print("\n[4/5] 模拟交易测试...")

    # 买入开仓 2手螺纹钢
    order_id = risk.buy("rb2410", price=3500.0, volume=2, exchange="SHFE")
    if order_id:
        print(f"OK 开仓单已提交: {order_id}")
        # 模拟成交
        gateway.simulate_trade(order_id, price=3505.0, volume=2)
        print("OK 开仓已成交")

    # 再买入3手
    order_id2 = risk.buy("rb2410", price=3510.0, volume=3, exchange="SHFE")
    if order_id2:
        print(f"OK 开仓单已提交: {order_id2}")
        gateway.simulate_trade(order_id2, price=3512.0, volume=3)
        print("OK 开仓已成交")

    # 买入1手螺纹钢 (触发持仓风控测试)
    print("\n风控测试: 尝试买入超过限制...")
    order_id3 = risk.buy("rb2410", price=3520.0, volume=100, exchange="SHFE")
    if order_id3:
        print("OK 下单成功 (未触发风控)")
    else:
        print("OK 风控拦截成功")

    # 5. 打印结果
    print("\n[5/5] 打印交易结果...")
    print("-" * 60)

    risk.position_manager.print_summary()
    risk.order_manager.print_summary()

    # 查询订单统计
    stats = risk.order_manager.get_order_statistics()
    print(f"\n订单统计:")
    print(f"  总订单数: {stats['total']}")
    print(f"  已成交: {stats['traded']}")
    print(f"  成交率: {stats['trade_rate']:.1f}%")

    # 关闭连接
    print("\n" + "=" * 60)
    gateway.close()
    print("测试完成!")


if __name__ == "__main__":
    setup_logger("DEBUG", "logs/simnow_test.log")
    main()

