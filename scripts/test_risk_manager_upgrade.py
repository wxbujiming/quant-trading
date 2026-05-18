"""
风险系统升级测试脚本

测试内容:
  1. MarginRule 保证金计算正确性
  2. RiskRatioRule 阈值触发逻辑
  3. PriceLimitRule 涨跌停拒绝
  4. LiquidationWarningRule 强平预警
  5. 完整的 RiskManager 升级后流程
  6. 与 LiveEngine 集成
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime
from loguru import logger

from src.trade.gateway import AccountData
from src.trade.contract_manager import ContractManager
from src.trade.risk_manager import (
    RiskManager, MarginRule, RiskRatioRule,
    PriceLimitRule, LiquidationWarningRule,
)
from src.trade.ctp_gateway import CtpGateway

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


def test_margin_rule():
    """保证金计算测试"""
    cm = ContractManager()
    gateway = CtpGateway("test", {})
    rm = RiskManager(gateway, initial_cash=1000000, contract_manager=cm)

    # RB: 乘数=10, 保证金率=10%
    margin = rm.calc_margin("RB2410", 3500, 1)
    expected = 3500 * 10 * 0.10
    check("RB margin 1手", abs(margin - expected) < 0.01, f"{margin} != {expected}")

    # CU: 乘数=5, 保证金率=12%
    margin = rm.calc_margin("CU2410", 70000, 2)
    expected = 70000 * 5 * 0.12 * 2
    check("CU margin 2手", abs(margin - expected) < 0.01, f"{margin} != {expected}")

    # IF: 乘数=300, 保证金率=12%
    margin = rm.calc_margin("IF2412", 3500, 1)
    expected = 3500 * 300 * 0.12
    check("IF margin 1手", abs(margin - expected) < 0.01, f"{margin} != {expected}")

    # 总保证金（无持仓）
    total = rm.calc_total_margin()
    check("无持仓总保证金为0", total == 0.0)

    return True


def test_margin_rule_insufficient():
    """保证金不足检查"""
    cm = ContractManager()
    gateway = CtpGateway("test", {})
    rm = RiskManager(gateway, initial_cash=1000000, contract_manager=cm)

    # 应该能通过（资金足够）
    passed, msg = rm.margin_rule.check("RB2410", 3500, 1, rm.position_manager)
    check("保证金足够时通过", passed, msg)

    # 模拟高保证金占用 + 超大数量, 使总需求超过CtpGateway返回的固定100万
    # RB 3500*10*0.10 = 3500/手, 200手=700000
    rm.margin_rule.set_total_margin(900000)  # 已占用90万
    passed, msg = rm.margin_rule.check("RB2410", 3500, 200, rm.position_manager)  # 需70万=160万>100万
    check("保证金不足时拒绝", not passed, msg)

    return True


def test_risk_ratio_rule():
    """风险度阈值测试"""
    cm = ContractManager()
    gateway = CtpGateway("test", {})
    rm = RiskManager(gateway, initial_cash=1000000, contract_manager=cm)
    rr = rm.risk_ratio_rule

    # 正常区间
    rr.update(500000, 1000000)
    check("风险度50%正常", rr.get_risk_level() == "normal")
    passed, _ = rr.check()
    check("50%可以通过", passed)

    # 警戒线 80%
    rr.update(800000, 1000000)
    check("风险度80%预警", rr.get_risk_level() == "warning")
    passed, _ = rr.check()
    check("80%仍可通过", passed)

    # 危险线 90%
    rr.update(920000, 1000000)
    check("风险度92%危险", rr.get_risk_level() == "danger")
    passed, _ = rr.check()
    check("92%拒绝开仓", not passed)

    # 强平线 100%
    rr.update(1000000, 1000000)
    check("风险度100%强平", rr.get_risk_level() == "liquidation")
    passed, _ = rr.check()
    check("100%拒绝开仓", not passed)

    # 阈值自定义
    rr2 = RiskRatioRule(cm, 1000000, warning_ratio=0.50, danger_ratio=0.70, liquidation_ratio=0.90)
    rr2.update(600000, 1000000)
    check("自定义60%>50%警告", rr2.get_risk_level() == "warning")
    rr2.update(800000, 1000000)
    check("自定义80%>70%危险", rr2.get_risk_level() == "danger")
    rr2.update(950000, 1000000)
    check("自定义95%>90%强平", rr2.get_risk_level() == "liquidation")

    return True


def test_price_limit_rule():
    """涨跌停板测试"""
    cm = ContractManager()
    gateway = CtpGateway("test", {})
    rm = RiskManager(gateway, initial_cash=1000000, contract_manager=cm)
    pl = rm.price_limit_rule

    # 设置RB涨跌停6%, 前结算3500
    pl.set_limit("RB", 0.06, 0.06)
    pl.set_prev_settle("RB2410", 3500)

    # 涨停价=3710, 跌停价=3290

    # 正常开多
    ok, _ = pl.check("RB2410", 3500, "open_long")
    check("开多正常价通过", ok)

    # 涨停附近开多
    ok, _ = pl.check("RB2410", 3700, "open_long")
    check("开多接近涨停通过", ok)

    # 超过涨停开多
    ok, msg = pl.check("RB2410", 3720, "open_long")
    check("开多超涨停拒绝", not ok, msg)

    # 正常开空
    ok, _ = pl.check("RB2410", 3500, "open_short")
    check("开空正常价通过", ok)

    # 低于跌停开空
    ok, msg = pl.check("RB2410", 3280, "open_short")
    check("开空低于跌停拒绝", not ok, msg)

    # 平多/平空不受影响（使用 close_long/close_short）
    ok, _ = pl.check("RB2410", 3500, "close_long")
    check("平多正常通过", ok)
    ok, _ = pl.check("RB2410", 3500, "close_short")
    check("平空正常通过", ok)

    return True


def test_liquidation_warning():
    """强平预警测试"""
    cm = ContractManager()
    gateway = CtpGateway("test", {})
    rm = RiskManager(gateway, initial_cash=1000000, contract_manager=cm)
    lw = rm.liquidation_warning

    # 正常状态
    rm.risk_ratio_rule.update(500000, 1000000)
    passed, msg = lw.check()
    check("正常无预警", passed and not msg)

    # 危险区间
    rm.risk_ratio_rule.update(920000, 1000000)
    passed, msg = lw.check()
    check("危险区间有预警", "危险" in msg, msg)

    # 强平区间
    rm.risk_ratio_rule.update(1000000, 1000000)
    passed, msg = lw.check()
    check("强平区间触发预警", not passed, msg)
    check("强平提示减仓", "减仓" in msg, msg)

    return True


def test_risk_manager_check_before_order():
    """风控总管理器的下单检查"""
    cm = ContractManager()
    gateway = CtpGateway("test", {})
    rm = RiskManager(gateway, initial_cash=1000000, contract_manager=cm)

    # 初始化结算价
    rm.price_limit_rule.set_limit("RB", 0.06, 0.06)
    rm.price_limit_rule.set_prev_settle("RB2410", 3500)

    # 正常开多
    passed, msg = rm.check_before_order("RB2410", 3500, 1, "open_long")
    check("正常开多风控通过", passed, msg)

    # 超涨停开多
    passed, msg = rm.check_before_order("RB2410", 3720, 1, "open_long")
    check("超涨停开多被拦截", not passed, msg)

    # 超大仓位（保证金不足）
    passed, msg = rm.check_before_order("RB2410", 3500, 10000, "open_long")
    check("超大仓位被拦截", not passed, msg)

    return True


def test_risk_manager_check_positions():
    """风控周期性持仓检查"""
    cm = ContractManager()
    gateway = CtpGateway("test", {})
    rm = RiskManager(gateway, initial_cash=1000000, contract_manager=cm)

    # 正常状态
    alerts = rm.check_positions()
    risk_alerts = [a for a in alerts if a.get("rule") in ("风险度监控", "强平预警")]
    check("正常状态无风险告警", len(risk_alerts) == 0, str(alerts))

    # 直接测试 RiskRatioRule 告警生成（check_positions会覆盖手动设置的值）
    rr = rm.risk_ratio_rule
    rr.update(950000, 1000000)
    direct_alerts = rr.get_alerts()
    check("高风险度直接生成告警", len(direct_alerts) > 0, str(direct_alerts))
    if direct_alerts:
        check("告警级别为danger", direct_alerts[0].get("level") == "danger")

    # 强平线告警
    rr.update(1000000, 1000000)
    liq_alerts = rr.get_alerts()
    check("强平线生成告警", len(liq_alerts) > 0, str(liq_alerts))
    if liq_alerts:
        check("告警级别为critical", liq_alerts[0].get("level") == "critical")

    return True


def test_margin_status():
    """保证金状态查询"""
    cm = ContractManager()
    gateway = CtpGateway("test", {})
    rm = RiskManager(gateway, initial_cash=1000000, contract_manager=cm)

    status = rm.get_margin_status()
    check("状态含total_equity", "total_equity" in status)
    check("状态含total_margin", "total_margin" in status)
    check("状态含available_margin", "available_margin" in status)
    check("状态含risk_ratio", "risk_ratio" in status)
    check("状态含risk_level", "risk_level" in status)
    check("初始状态normal", status["risk_level"] == "normal")

    return True


def test_check_before_order_with_defaults():
    """无 contract_manager 时的兼容性"""
    gateway = CtpGateway("test", {})
    rm = RiskManager(gateway, initial_cash=1000000)  # 没传contract_manager

    passed, msg = rm.check_before_order("RB2410", 3500, 1)
    check("无cm时风控仍可运行", passed, msg)

    return True


def test_integration_with_live_engine():
    """与 LiveEngine 集成测试"""
    import time
    from src.engine.live_engine import LiveEngine
    from src.core.config import LiveConfig
    from src.strategy.futures_strategy import DualMaCrossStrategy

    cfg = LiveConfig(initial_capital=1000000, symbols=["RB2410"])
    gateway = CtpGateway("SimNow", {"environment": "simnow"})
    engine = LiveEngine(gateway, cfg)

    # 验证 contract_manager 已传入 RiskManager
    check("engine.cm已创建", engine.contract_manager is not None)
    check("rm.cm已传入", engine.risk_manager.contract_manager is engine.contract_manager)
    check("保证金规则已启用", engine.risk_manager.margin_rule is not None)
    check("风险度规则已启用", engine.risk_manager.risk_ratio_rule is not None)

    # 快速启动关闭验证
    strategy = DualMaCrossStrategy()
    engine.run(strategy, ["RB2410"])
    time.sleep(3)
    check("引擎正常运行", engine.state.name == "RUNNING")

    # 风险度可以正常计算
    ratio = engine.risk_manager.calc_risk_ratio()
    check(f"风险度可计算: {ratio:.1%}", isinstance(ratio, float))

    engine.stop()
    check("引擎安全停止", True)

    return True


if __name__ == "__main__":
    print("=" * 55)
    print("  风控系统升级测试")
    print("=" * 55)

    tests = [
        ("保证金计算", test_margin_rule),
        ("保证金不足检查", test_margin_rule_insufficient),
        ("风险度阈值", test_risk_ratio_rule),
        ("涨跌停板", test_price_limit_rule),
        ("强平预警", test_liquidation_warning),
        ("风控总管理下单检查", test_risk_manager_check_before_order),
        ("风控周期性持仓检查", test_risk_manager_check_positions),
        ("保证金状态查询", test_margin_status),
        ("无cm时兼容性", test_check_before_order_with_defaults),
        ("LiveEngine集成", test_integration_with_live_engine),
    ]

    for name, fn in tests:
        print(f"\n--- {name} ---")
        try:
            fn()
        except Exception as e:
            failed += 1
            print(f"  [ERROR] {e}")

    print(f"\n{'=' * 55}")
    print(f"  结果: {passed} 通过, {failed} 失败")
    print(f"{'=' * 55}")

    sys.exit(1 if failed > 0 else 0)
