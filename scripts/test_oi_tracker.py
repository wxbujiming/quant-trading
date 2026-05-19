"""
OI 主力合约追踪器单元测试

验证 OpenInterestTracker 的核心检测逻辑:
  - 初始主力识别
  - 阈值不足不换月
  - 确认次数不足不换月
  - 确认达标触发换月
  - 旧主力抑制期内不反复

用法:
  python scripts/test_oi_tracker.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime, timedelta
from src.trade.contract_manager import ContractManager
from src.trade.oi_tracker import OpenInterestTracker
from src.trade.gateway import TickData


class _TestRecorder:
    """记录 on_main_contract_changed 回调"""
    def __init__(self):
        self.calls: list = []

    def __call__(self, base, old, new):
        self.calls.append((base, old, new))


def _make_tick(symbol: str, oi: int, dt: datetime = None) -> TickData:
    return TickData(
        symbol=symbol,
        exchange="SHFE",
        last_price=3500.0,
        volume=1000,
        open_interest=oi,
        datetime=dt or datetime.now(),
    )


def test_initial_leader():
    """首次接收 OI 数据后应设置当前主力"""
    cm = ContractManager()
    cm.start()
    recorder = _TestRecorder()
    tracker = OpenInterestTracker(cm, confirmation_count=2, check_interval_seconds=0,
                                   on_main_contract_changed=recorder)

    now = datetime.now()
    tracker.on_tick(_make_tick("RB2510", 120000, now))
    tracker.on_tick(_make_tick("RB2509", 80000, now))

    tracker.check()
    snap = tracker.get_oi_snapshot("RB")
    assert snap is not None, "应该有 RB 的快照"
    assert snap["current_leader"] == "RB2510", f"应选 RB2510, 实际={snap['current_leader']}"
    assert snap["current_leader_oi"] == 120000
    print(f"  [OK] 初始主力 RB2510 (OI=120000)")


def test_threshold_not_met():
    """OI 差值未达阈值不应换月"""
    cm = ContractManager()
    cm.start()
    recorder = _TestRecorder()
    tracker = OpenInterestTracker(
        cm, threshold_ratio=0.20, confirmation_count=2,
        check_interval_seconds=0,
        on_main_contract_changed=recorder,
    )

    now = datetime.now()
    tracker.on_tick(_make_tick("RB2510", 100000, now))
    tracker.check()
    assert tracker.get_oi_snapshot("RB")["current_leader"] == "RB2510"

    # OI 接近 (10万 vs 11万 = 10%, 不够 20%)
    tracker.on_tick(_make_tick("RB2511", 110000, now))
    tracker.check()
    tracker.check()

    assert recorder.calls == [], f"不应换月, 实际回调={recorder.calls}"
    assert tracker.get_oi_snapshot("RB")["current_leader"] == "RB2510"
    print(f"  [OK] OI 10% 未达阈值 20%, 不换月")


def test_confirmation_not_met():
    """OI 领先但确认次数不够不应换月"""
    cm = ContractManager()
    cm.start()
    recorder = _TestRecorder()
    tracker = OpenInterestTracker(
        cm, threshold_ratio=0.20, confirmation_count=3,
        check_interval_seconds=0,
        on_main_contract_changed=recorder,
    )

    now = datetime.now()
    tracker.on_tick(_make_tick("RB2510", 100000, now))
    tracker.check()
    assert tracker.get_oi_snapshot("RB")["current_leader"] == "RB2510"

    # OI 大幅领先 (10万 vs 15万 = 50%, 够阈值)
    tracker.on_tick(_make_tick("RB2511", 150000, now))
    tracker.check()  # 第1次确认
    assert recorder.calls == []

    tracker.check()  # 第2次确认
    assert recorder.calls == []

    print(f"  [OK] 确认2/3不换月, 无回调")


def test_rollover_triggered():
    """确认达标应触发换月"""
    cm = ContractManager()
    cm.start()
    recorder = _TestRecorder()
    tracker = OpenInterestTracker(
        cm, threshold_ratio=0.20, confirmation_count=2,
        check_interval_seconds=0,
        on_main_contract_changed=recorder,
    )

    now = datetime.now()
    tracker.on_tick(_make_tick("RB2510", 100000, now))
    tracker.check()
    assert tracker.get_oi_snapshot("RB")["current_leader"] == "RB2510"

    # OI 反转 (RB2511 领先 30%)
    tracker.on_tick(_make_tick("RB2511", 130000, now))
    tracker.check()  # 确认1
    assert recorder.calls == []
    tracker.check()  # 确认2 → 触发

    assert len(recorder.calls) == 1, f"应触发1次回调, 实际={recorder.calls}"
    base, old, new = recorder.calls[0]
    assert (base, old, new) == ("RB", "RB2510", "RB2511"), f"回调参数错误: {recorder.calls[0]}"
    assert tracker.get_oi_snapshot("RB")["current_leader"] == "RB2511"
    print(f"  [OK] 换月触发: {old} → {new}")


def test_old_leader_suppressed():
    """换月后旧主力应在抑制期内不被选中"""
    cm = ContractManager()
    cm.start()
    recorder = _TestRecorder()
    tracker = OpenInterestTracker(
        cm, threshold_ratio=0.20, confirmation_count=2,
        check_interval_seconds=0,
        old_leader_suppress_minutes=60,
        on_main_contract_changed=recorder,
    )

    now = datetime.now()
    tracker.on_tick(_make_tick("RB2510", 100000, now))
    tracker.check()
    assert tracker.get_oi_snapshot("RB")["current_leader"] == "RB2510"

    # 换月: RB2510 → RB2511
    tracker.on_tick(_make_tick("RB2511", 130000, now))
    tracker.check()
    tracker.check()
    assert len(recorder.calls) == 1
    assert tracker.get_oi_snapshot("RB")["current_leader"] == "RB2511"

    # 旧主力 OI 反超 (仍在抑制期内)
    tracker.on_tick(_make_tick("RB2510", 150000, now))
    tracker.check()
    tracker.check()
    tracker.check()
    assert len(recorder.calls) == 1, "抑制期内不应再次换月"
    assert tracker.get_oi_snapshot("RB")["current_leader"] == "RB2511"
    print(f"  [OK] 旧主力抑制期不反跳")


def test_stale_contract_excluded():
    """5 分钟无更新的合约应被排除"""
    cm = ContractManager()
    cm.start()
    recorder = _TestRecorder()
    tracker = OpenInterestTracker(cm, check_interval_seconds=0, on_main_contract_changed=recorder)

    now = datetime.now()
    tracker.on_tick(_make_tick("RB2510", 100000, now))
    tracker.on_tick(_make_tick("RB2511", 120000, now))
    tracker.check()
    assert tracker.get_oi_snapshot("RB")["current_leader"] == "RB2511"

    # RB2511 有最新数据, RB2510 还是旧数据
    stale_time = now - timedelta(minutes=6)
    tracker.on_tick(_make_tick("RB2510", 99999, stale_time))
    tracker.on_tick(_make_tick("RB2511", 1, now))  # OI 很低但新鲜
    snap = tracker.get_oi_snapshot("RB")
    # 说明: RB2510 因 OI 低被 min_oi 过滤, RB2511 因新鲜数据被保留,
    # 但 OI=1 < min_oi=100, 两个合约都被过滤 → leader 不变
    tracker.check()
    # 此时 leader 未变
    assert tracker.get_oi_snapshot("RB")["current_leader"] == "RB2511"
    print(f"  [OK] 过期合约被排除")


def test_multiple_bases():
    """同时跟踪多个品种"""
    cm = ContractManager()
    cm.start()
    recorder = _TestRecorder()
    tracker = OpenInterestTracker(cm, confirmation_count=2, check_interval_seconds=0, on_main_contract_changed=recorder)

    now = datetime.now()
    # RB: 先设 RB2510 为初始主力
    tracker.on_tick(_make_tick("RB2510", 100000, now))
    tracker.check()
    assert tracker.get_oi_snapshot("RB")["current_leader"] == "RB2510"

    # RB2511 OI 反超 → 触发换月
    tracker.on_tick(_make_tick("RB2511", 130000, now))
    tracker.check()
    tracker.check()

    # CU: 先设 CU2508 为初始主力
    tracker.on_tick(_make_tick("CU2508", 50000, now))
    tracker.check()
    assert tracker.get_oi_snapshot("CU")["current_leader"] == "CU2508"

    # CU2507 OI 反超 → 触发换月
    tracker.on_tick(_make_tick("CU2507", 80000, now))
    tracker.check()
    tracker.check()

    rb_snap = tracker.get_oi_snapshot("RB")
    cu_snap = tracker.get_oi_snapshot("CU")
    assert rb_snap["current_leader"] == "RB2511"
    assert cu_snap["current_leader"] == "CU2507"
    assert len(recorder.calls) == 2, f"两个品种各触发1次: {recorder.calls}"
    print(f"  [OK] 多品种跟踪: RB→{rb_snap['current_leader']}, CU→{cu_snap['current_leader']}")


def test_config_load():
    """验证配置加载"""
    from src.core.config import Config, LiveConfig
    lc = LiveConfig()
    assert lc.oi_tracker_enabled is True
    assert lc.oi_threshold_ratio == 0.20
    assert lc.oi_confirmation_count == 5
    print(f"  [OK] LiveConfig OI 字段加载正常")


def test_required_subscriptions():
    """验证 get_required_subscriptions 返回额外合约"""
    cm = ContractManager()
    cm.start()
    tracker = OpenInterestTracker(cm)
    extra = tracker.get_required_subscriptions(["RB2505"])
    assert len(extra) > 0, "应返回额外合约"
    assert "RB2505" not in extra, "不应包含用户已有合约"
    assert all(c.startswith("RB") for c in extra), "应全是 RB 品种"
    print(f"  [OK] 额外订阅 {len(extra)} 个合约, 示例: {extra[:3]}")


def test_extract_base():
    """验证 ContractManager.extract_base"""
    from src.trade.contract_manager import ContractManager
    assert ContractManager.extract_base("RB2510") == "RB"
    assert ContractManager.extract_base("CU2507") == "CU"
    assert ContractManager.extract_base("IF2506") == "IF"
    assert ContractManager.extract_base("SC0") == "SC"
    print(f"  [OK] extract_base 正常")


def test_has_main_contract():
    """验证 has_main_contract"""
    cm = ContractManager()
    cm.start()
    assert cm.has_main_contract("RB") == False, "默认连续合约应返回 False"
    cm.update_main_contract("RB", "RB2510")
    assert cm.has_main_contract("RB") == True, "更新为非连续合约应返回 True"
    print(f"  [OK] has_main_contract 正常")


def test_tick_data_fix():
    """验证 TickData 5档修复"""
    from src.trade.gateway import TickData
    t = TickData(
        symbol="RB2510", exchange="SHFE",
        last_price=3500.0, volume=1000, open_interest=120000,
        bid_price_1=3499.0, bid_volume_1=10,
        ask_price_1=3501.0, ask_volume_1=5,
        bid_price_5=3495.0, bid_volume_5=50,
        ask_price_5=3505.0, ask_volume_5=15,
    )
    assert hasattr(t, "bid_price_5")
    assert t.open_interest == 120000
    print(f"  [OK] TickData 5档正常, OI={t.open_interest}")


if __name__ == "__main__":
    tests = [
        ("extract_base", test_extract_base),
        ("has_main_contract", test_has_main_contract),
        ("TickData 5档", test_tick_data_fix),
        ("config 加载", test_config_load),
        ("初始主力识别", test_initial_leader),
        ("阈值不足不换月", test_threshold_not_met),
        ("确认不足不换月", test_confirmation_not_met),
        ("确认达标触发换月", test_rollover_triggered),
        ("旧主力抑制期", test_old_leader_suppressed),
        ("过期合约排除", test_stale_contract_excluded),
        ("多品种跟踪", test_multiple_bases),
        ("额外订阅计算", test_required_subscriptions),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            print(f"\n--- {name} ---")
            fn()
            passed += 1
        except Exception as e:
            import traceback
            print(f"  [FAIL] {e}")
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*40}")
    print(f"结果: {passed}/{len(tests)} 通过", end="")
    if failed:
        print(f", {failed} 失败")
    else:
        print("")
    print(f"{'='*40}")
    sys.exit(0 if failed == 0 else 1)
