"""
合约管理与换月移仓

期货合约有到期日，必须自动识别主力合约并执行换月移仓。

核心职责:
  1. 品种规格管理 — 合约乘数/保证金率/最小变动价位等
  2. 主力合约跟踪 — 当前主力合约是哪个
  3. 换月检测 — 主力合约是否发生变化
  4. 移仓执行 — 平旧仓 → 开新仓（跨合约）
  5. 交割月限制 — 临近交割月提高保证金/限制开仓
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, date
from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path

from loguru import logger


# ──────────── 品种规格数据库 ────────────

PRODUCT_SPECS: Dict[str, dict] = {
    "RB": {
        "name": "螺纹钢",
        "exchange": "shfe",
        "multiplier": 10,
        "margin_rate": 0.10,
        "commission_open": 0.0001,
        "commission_close": 0.0001,
        "commission_close_today": 0.0,
        "tick_size": 1,
        "min_move_value": 10,
        "delivery_month_limit": 1,       # 交割月前1个月限制开仓
        "delivery_month_stop": 0,         # 交割月禁止交易
        "night_session": True,
    },
    "CU": {
        "name": "沪铜",
        "exchange": "shfe",
        "multiplier": 5,
        "margin_rate": 0.12,
        "commission_open": 0.00005,
        "commission_close": 0.00005,
        "commission_close_today": 0.0001,
        "tick_size": 10,
        "min_move_value": 50,
        "delivery_month_limit": 1,
        "delivery_month_stop": 0,
        "night_session": True,
    },
    "AL": {
        "name": "沪铝",
        "exchange": "shfe",
        "multiplier": 5,
        "margin_rate": 0.10,
        "commission_open": 0.0001,
        "commission_close": 0.0001,
        "commission_close_today": 0.0,
        "tick_size": 5,
        "min_move_value": 25,
        "night_session": True,
    },
    "ZN": {
        "name": "沪锌",
        "exchange": "shfe",
        "multiplier": 5,
        "margin_rate": 0.10,
        "commission_open": 0.0001,
        "commission_close": 0.0001,
        "commission_close_today": 0.0,
        "tick_size": 5,
        "min_move_value": 25,
        "night_session": True,
    },
    "AU": {
        "name": "沪金",
        "exchange": "shfe",
        "multiplier": 1000,        # 克
        "margin_rate": 0.08,
        "commission_open": 0.00005,
        "commission_close": 0.00005,
        "commission_close_today": 0.0,
        "tick_size": 0.02,
        "min_move_value": 20,
        "night_session": True,
    },
    "AG": {
        "name": "沪银",
        "exchange": "shfe",
        "multiplier": 15,          # 千克
        "margin_rate": 0.10,
        "commission_open": 0.0001,
        "commission_close": 0.0001,
        "commission_close_today": 0.0,
        "tick_size": 1,
        "min_move_value": 15,
        "night_session": True,
    },
    "RU": {
        "name": "橡胶",
        "exchange": "shfe",
        "multiplier": 10,
        "margin_rate": 0.10,
        "commission_open": 0.0001,
        "commission_close": 0.0001,
        "commission_close_today": 0.0,
        "tick_size": 5,
        "min_move_value": 50,
        "night_session": True,
    },
    "HC": {
        "name": "热轧卷板",
        "exchange": "shfe",
        "multiplier": 10,
        "margin_rate": 0.10,
        "commission_open": 0.0001,
        "commission_close": 0.0001,
        "commission_close_today": 0.0,
        "tick_size": 1,
        "min_move_value": 10,
        "night_session": True,
    },
    "NI": {
        "name": "沪镍",
        "exchange": "shfe",
        "multiplier": 1,
        "margin_rate": 0.12,
        "commission_open": 0.0001,
        "commission_close": 0.0001,
        "commission_close_today": 0.0,
        "tick_size": 10,
        "min_move_value": 10,
        "night_session": True,
    },
    "SN": {
        "name": "沪锡",
        "exchange": "shfe",
        "multiplier": 1,
        "margin_rate": 0.12,
        "commission_open": 0.0001,
        "commission_close": 0.0001,
        "commission_close_today": 0.0,
        "tick_size": 10,
        "min_move_value": 10,
        "night_session": True,
    },
    "IF": {
        "name": "沪深300股指",
        "exchange": "cffex",
        "multiplier": 300,
        "margin_rate": 0.12,
        "commission_open": 0.000023,
        "commission_close": 0.000023,
        "commission_close_today": 0.00023,
        "tick_size": 0.2,
        "min_move_value": 60,
        "delivery_month_limit": 0,
        "delivery_month_stop": 0,
        "night_session": False,
    },
    "IH": {
        "name": "上证50股指",
        "exchange": "cffex",
        "multiplier": 300,
        "margin_rate": 0.12,
        "commission_open": 0.000023,
        "commission_close": 0.000023,
        "commission_close_today": 0.00023,
        "tick_size": 0.2,
        "min_move_value": 60,
        "delivery_month_limit": 0,
        "delivery_month_stop": 0,
        "night_session": False,
    },
    "IC": {
        "name": "中证500股指",
        "exchange": "cffex",
        "multiplier": 200,
        "margin_rate": 0.12,
        "commission_open": 0.000023,
        "commission_close": 0.000023,
        "commission_close_today": 0.00023,
        "tick_size": 0.2,
        "min_move_value": 40,
        "delivery_month_limit": 0,
        "delivery_month_stop": 0,
        "night_session": False,
    },
    "SC": {
        "name": "原油",
        "exchange": "ine",
        "multiplier": 1000,
        "margin_rate": 0.15,
        "commission_open": 0.0001,
        "commission_close": 0.0001,
        "commission_close_today": 0.0,
        "tick_size": 0.1,
        "min_move_value": 100,
        "delivery_month_limit": 1,
        "delivery_month_stop": 0,
        "night_session": True,
    },
    "P": {
        "name": "棕榈油",
        "exchange": "dce",
        "multiplier": 10,
        "margin_rate": 0.10,
        "commission_open": 0.0001,
        "commission_close": 0.0001,
        "commission_close_today": 0.0,
        "tick_size": 2,
        "min_move_value": 20,
        "night_session": True,
    },
    "M": {
        "name": "豆粕",
        "exchange": "dce",
        "multiplier": 10,
        "margin_rate": 0.10,
        "commission_open": 0.0001,
        "commission_close": 0.0001,
        "commission_close_today": 0.0,
        "tick_size": 1,
        "min_move_value": 10,
        "night_session": True,
    },
    "Y": {
        "name": "豆油",
        "exchange": "dce",
        "multiplier": 10,
        "margin_rate": 0.10,
        "commission_open": 0.0001,
        "commission_close": 0.0001,
        "commission_close_today": 0.0,
        "tick_size": 2,
        "min_move_value": 20,
        "night_session": True,
    },
    "I": {
        "name": "铁矿石",
        "exchange": "dce",
        "multiplier": 100,
        "margin_rate": 0.13,
        "commission_open": 0.0001,
        "commission_close": 0.0001,
        "commission_close_today": 0.0,
        "tick_size": 0.5,
        "min_move_value": 50,
        "delivery_month_limit": 1,
        "delivery_month_stop": 0,
        "night_session": True,
    },
    "J": {
        "name": "焦炭",
        "exchange": "dce",
        "multiplier": 100,
        "margin_rate": 0.11,
        "commission_open": 0.0001,
        "commission_close": 0.0001,
        "commission_close_today": 0.0,
        "tick_size": 0.5,
        "min_move_value": 50,
        "night_session": True,
    },
    "JM": {
        "name": "焦煤",
        "exchange": "dce",
        "multiplier": 60,
        "margin_rate": 0.11,
        "commission_open": 0.0001,
        "commission_close": 0.0001,
        "commission_close_today": 0.0,
        "tick_size": 0.5,
        "min_move_value": 30,
        "night_session": True,
    },
    "TA": {
        "name": "PTA",
        "exchange": "czce",
        "multiplier": 5,
        "margin_rate": 0.08,
        "commission_open": 0.0001,
        "commission_close": 0.0001,
        "commission_close_today": 0.0,
        "tick_size": 2,
        "min_move_value": 10,
        "night_session": True,
    },
    "MA": {
        "name": "甲醇",
        "exchange": "czce",
        "multiplier": 10,
        "margin_rate": 0.08,
        "commission_open": 0.0001,
        "commission_close": 0.0001,
        "commission_close_today": 0.0,
        "tick_size": 1,
        "min_move_value": 10,
        "night_session": True,
    },
    "SR": {
        "name": "白糖",
        "exchange": "czce",
        "multiplier": 10,
        "margin_rate": 0.08,
        "commission_open": 0.0001,
        "commission_close": 0.0001,
        "commission_close_today": 0.0,
        "tick_size": 1,
        "min_move_value": 10,
        "night_session": True,
    },
    "CF": {
        "name": "棉花",
        "exchange": "czce",
        "multiplier": 5,
        "margin_rate": 0.08,
        "commission_open": 0.0001,
        "commission_close": 0.0001,
        "commission_close_today": 0.0,
        "tick_size": 5,
        "min_move_value": 25,
        "night_session": True,
    },
    "OI": {
        "name": "菜籽油",
        "exchange": "czce",
        "multiplier": 10,
        "margin_rate": 0.08,
        "commission_open": 0.0001,
        "commission_close": 0.0001,
        "commission_close_today": 0.0,
        "tick_size": 1,
        "min_move_value": 10,
        "night_session": True,
    },
    "FG": {
        "name": "玻璃",
        "exchange": "czce",
        "multiplier": 20,
        "margin_rate": 0.10,
        "commission_open": 0.0001,
        "commission_close": 0.0001,
        "commission_close_today": 0.0,
        "tick_size": 1,
        "min_move_value": 20,
        "night_session": True,
    },
}

# 按交易所分组
EXCHANGE_PRODUCTS: Dict[str, List[str]] = {
    "shfe": ["RB", "CU", "AL", "ZN", "AU", "AG", "RU", "HC", "NI", "SN"],
    "dce": ["P", "M", "Y", "I", "J", "JM"],
    "czce": ["TA", "MA", "SR", "CF", "OI", "FG"],
    "cffex": ["IF", "IH", "IC"],
    "ine": ["SC"],
    "gfex": [],
}


@dataclass
class MainContractInfo:
    """主力合约信息"""
    base: str                           # 品种代码 (RB)
    current_contract: str               # 当前主力合约 (RB2510)
    previous_contract: Optional[str]    # 上一主力合约
    changed_at: Optional[datetime]      # 换月时间
    open_interest_ratio: float = 0.0    # 当前主力持仓量占比
    detected_method: str = ""           # 识别方式


class RolloverAction(Enum):
    """换月动作"""
    NONE = "none"               # 无需换月
    PENDING = "pending"         # 检测到换月，待执行
    EXECUTING = "executing"     # 执行中
    COMPLETED = "completed"     # 已完成
    FAILED = "failed"           # 失败


@dataclass
class RolloverRecord:
    """换月移仓记录"""
    base: str
    old_contract: str
    new_contract: str
    old_price: float = 0.0
    new_price: float = 0.0
    volume: int = 0
    pnl: float = 0.0            # 平仓盈亏
    cost: float = 0.0           # 开新仓费用
    action: RolloverAction = RolloverAction.NONE
    timestamp: datetime = field(default_factory=datetime.now)


class ContractManager:
    """
    合约管理器

    管理所有期货品种的合约规格、主力合约跟踪、换月检测与移仓执行。

    用法:
        cm = ContractManager(engine=live_engine)
        cm.start()
        # 在主循环中周期性调用:
        cm.check_rollovers()
        cm.check_delivery_limits()
    """

    def __init__(
        self,
        engine=None,
        config_path: Optional[str] = None,
    ):
        """
        Args:
            engine: LiveEngine 实例（用于执行移仓交易）
            config_path: 自定义品种配置路径（JSON），不指定则使用内置配置
        """
        self.engine = engine
        self._specs: Dict[str, dict] = {}

        # 加载规格
        if config_path and Path(config_path).exists():
            self._load_specs(config_path)
        else:
            self._specs = {k: dict(v) for k, v in PRODUCT_SPECS.items()}

        # 主力合约跟踪: base -> MainContractInfo
        self._main_contracts: Dict[str, MainContractInfo] = {}

        # 换月记录: base -> RolloverRecord
        self._rollovers: Dict[str, RolloverRecord] = {}

        # 换月检查锁（避免重复检测）
        self._last_check: Dict[str, date] = {}

        logger.info(f"合约管理器初始化: {len(self._specs)} 个品种")

    # ────────────── 品种规格查询 ──────────────

    def get_spec(self, base: str) -> Optional[dict]:
        """
        获取品种规格参数

        Returns:
            dict 包含 multiplier, margin_rate, tick_size 等
            或 None（未知品种）
        """
        return self._specs.get(base.upper())

    def has_spec(self, base: str) -> bool:
        """品种是否在数据库中"""
        return base.upper() in self._specs

    def list_products(self) -> List[str]:
        """列出所有支持的品种代码"""
        return sorted(self._specs.keys())

    def list_products_by_exchange(self, exchange: str) -> List[str]:
        """按交易所列出品种"""
        return EXCHANGE_PRODUCTS.get(exchange, [])

    def get_exchange(self, base: str) -> str:
        """获取品种所属交易所"""
        spec = self.get_spec(base)
        return spec.get("exchange", "") if spec else ""

    def get_multiplier(self, base: str) -> int:
        """获取合约乘数"""
        spec = self.get_spec(base)
        return spec["multiplier"] if spec else 10

    def get_margin_rate(self, base: str, contract: str = "") -> float:
        """
        获取保证金率

        可以对具体合约返回不同值（如交割月前提高保证金）

        Args:
            base: 品种代码
            contract: 合约代码（可选，用于交割月判断）

        Returns:
            保证金率 (0.10 = 10%)
        """
        spec = self.get_spec(base)
        if not spec:
            return 0.10

        base_rate = spec["margin_rate"]

        # 交割月前提高保证金
        if contract:
            months_to_delivery = self._months_to_delivery(contract)
            if months_to_delivery is not None and 0 <= months_to_delivery <= 1:
                # 临近交割月，保证金提高50%
                adjusted = base_rate * 1.5
                logger.info(f"[{contract}] 临近交割月({months_to_delivery}个月), "
                           f"保证金率 {base_rate:.0%} → {adjusted:.0%}")
                return adjusted

        return base_rate

    def get_tick_size(self, base: str) -> float:
        """获取最小变动价位"""
        spec = self.get_spec(base)
        return spec["tick_size"] if spec else 1

    def get_min_move_value(self, base: str) -> float:
        """获取每跳价值 = tick_size * multiplier"""
        spec = self.get_spec(base)
        return spec["min_move_value"] if spec else 10

    # ────────────── 合约代码工具 ──────────────

    @staticmethod
    def parse_contract(contract: str) -> dict:
        """
        解析合约代码

        Args:
            contract: 合约代码 (RB2505, IF2506, SC0)

        Returns:
            dict: {base, year, month, is_continuous}
        """
        contract = contract.upper()

        # 连续合约: 纯字母base + "0" (如 RB0, CU0, SC0)
        if len(contract) <= 4 and contract.endswith("0") and contract[:-1].isalpha():
            base = contract.rstrip("0")
            return {
                "base": base,
                "contract": contract,
                "year": None,
                "month": None,
                "is_continuous": True,
            }

        base = contract.rstrip("0123456789")
        num_part = contract[len(base):]

        year = None
        month = None
        if len(num_part) == 4:
            year = int("20" + num_part[:2])
            month = int(num_part[2:])
        elif len(num_part) == 3:
            year = int("20" + num_part[0])
            month = int(num_part[1:])

        return {
            "base": base,
            "contract": contract,
            "year": year,
            "month": month,
            "is_continuous": False,
        }

    @staticmethod
    def build_contract_code(base: str, year: int, month: int) -> str:
        """
        生成合约代码

        Args:
            base: 品种代码 (RB)
            year: 年份 (2025)
            month: 月份 (5)

        Returns:
            合约代码 (RB2505)
        """
        return f"{base.upper()}{year % 100:02d}{month:02d}"

    @staticmethod
    def get_contract_month(contract: str) -> int:
        """获取合约的月份"""
        parsed = ContractManager.parse_contract(contract)
        return parsed.get("month", 0) or 0

    @staticmethod
    def get_contract_year(contract: str) -> int:
        """获取合约的年份"""
        parsed = ContractManager.parse_contract(contract)
        return parsed.get("year", 0) or 0

    @staticmethod
    def extract_base(symbol: str) -> str:
        """从合约代码提取品种代码"""
        return ContractManager.parse_contract(symbol)["base"]

    def has_main_contract(self, base: str) -> bool:
        """品种是否有非连续的主力合约"""
        info = self._main_contracts.get(base.upper())
        return bool(info and not self.parse_contract(info.current_contract)["is_continuous"])

    def get_tracked_bases(self) -> List[str]:
        """返回所有被跟踪的品种列表"""
        return list(self._main_contracts.keys())

    def get_contract_sort_key(self, contract: str) -> int:
        """
        获取合约排序键（用于找下一个合约）

        例如: RB2505 → 202505, RB2510 → 202510
        """
        parsed = self.parse_contract(contract)
        y = parsed["year"] or 0
        m = parsed["month"] or 0
        return y * 100 + m

    def get_trading_months(self, base: str) -> List[int]:
        """
        获取品种的交易月份列表

        不同品种的合约月份不同:
        - 螺纹钢(RB): 1-12月
        - 棕榈油(P): 1-12月
        - 股指(IF): 当月+下月+下季+隔季

        Args:
            base: 品种代码

        Returns:
            月份列表 [1, 2, ..., 12]
        """
        base = base.upper()
        spec = self.get_spec(base)
        if spec and spec.get("exchange") == "cffex":
            now = datetime.now()
            current_month = now.month
            months = []
            # IF/IH/IC: 当月、下月、下季、隔季
            months.append(current_month)
            months.append(current_month + 1 if current_month < 12 else 1)
            # 下季: (当前季度+1) 的第一个月
            q = (current_month - 1) // 3
            next_q_start = (q + 1) * 3 + 1
            months.append(next_q_start)
            # 隔季
            next_q2_start = next_q_start + 3
            months.append(next_q2_start)
            return [m if m <= 12 else m - 12 for m in months]
        # 商品期货: 1-12月
        return list(range(1, 13))

    # ────────────── 主力合约跟踪 ──────────────

    def update_main_contract(self, base: str, contract: str,
                             open_interest_ratio: float = 0.0,
                             detected_method: str = "manual") -> bool:
        """
        更新主力合约信息

        Args:
            base: 品种代码
            contract: 当前主力合约代码
            open_interest_ratio: 持仓量占比
            detected_method: 识别方式 (manual / volume / api)

        Returns:
            True 表示主力合约发生变化（需要换月）
        """
        base = base.upper()
        old_info = self._main_contracts.get(base)
        old_contract = old_info.current_contract if old_info else None

        is_changed = (old_contract is not None and old_contract != contract)

        self._main_contracts[base] = MainContractInfo(
            base=base,
            current_contract=contract,
            previous_contract=old_contract,
            changed_at=datetime.now() if is_changed else (old_info.changed_at if old_info else None),
            open_interest_ratio=open_interest_ratio,
            detected_method=detected_method,
        )

        if is_changed:
            logger.info(f"[{base}] 主力合约变更: {old_contract} → {contract}")
            return True

        if old_info is None:
            logger.info(f"[{base}] 主力合约: {contract}")

        return False

    def get_current_main(self, base: str) -> Optional[str]:
        """获取当前主力合约代码"""
        info = self._main_contracts.get(base.upper())
        return info.current_contract if info else None

    def get_main_contract_info(self, base: str) -> Optional[MainContractInfo]:
        """获取主力合约详情"""
        return self._main_contracts.get(base.upper())

    def detect_rollover(self, base: str, new_main_contract: str) -> bool:
        """
        检测是否需要换月

        当新主力合约与当前持仓合约不同时返回 True。

        Args:
            base: 品种代码
            new_main_contract: 新识别的主力合约

        Returns:
            是否需要换月
        """
        base = base.upper()
        current = self.get_current_main(base)

        if current is None:
            self.update_main_contract(base, new_main_contract)
            return False

        if current == new_main_contract:
            return False

        # 检查是否已在换月过程中
        record = self._rollovers.get(base)
        if record and record.action in (RolloverAction.PENDING, RolloverAction.EXECUTING):
            logger.debug(f"[{base}] 换月已在进行中: {record.old_contract} → {record.new_contract}")
            return False

        logger.info(f"[{base}] 检测到换月: {current} → {new_main_contract}")

        # 更新主力合约信息
        self.update_main_contract(base, new_main_contract)

        # 创建换月记录
        self._rollovers[base] = RolloverRecord(
            base=base,
            old_contract=current,
            new_contract=new_main_contract,
            action=RolloverAction.PENDING,
        )
        return True

    # ────────────── 换月移仓执行 ──────────────

    def execute_rollover(self, base: str) -> bool:
        """
        执行换月移仓

        流程:
        1. 获取当前持仓（旧合约）
        2. 获取新主力合约当前价格
        3. 平旧仓 → 开新仓（同方向同手数）
        4. 记录换月信息

        Args:
            base: 品种代码

        Returns:
            是否成功执行
        """
        if not self.engine:
            logger.error(f"[{base}] 移仓失败: 未绑定引擎")
            return False

        base = base.upper()
        info = self._main_contracts.get(base)
        if not info or not info.previous_contract:
            logger.warning(f"[{base}] 无换月信息")
            return False

        old_contract = info.previous_contract
        new_contract = info.current_contract

        # 获取持仓
        long_pos, short_pos = self.engine.get_position(base, contract=old_contract)

        if (not long_pos or long_pos.volume <= 0) and (not short_pos or short_pos.volume <= 0):
            logger.info(f"[{base}] 无持仓, 无需移仓")
            # 更新换月记录
            self._rollovers[base] = RolloverRecord(
                base=base,
                old_contract=old_contract,
                new_contract=new_contract,
                action=RolloverAction.COMPLETED,
            )
            return True

        record = RolloverRecord(
            base=base,
            old_contract=old_contract,
            new_contract=new_contract,
            action=RolloverAction.EXECUTING,
        )

        now = datetime.now()
        success = True

        try:
            # 平多仓
            if long_pos and long_pos.volume > 0:
                vol = long_pos.volume
                logger.info(f"[{base}] 移仓平多: {old_contract} {vol}手")
                ok = self.engine.close_long(now, base, long_pos.avg_price, vol, contract=old_contract)
                if ok:
                    logger.info(f"[{base}] 移仓开多: {new_contract} {vol}手")
                    ok = self.engine.open_long(now, base, long_pos.avg_price, vol, contract=new_contract)
                if not ok:
                    success = False

            # 平空仓
            if short_pos and short_pos.volume > 0:
                vol = short_pos.volume
                logger.info(f"[{base}] 移仓平空: {old_contract} {vol}手")
                ok = self.engine.close_short(now, base, short_pos.avg_price, vol, contract=old_contract)
                if ok:
                    logger.info(f"[{base}] 移仓开空: {new_contract} {vol}手")
                    ok = self.engine.open_short(now, base, short_pos.avg_price, vol, contract=new_contract)
                if not ok:
                    success = False

        except Exception as e:
            logger.error(f"[{base}] 移仓异常: {e}")
            success = False

        record.action = RolloverAction.COMPLETED if success else RolloverAction.FAILED
        self._rollovers[base] = record

        if success:
            logger.success(f"[{base}] 换月移仓完成: {old_contract} → {new_contract}")
        else:
            logger.error(f"[{base}] 换月移仓失败: {old_contract} → {new_contract}")

        return success

    def get_rollover_status(self, base: str) -> RolloverAction:
        """获取换月状态"""
        record = self._rollovers.get(base.upper())
        return record.action if record else RolloverAction.NONE

    def get_rollover_record(self, base: str) -> Optional[RolloverRecord]:
        """获取换月记录"""
        return self._rollovers.get(base.upper())

    def list_rollovers(self) -> List[RolloverRecord]:
        """列出所有换月记录"""
        return list(self._rollovers.values())

    # ────────────── 交割月检查 ──────────────

    def is_delivery_month(self, contract: str) -> bool:
        """
        合约是否进入交割月

        Args:
            contract: 合约代码 (RB2505)

        Returns:
            True 表示当前月是该合约的交割月
        """
        parsed = self.parse_contract(contract)
        if parsed["is_continuous"]:
            return False

        y, m = parsed["year"], parsed["month"]
        if not y or not m:
            return False

        now = datetime.now()
        return now.year == y and now.month == m

    def is_approaching_delivery(self, contract: str, limit_months: int = 1) -> bool:
        """
        合约是否临近交割月

        Args:
            contract: 合约代码
            limit_months: 提前几个月视为"临近"

        Returns:
            True 表示临近交割月
        """
        parsed = self.parse_contract(contract)
        if parsed["is_continuous"]:
            return False

        y, m = parsed["year"], parsed["month"]
        if not y or not m:
            return False

        now = datetime.now()
        contract_month = y * 12 + m
        current_month = now.year * 12 + now.month

        return 0 <= (contract_month - current_month) <= limit_months

    def _months_to_delivery(self, contract: str) -> Optional[int]:
        """获取距离交割月的月数"""
        parsed = self.parse_contract(contract)
        if parsed["is_continuous"]:
            return None

        y, m = parsed["year"], parsed["month"]
        if not y or not m:
            return None

        now = datetime.now()
        contract_month = y * 12 + m
        current_month = now.year * 12 + now.month

        return contract_month - current_month

    def check_delivery_limits(self, base: str) -> Optional[str]:
        """
        检查交割月限制

        Returns:
            None 表示无限制, str 表示限制原因
        """
        base = base.upper()
        spec = self.get_spec(base)
        if not spec:
            return None

        main_contract = self.get_current_main(base)
        if not main_contract:
            return None

        limit_months = spec.get("delivery_month_limit", 1)
        stop_month = spec.get("delivery_month_stop", 0)

        # 禁止交易
        if self.is_delivery_month(main_contract) and stop_month == 0:
            return f"[{main_contract}] 已进入交割月, 禁止交易"

        # 限制开仓
        if self.is_approaching_delivery(main_contract, limit_months):
            return f"[{main_contract}] 临近交割月({limit_months}个月), 限制开仓"

        return None

    # ────────────── 合约列表 ──────────────

    def get_active_contracts(self, base: str) -> List[str]:
        """
        获取活跃合约列表

        对于商品期货，返回所有可能的合约代码
        对于股指，返回当月/下月/下季/隔季

        Args:
            base: 品种代码

        Returns:
            合约代码列表, 按到期时间排序
        """
        base = base.upper()
        spec = self.get_spec(base)
        if not spec:
            return []

        now = datetime.now()
        months = self.get_trading_months(base)
        contracts = []

        for m in months:
            y = now.year
            if m < now.month:
                y += 1
            contracts.append(self.build_contract_code(base, y, m))

        return sorted(contracts, key=self.get_contract_sort_key)

    def get_next_main_candidate(self, base: str) -> Optional[str]:
        """
        获取下一个潜在主力合约

        基于当前主力合约，推断下一个可能的主力合约

        Args:
            base: 品种代码

        Returns:
            下一个可能的合约代码
        """
        base = base.upper()
        current = self.get_current_main(base)
        if not current:
            contracts = self.get_active_contracts(base)
            return contracts[0] if contracts else None

        parsed = self.parse_contract(current)
        if parsed["is_continuous"]:
            return None

        y, m = parsed["year"], parsed["month"]
        if not y or not m:
            return None

        # 找下一个月份
        months = self.get_trading_months(base)

        next_month = None
        for tm in sorted(months):
            if tm > m:
                next_month = tm
                break

        if next_month is None:
            # 下一年
            next_month = months[0]
            y += 1

        return self.build_contract_code(base, y, next_month)

    # ────────────── 引擎集成 ──────────────

    def start(self):
        """启动合约管理器（在引擎启动时调用）"""
        logger.info("合约管理器启动")
        for base in self._specs:
            if base not in self._main_contracts:
                info = MainContractInfo(
                    base=base,
                    current_contract=f"{base}0",  # 默认使用连续合约
                    previous_contract=None,
                    changed_at=None,
                    detected_method="default",
                )
                self._main_contracts[base] = info
        logger.info(f"合约管理器就绪: {len(self._main_contracts)} 个品种已跟踪")

    def stop(self):
        """停止合约管理器"""
        logger.info("合约管理器停止")

    def check_rollovers(self) -> List[str]:
        """
        检查所有品种是否需要换月（供主循环调用）

        Returns:
            需要换月的品种列表
        """
        triggered = []
        for base in list(self._main_contracts.keys()):
            info = self._main_contracts[base]
            if info.previous_contract and info.current_contract != info.previous_contract:
                record = self._rollovers.get(base)
                if not record or record.action not in (
                    RolloverAction.PENDING, RolloverAction.EXECUTING
                ):
                    triggered.append(base)
        return triggered

    def periodic_check(self):
        """
        周期性检查（供引擎主循环调用）

        每轮检查:
        1. 交割月限制
        2. 需换月的品种
        """
        for base in list(self._main_contracts.keys()):
            # 交割月限制
            limit = self.check_delivery_limits(base)
            if limit:
                logger.warning(limit)

            # 检查是否需要执行换月
            record = self._rollovers.get(base)
            if record and record.action == RolloverAction.PENDING:
                self.execute_rollover(base)

    # ────────────── 序列化 ──────────────

    def to_dict(self) -> dict:
        """序列化合约管理器状态"""
        return {
            "main_contracts": {
                base: {
                    "current_contract": info.current_contract,
                    "previous_contract": info.previous_contract,
                    "changed_at": info.changed_at.isoformat() if info.changed_at else None,
                    "detected_method": info.detected_method,
                }
                for base, info in self._main_contracts.items()
            },
            "rollovers": [
                {
                    "base": r.base,
                    "old_contract": r.old_contract,
                    "new_contract": r.new_contract,
                    "action": r.action.value,
                    "timestamp": r.timestamp.isoformat(),
                }
                for r in self._rollovers.values()
            ],
        }

    def save_state(self, path: str):
        """保存合约管理器状态"""
        state = self.to_dict()
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"合约状态保存失败: {e}")

    def load_state(self, path: str) -> bool:
        """加载合约管理器状态"""
        file_path = Path(path)
        if not file_path.exists():
            return False
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            for base, info in state.get("main_contracts", {}).items():
                self._main_contracts[base] = MainContractInfo(
                    base=base,
                    current_contract=info["current_contract"],
                    previous_contract=info.get("previous_contract"),
                    changed_at=datetime.fromisoformat(info["changed_at"]) if info.get("changed_at") else None,
                    detected_method=info.get("detected_method", "restored"),
                )
            logger.info(f"合约状态已恢复: {file_path.name}")
            return True
        except Exception as e:
            logger.error(f"合约状态加载失败: {e}")
            return False
