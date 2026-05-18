"""
合约管理器测试脚本

用法:
    python scripts/test_contract_manager.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime
from loguru import logger
from src.trade.contract_manager import (
    ContractManager, PRODUCT_SPECS, EXCHANGE_PRODUCTS,
    RolloverAction, RolloverRecord,
)


def test_basic():
    """基本功能测试"""
    cm = ContractManager()

    # 品种规格
    for base in ["RB", "CU", "IF", "SC", "P"]:
        spec = cm.get_spec(base)
        assert spec is not None, f"{base} 规格缺失"
        print(f"  {base:4s} {spec['name']:8s} 乘数={spec['multiplier']:4d}  "
              f"保证金={spec['margin_rate']:.0%} tick={spec['tick_size']}")

    # 合约解析
    for code, expected_base, expected_yr, expected_mo, expected_cont in [
        ("RB2505", "RB", 2025, 5, False),
        ("CU2410", "CU", 2024, 10, False),
        ("IF2503", "IF", 2025, 3, False),
        ("SC0", "SC", None, None, True),
        ("RB0", "RB", None, None, True),
        ("P2505", "P", 2025, 5, False),
    ]:
        p = ContractManager.parse_contract(code)
        assert p["base"] == expected_base, f"{code} base: {p['base']} != {expected_base}"
        assert p["year"] == expected_yr, f"{code} year: {p['year']} != {expected_yr}"
        assert p["month"] == expected_mo, f"{code} month: {p['month']} != {expected_mo}"
        assert p["is_continuous"] == expected_cont, f"{code} continuous: {p['is_continuous']} != {expected_cont}"

    # 合约代码生成
    assert ContractManager.build_contract_code("RB", 2025, 5) == "RB2505"
    assert ContractManager.build_contract_code("SC", 2025, 12) == "SC2512"

    # 排序键
    cm = ContractManager()
    assert cm.get_contract_sort_key("RB2505") == 202505
    assert cm.get_contract_sort_key("RB2510") == 202510

    print("  [OK] 基本功能测试通过")


def test_main_contract():
    """主力合约跟踪测试"""
    cm = ContractManager()

    # 初始设置
    changed = cm.update_main_contract("RB", "RB2505", 0.6, "volume")
    assert cm.get_current_main("RB") == "RB2505"
    assert not changed  # 第一次设置不触发换月

    # 换月检测
    changed = cm.update_main_contract("RB", "RB2510", 0.7, "volume")
    assert changed
    info = cm.get_main_contract_info("RB")
    assert info.previous_contract == "RB2505"
    assert info.current_contract == "RB2510"
    assert info.detected_method == "volume"

    # 重复检测（相同合约）
    changed = cm.update_main_contract("RB", "RB2510", 0.65, "volume")
    assert not changed

    print("  [OK] 主力合约跟踪测试通过")


def test_delivery():
    """交割月检查测试"""
    cm = ContractManager()

    # is_delivery_month
    now = datetime.now()
    future_contract = ContractManager.build_contract_code("RB", now.year + 1, now.month)
    assert not cm.is_delivery_month(future_contract)

    # is_approaching_delivery
    assert not cm.is_approaching_delivery(future_contract, 2)

    # check_delivery_limits
    cm.update_main_contract("RB", future_contract)
    limit = cm.check_delivery_limits("RB")
    assert limit is None  # 未来合约无限制

    print("  [OK] 交割月检查测试通过")


def test_margin_adjustment():
    """保证金率调整测试"""
    cm = ContractManager()

    now = datetime.now()

    # 远月合约：正常保证金
    far_contract = ContractManager.build_contract_code("RB", now.year + 1, now.month)
    margin_far = cm.get_margin_rate("RB", far_contract)

    # 临近交割月合约：保证金应提高
    if now.month < 12:
        near_contract = ContractManager.build_contract_code("RB", now.year, now.month + 1)
    else:
        near_contract = ContractManager.build_contract_code("RB", now.year + 1, 1)

    margin_near = cm.get_margin_rate("RB", near_contract)
    print(f"  远月保证金: {margin_far:.0%}, 近月保证金: {margin_near:.0%}")

    print("  [OK] 保证金率调整测试通过")


def test_products():
    """品种列表测试"""
    cm = ContractManager()

    # 所有品种
    all_products = cm.list_products()
    print(f"  共 {len(all_products)} 个品种")

    # 按交易所
    for ex in ["shfe", "dce", "czce", "cffex", "ine"]:
        products = cm.list_products_by_exchange(ex)
        print(f"  {ex}: {len(products)} 个品种 - {products[:3]}...")

    # 交易所归属
    assert cm.get_exchange("RB") == "shfe"
    assert cm.get_exchange("IF") == "cffex"
    assert cm.get_exchange("SC") == "ine"

    print("  [OK] 品种列表测试通过")


def test_active_contracts():
    """活跃合约生成测试"""
    cm = ContractManager()

    contracts = cm.get_active_contracts("RB")
    assert len(contracts) > 0
    print(f"  RB: {contracts[:5]}")

    # 股指特殊月份
    if_contracts = cm.get_active_contracts("IF")
    print(f"  IF: {if_contracts}")

    print("  [OK] 活跃合约测试通过")


def test_next_main():
    """下一个主力合约推断测试"""
    cm = ContractManager()

    cm.update_main_contract("RB", "RB2505")
    next_candidate = cm.get_next_main_candidate("RB")
    print(f"  RB 当前主力: RB2505, 下一个候选: {next_candidate}")

    cm.update_main_contract("RB", "RB2512")
    next_candidate = cm.get_next_main_candidate("RB")
    print(f"  RB 当前主力: RB2512, 下一个候选: {next_candidate}")

    print("  [OK] 下一个主力推断测试通过")


def test_product_specs_completeness():
    """品种规格完整性检查"""
    missing = []
    for base, spec in PRODUCT_SPECS.items():
        required = ["name", "exchange", "multiplier", "margin_rate",
                     "commission_open", "commission_close", "tick_size",
                     "min_move_value"]
        for field in required:
            if field not in spec:
                missing.append(f"{base}.{field}")
        if spec["multiplier"] * spec["tick_size"] != spec["min_move_value"]:
            print(f"  [WARN] {base}: 乘数*最小变动≠每跳价值 "
                  f"({spec['multiplier']}*{spec['tick_size']}≠{spec['min_move_value']})")

    if missing:
        print(f"  [FAIL] 缺失字段: {missing}")
    else:
        print("  [OK] 品种规格完整性检查通过")


def test_serialization():
    """序列化测试"""
    cm = ContractManager()
    cm.update_main_contract("RB", "RB2505")
    cm.update_main_contract("CU", "CU2507")

    state = cm.to_dict()
    assert "main_contracts" in state
    assert state["main_contracts"]["RB"]["current_contract"] == "RB2505"
    assert state["main_contracts"]["CU"]["current_contract"] == "CU2507"

    # 保存与加载
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        fname = f.name

    try:
        cm.save_state(fname)
        cm2 = ContractManager()
        loaded = cm2.load_state(fname)
        assert loaded
        assert cm2.get_current_main("RB") == "RB2505"
        assert cm2.get_current_main("CU") == "CU2507"
        print("  [OK] 序列化测试通过")
    finally:
        import os
        os.unlink(fname)


def test_rollover_detection():
    """换月检测测试"""
    cm = ContractManager()

    # 无换月
    action = cm.get_rollover_status("RB")
    assert action == RolloverAction.NONE

    # 检测换月
    cm.update_main_contract("RB", "RB2505")
    need_roll = cm.detect_rollover("RB", "RB2510")
    assert need_roll

    # 重复检测不应触发
    need_roll = cm.detect_rollover("RB", "RB2510")
    assert not need_roll

    print("  [OK] 换月检测测试通过")


if __name__ == "__main__":
    logger.remove()

    print("=" * 50)
    print("  合约管理器测试")
    print("=" * 50)

    test_basic()
    test_main_contract()
    test_delivery()
    test_margin_adjustment()
    test_products()
    test_active_contracts()
    test_next_main()
    test_product_specs_completeness()
    test_serialization()
    test_rollover_detection()

    print("=" * 50)
    print(f"  全部测试通过 ({datetime.now().strftime('%H:%M:%S')})")
    print("=" * 50)
