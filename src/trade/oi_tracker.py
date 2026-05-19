"""
基于持仓量(Open Interest)的主力合约自动识别

从 CTP 行情 Tick 中提取 OpenInterest，对比同一品种下所有活跃合约的 OI，
使用滞回比较机制自动识别主力合约并检测换月。

滞回机制:
  1. OI 阈值(20%): 候选合约 OI 必须超过当前主力 20% 才触发
  2. 确认次数(5次): 领先必须持续多次检查
  3. 旧主力抑制(60min): 换月后旧主力暂时不参与竞争
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Lock
from typing import Dict, List, Optional, Set, Tuple, Callable

from loguru import logger

from src.trade.gateway import TickData, BaseGateway
from src.trade.contract_manager import ContractManager, RolloverAction


@dataclass
class _ContractOI:
    """单个合约的 OI 状态"""
    oi: int = 0
    last_update: Optional[datetime] = None


@dataclass
class _Candidate:
    """候选合约"""
    contract: str
    oi: int
    confirmation_count: int = 1


@dataclass
class _BaseState:
    """一个品种的 OI 追踪状态"""
    base: str
    current_leader: Optional[str] = None
    current_leader_oi: int = 0
    previous_leader: Optional[str] = None
    suppressed_until: Optional[datetime] = None
    contracts: Dict[str, _ContractOI] = field(default_factory=dict)
    candidate: Optional[_Candidate] = None
    last_check_time: Optional[datetime] = None
    last_snapshot_time: Optional[datetime] = None


class OpenInterestTracker:
    """
    实时 OI 主力合约追踪器

    使用方式:
        tracker = OpenInterestTracker(cm)
        tracker.get_required_subscriptions(["RB2510"])  # 算额外合约
        # 在 _on_tick 中:
        tracker.on_tick(tick)
        # 在主循环中:
        tracker.check()
    """

    def __init__(
        self,
        contract_manager: ContractManager,
        threshold_ratio: float = 0.20,
        confirmation_count: int = 5,
        check_interval_seconds: int = 10,
        snapshot_interval_seconds: int = 60,
        min_oi_absolute: int = 100,
        old_leader_suppress_minutes: int = 60,
        on_main_contract_changed: Optional[Callable[[str, str, str], None]] = None,
    ):
        self._cm = contract_manager
        self._threshold = threshold_ratio
        self._confirm_count = confirmation_count
        self._check_interval = timedelta(seconds=check_interval_seconds)
        self._snapshot_interval = timedelta(seconds=snapshot_interval_seconds)
        self._min_oi = min_oi_absolute
        self._suppress = timedelta(minutes=old_leader_suppress_minutes)
        self._stale_cutoff = timedelta(minutes=5)
        self.on_main_contract_changed = on_main_contract_changed

        self._states: Dict[str, _BaseState] = {}
        self._lock = Lock()
        self._enabled = True

        logger.info(
            f"OI Tracker: 阈值={threshold_ratio:.0%}, "
            f"确认={confirmation_count}次, "
            f"抑制={old_leader_suppress_minutes}min"
        )

    # ────────────── 公开方法 ──────────────

    def get_required_subscriptions(self, user_symbols: List[str]) -> List[str]:
        """
        给定用户交易合约，计算 OI 追踪需要的额外订阅合约
        """
        extra: List[str] = []
        seen_bases: Set[str] = set()

        for sym in user_symbols:
            base = ContractManager.extract_base(sym)
            if base in seen_bases:
                continue
            seen_bases.add(base)
            self._init_base(base)

            for c in self._cm.get_active_contracts(base):
                if c not in user_symbols:
                    extra.append(c)

        return extra

    def on_tick(self, tick: TickData):
        """接收 Tick，更新 OI 数据（线程安全）"""
        if not self._enabled or tick.open_interest <= 0:
            return

        base = ContractManager.extract_base(tick.symbol)

        with self._lock:
            self._init_base(base)
            state = self._states[base]
            if tick.symbol not in state.contracts:
                state.contracts[tick.symbol] = _ContractOI()
            c = state.contracts[tick.symbol]
            c.oi = tick.open_interest
            c.last_update = tick.datetime or datetime.now()

    def check(self) -> List[Tuple[str, str, str]]:
        """
        周期性检查各品种 OI 主力的变化

        Returns:
            [(base, old_main, new_main), ...] 确认换月的列表
        """
        if not self._enabled:
            return []

        now = datetime.now()
        rollovers: List[Tuple[str, str, str]] = []

        with self._lock:
            for base, state in self._states.items():
                # 检查间隔
                if state.last_check_time and \
                   now - state.last_check_time < self._check_interval:
                    continue
                state.last_check_time = now

                result = self._check_base(base, state, now)
                if result:
                    rollovers.append(result)

                # 周期快照
                if not state.last_snapshot_time or \
                   now - state.last_snapshot_time >= self._snapshot_interval:
                    self._log_snapshot(base, state)
                    state.last_snapshot_time = now

        return rollovers

    def get_oi_snapshot(self, base: str) -> Optional[dict]:
        """获取品种的 OI 快照"""
        with self._lock:
            state = self._states.get(base)
            if not state:
                return None
            contract_oi = {}
            for c, s in state.contracts.items():
                contract_oi[c] = {
                    "oi": s.oi,
                    "last_update": s.last_update.isoformat() if s.last_update else None,
                }
            return {
                "base": base,
                "current_leader": state.current_leader,
                "current_leader_oi": state.current_leader_oi,
                "previous_leader": state.previous_leader,
                "contracts": contract_oi,
            }

    def disable(self):
        self._enabled = False

    def enable(self):
        self._enabled = True

    # ────────────── 内部方法 ──────────────

    def _init_base(self, base: str):
        """初始化品种状态"""
        if base not in self._states:
            self._states[base] = _BaseState(base=base)

    def _check_base(self, base: str, state: _BaseState,
                    now: datetime) -> Optional[Tuple[str, str, str]]:
        """
        检查单个品种的 OI 排名变化

        算法:
          1. 过滤 5 分钟未更新、OI 太低的合约
          2. 找 OI 最高的合约
          3. 与当前主力比较 + 滞回判断
        """
        if not state.contracts:
            return None

        # 过滤过期 + 低 OI 合约
        valid = {
            c: s for c, s in state.contracts.items()
            if s.last_update and now - s.last_update <= self._stale_cutoff
               and s.oi > self._min_oi
        }
        if not valid:
            return None

        # 找 OI 最高者
        candidate_contract, candidate_state = max(
            valid.items(), key=lambda x: x[1].oi
        )
        candidate_oi = candidate_state.oi

        current_leader = state.current_leader

        # 首次 → 设当前主力
        if current_leader is None:
            state.current_leader = candidate_contract
            state.current_leader_oi = candidate_oi
            logger.info(f"[{base}] OI 初始主力: {candidate_contract} (OI={candidate_oi})")
            return None

        # 仍是当前主力
        if candidate_contract == current_leader:
            state.current_leader_oi = candidate_oi
            state.candidate = None
            return None

        # 候选是前主力且在抑制期 → 跳过
        if state.previous_leader and candidate_contract == state.previous_leader:
            if state.suppressed_until and now < state.suppressed_until:
                return None

        # 计算 OI 比值
        current_oi = valid.get(current_leader)
        current_oi_val = current_oi.oi if current_oi else 0

        if current_oi_val <= 0:
            self._do_switch(base, state, candidate_contract, candidate_oi, now)
            return (base, current_leader, candidate_contract)

        ratio = candidate_oi / current_oi_val

        if ratio >= 1.0 + self._threshold:
            # 达标 → 增加确认
            if state.candidate and state.candidate.contract == candidate_contract:
                state.candidate.confirmation_count += 1
                state.candidate.oi = candidate_oi
            else:
                state.candidate = _Candidate(contract=candidate_contract, oi=candidate_oi)

            logger.debug(
                f"[{base}] 候选 {candidate_contract} OI={candidate_oi} "
                f"比值={ratio:.2f} 确认={state.candidate.confirmation_count}"
            )

            if state.candidate.confirmation_count >= self._confirm_count:
                self._do_switch(base, state, candidate_contract, candidate_oi, now)
                return (base, current_leader, candidate_contract)
        else:
            # 未达标 → 重置
            state.candidate = None

        return None

    def _do_switch(self, base: str, state: _BaseState,
                   new_contract: str, new_oi: int, now: datetime):
        """执行主力切换"""
        old = state.current_leader
        state.previous_leader = old
        state.suppressed_until = now + self._suppress
        state.current_leader = new_contract
        state.current_leader_oi = new_oi
        state.candidate = None

        logger.info(
            f"[{base}] 主力切换: {old} → {new_contract} "
            f"(OI={new_oi}, 抑制={self._suppress})"
        )

        if self.on_main_contract_changed:
            self.on_main_contract_changed(base, old, new_contract)

    def _log_snapshot(self, base: str, state: _BaseState):
        """记录 OI 快照日志"""
        if not state.contracts:
            return
        items = sorted(state.contracts.items())
        parts = [f"[{base}] OI:"]
        for c, s in items:
            marker = " <<" if c == state.current_leader else ""
            parts.append(f" {c}={s.oi}{marker}")
        logger.info(" |".join(parts))
