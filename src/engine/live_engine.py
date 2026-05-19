"""
实盘策略引擎

连接回测策略与真实交易网关的桥梁。
与 FuturesBacktestEngine 保持相同的公开接口，使策略代码可无缝切换。
"""
from enum import Enum, auto
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import json
import time
import threading

from loguru import logger

from src.backtest.futures_engine import PositionState, PositionSide
from src.trade.gateway import (
    BaseGateway, OrderData, TradeData, TickData, OrderDirection,
    OrderStatus,
)
from src.trade.risk_manager import RiskManager
from src.trade.contract_manager import ContractManager, RolloverAction
from src.strategy.futures_strategy import BaseFuturesStrategy
from src.monitor.alerter import Alerter
from src.core.config import LiveConfig
from src.trade.oi_tracker import OpenInterestTracker


class EngineState(Enum):
    """引擎状态"""
    IDLE = auto()
    CONNECTING = auto()
    RUNNING = auto()
    PAUSED = auto()
    STOPPED = auto()
    ERROR = auto()


class SessionPhase(Enum):
    """交易时段阶段"""
    PRE_OPEN = auto()          # 集合竞价
    CONTINUOUS = auto()        # 连续交易
    BREAK = auto()             # 休盘
    CLOSED = auto()            # 闭市


@dataclass
class Bar:
    """聚合后的K线数据"""
    datetime: datetime
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class PendingOrderInfo:
    """挂单跟踪信息（用于超时撤单重发）"""
    engine_order_id: str         # 网关返回的订单ID
    strategy_order_id: str       # 内部跟踪ID
    symbol: str
    direction: str               # open_long / open_short / close_long / close_short
    price: float
    volume: int
    filled_volume: int = 0
    status: str = "pending"      # pending / partial / filled / canceled / failed
    create_time: datetime = field(default_factory=datetime.now)
    retry_count: int = 0
    timeout_seconds: int = 30
    max_retries: int = 3


class BarAggregator:
    """Tick → OHLC K线聚合器"""

    def __init__(self, symbol: str, interval_minutes: int = 1):
        self.symbol = symbol
        self.interval = interval_minutes
        self._bar_start: Optional[datetime] = None
        self._open = 0.0
        self._high = 0.0
        self._low = 0.0
        self._close = 0.0
        self._volume = 0

    def update_tick(self, tick: TickData) -> Optional[Bar]:
        """
        处理一个 Tick，返回完成的 Bar（跨周期边界时）或 None。
        """
        if self._bar_start is None:
            self._bar_start = self._round_down(tick.datetime)
            self._open = tick.last_price
            self._high = tick.last_price
            self._low = tick.last_price
            self._close = tick.last_price
            self._volume = tick.volume
            return None

        boundary = self._round_down(tick.datetime)
        if boundary > self._bar_start:
            completed = Bar(
                datetime=self._bar_start,
                symbol=self.symbol,
                open=self._open,
                high=self._high,
                low=self._low,
                close=self._close,
                volume=self._volume,
            )
            self._bar_start = boundary
            self._open = tick.last_price
            self._high = tick.last_price
            self._low = tick.last_price
            self._close = tick.last_price
            self._volume = tick.volume
            return completed

        self._high = max(self._high, tick.last_price)
        self._low = min(self._low, tick.last_price)
        self._close = tick.last_price
        self._volume = tick.volume
        return None

    def force_finish(self) -> Optional[Bar]:
        """强制输出当前未完成的 Bar（收盘/休盘时）"""
        if self._bar_start is None:
            return None
        bar = Bar(
            datetime=self._bar_start,
            symbol=self.symbol,
            open=self._open,
            high=self._high,
            low=self._low,
            close=self._close,
            volume=self._volume,
        )
        self._bar_start = None
        return bar

    def _round_down(self, dt: datetime) -> datetime:
        """将时间向下取整到周期边界"""
        minute = (dt.minute // self.interval) * self.interval
        return dt.replace(minute=minute, second=0, microsecond=0)


class SessionTimeController:
    """
    期货交易时段控制器

    日盘:
      08:55-09:00  集合竞价
      09:00-10:15  连续交易
      10:15-10:30  休盘
      10:30-11:30  连续交易
      11:30-13:30  午休
      13:30-14:55  连续交易
      14:55-15:00  收盘集合竞价
      15:00-20:55  闭市

    夜盘（简化）:
      20:55-21:00  集合竞价
      21:00-23:00/01:00  夜盘连续交易
    """

    def __init__(self):
        self._phase = SessionPhase.CLOSED

    def update(self, now: datetime) -> SessionPhase:
        """更新时间阶段"""
        h, m = now.hour, now.minute
        t = h * 100 + m

        if 855 <= t < 900:
            self._phase = SessionPhase.PRE_OPEN
        elif 900 <= t < 1015:
            self._phase = SessionPhase.CONTINUOUS
        elif 1015 <= t < 1030:
            self._phase = SessionPhase.BREAK
        elif 1030 <= t < 1130:
            self._phase = SessionPhase.CONTINUOUS
        elif 1130 <= t < 1330:
            self._phase = SessionPhase.BREAK
        elif 1330 <= t < 1455:
            self._phase = SessionPhase.CONTINUOUS
        elif 1455 <= t < 1500:
            self._phase = SessionPhase.CONTINUOUS  # 收盘竞价仍可交易
        elif 2055 <= t < 2100:
            self._phase = SessionPhase.PRE_OPEN
        elif t >= 2100 or t < 300:
            self._phase = SessionPhase.CONTINUOUS  # 夜盘
        else:
            self._phase = SessionPhase.CLOSED
        return self._phase

    @property
    def phase(self) -> SessionPhase:
        return self._phase

    def is_trading_time(self) -> bool:
        """是否在可交易时段"""
        return self._phase in (SessionPhase.CONTINUOUS, SessionPhase.PRE_OPEN)

    def can_send_order(self) -> bool:
        """是否可以下单"""
        return self._phase == SessionPhase.CONTINUOUS


class LiveEngine:
    """
    实盘策略引擎

    与 FuturesBacktestEngine 保持一致的公开接口，现有期货策略无需修改即可运行。

    公开接口:
        open_long(date, symbol, price, volume) -> bool
        open_short(date, symbol, price, volume) -> bool
        close_long(date, symbol, price, volume, is_today, contract) -> bool
        close_short(date, symbol, price, volume, is_today, contract) -> bool
        get_position(symbol, contract) -> Tuple[Optional[PositionState], Optional[PositionState]]
        get_available_capital() -> float
        get_total_equity(prices) -> float

    生命周期:
        run(strategy, symbols) -> None
        stop() -> None
        pause() / resume()
    """

    def __init__(
        self,
        gateway: BaseGateway,
        config: LiveConfig,
        risk_manager: Optional[RiskManager] = None,
        alerter: Optional[Alerter] = None,
    ):
        self.gateway = gateway
        self.config = config

        # 合约管理器（自动识别主力合约 + 换月移仓）
        self.contract_manager = ContractManager(engine=self)

        # 重用现有的管理器（传入 contract_manager 启用保证金和风险度监控）
        auto_reduce_config = {
            "trigger_ratio": config.auto_reduce_trigger_ratio,
            "target_ratio": config.auto_reduce_target_ratio,
            "flat_ratio": config.flat_all_trigger_ratio,
        }
        self.risk_manager = risk_manager or RiskManager(
            gateway, initial_cash=config.initial_capital,
            contract_manager=self.contract_manager,
            auto_reduce_config=auto_reduce_config,
        )
        self.order_manager = self.risk_manager.order_manager
        self.position_manager = self.risk_manager.position_manager

        # 告警系统（未传入则不启用）
        self.alerter = alerter

        # OI 主力合约追踪
        self.oi_tracker: Optional[OpenInterestTracker] = None
        if config.oi_tracker_enabled:
            self.oi_tracker = OpenInterestTracker(
                contract_manager=self.contract_manager,
                threshold_ratio=config.oi_threshold_ratio,
                confirmation_count=config.oi_confirmation_count,
                check_interval_seconds=config.oi_check_interval_seconds,
                snapshot_interval_seconds=config.oi_snapshot_interval_seconds,
                min_oi_absolute=config.oi_min_oi_absolute,
                old_leader_suppress_minutes=config.oi_old_leader_suppress_minutes,
                on_main_contract_changed=self._on_oi_main_changed,
            )

        # 引擎状态
        self.state = EngineState.IDLE
        self.strategy: Optional[BaseFuturesStrategy] = None
        self.symbols: List[str] = []
        self.symbol: str = ""  # 主品种（strategy.symbol 兼容）

        # 品种参数（策略代码会访问 engine.contract_multiplier 等）
        self.contract_multiplier = config.contract_multiplier
        self.margin_rate = config.margin_rate

        # K线聚合：symbol -> aggregator
        self._bar_aggregators: Dict[str, BarAggregator] = {}
        self._bar_interval = config.bar_interval_minutes

        # 挂单跟踪
        self._pending_orders: Dict[str, PendingOrderInfo] = {}
        self._strategy_order_counter = 0

        # 交易时段
        self._session = SessionTimeController()

        # 持久化
        self._state_dir = Path(config.state_dir)
        self._state_dir.mkdir(parents=True, exist_ok=True)

        # 主循环控制
        self._running = False
        self._main_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # 注册网关回调
        gateway.on_tick = self._on_tick
        gateway.on_order = self._on_order
        gateway.on_trade = self._on_trade
        gateway.on_error = self._on_error
        gateway.on_disconnected = self._on_gateway_disconnected

        # 重连监控
        self._reconnect_alerted = False
        self._last_connected_check = 0

        logger.info(f"实盘引擎初始化: 资金={config.initial_capital}, 网关={config.gateway_name}")

    # ────────────── 公开接口（与 FuturesBacktestEngine 一致） ──────────────

    def open_long(self, date: datetime, symbol: str, price: float,
                  volume: int, contract: str = "") -> bool:
        """开多仓"""
        if volume <= 0:
            return False
        if not self._session.can_send_order():
            logger.warning(f"[{symbol}] 非交易时间, 拒绝开多")
            return False

        order_id = self.risk_manager.buy(symbol, price, volume)
        if not order_id:
            return False

        self._track_order(order_id, "open_long", symbol, price, volume)
        if getattr(self.config, 'cancel_monitor_enabled', True):
            self.risk_manager.record_order(symbol, volume)
        logger.info(f"开多 {symbol}: {volume}手 @ {price}, 订单={order_id}")
        return True

    def open_short(self, date: datetime, symbol: str, price: float,
                   volume: int, contract: str = "") -> bool:
        """开空仓"""
        if volume <= 0:
            return False
        if not self._session.can_send_order():
            logger.warning(f"[{symbol}] 非交易时间, 拒绝开空")
            return False

        passed, msg = self.risk_manager.check_before_order(symbol, price, volume)
        if not passed:
            logger.warning(f"[{symbol}] 风控拒绝开空: {msg}")
            return False

        order_id = self.order_manager.short(symbol, price, volume)
        self._track_order(order_id, "open_short", symbol, price, volume)
        if getattr(self.config, 'cancel_monitor_enabled', True):
            self.risk_manager.record_order(symbol, volume)
        logger.info(f"开空 {symbol}: {volume}手 @ {price}, 订单={order_id}")
        return True

    def close_long(self, date: datetime, symbol: str, price: float,
                   volume: int = None, is_today: bool = False,
                   contract: str = "", skip_risk_check: bool = False) -> bool:
        """平多仓"""
        # 查询当前多仓
        pos = self.position_manager.get_position(symbol)
        current_vol = pos.volume if pos else 0
        if current_vol <= 0:
            return False
        if volume is None or volume > current_vol:
            volume = current_vol

        if skip_risk_check:
            order_id = self.order_manager.sell(symbol, price, volume)
        else:
            order_id = self.risk_manager.sell(symbol, price, volume)
        if not order_id:
            return False

        self._track_order(order_id, "close_long", symbol, price, volume)
        if getattr(self.config, 'cancel_monitor_enabled', True):
            self.risk_manager.record_order(symbol, volume)
        logger.info(f"平多 {symbol}: {volume}手 @ {price}, 订单={order_id}")
        return True

    def close_short(self, date: datetime, symbol: str, price: float,
                    volume: int = None, is_today: bool = False,
                    contract: str = "", skip_risk_check: bool = False) -> bool:
        """平空仓"""
        pos = self.position_manager.get_position(symbol)
        current_vol = pos.volume if pos else 0
        if current_vol <= 0:
            return False
        if volume is None or volume > current_vol:
            volume = current_vol

        order_id = self.order_manager.cover(symbol, price, volume)
        self._track_order(order_id, "close_short", symbol, price, volume)
        if getattr(self.config, 'cancel_monitor_enabled', True):
            self.risk_manager.record_order(symbol, volume)
        logger.info(f"平空 {symbol}: {volume}手 @ {price}, 订单={order_id}")
        return True

    def get_position(self, symbol: str, contract: str = ""
                     ) -> Tuple[Optional[PositionState], Optional[PositionState]]:
        """
        获取多空持仓（与 FuturesBacktestEngine 返回类型一致）
        """
        from src.trade.gateway import OrderDirection as GWDir

        long_pd = self.position_manager.get_position(symbol, GWDir.BUY)
        short_pd = self.position_manager.get_position(symbol, GWDir.SHORT)

        long_state = None
        if long_pd and long_pd.volume > 0:
            long_state = PositionState(
                side=PositionSide.LONG,
                volume=long_pd.volume,
                avg_price=long_pd.price,
                frozen=long_pd.frozen,
            )

        short_state = None
        if short_pd and short_pd.volume > 0:
            short_state = PositionState(
                side=PositionSide.SHORT,
                volume=short_pd.volume,
                avg_price=short_pd.price,
                frozen=short_pd.frozen,
            )

        return long_state, short_state

    def get_available_capital(self) -> float:
        """获取可用资金"""
        account = self.position_manager.get_account()
        return account.available if account else self.config.initial_capital

    def get_total_equity(self, prices: Dict[str, float] = None) -> float:
        """
        获取总权益 = 余额 + 浮动盈亏（简化按市价计算）
        """
        account = self.position_manager.get_account()
        if not account:
            return self.config.initial_capital
        return account.balance

    # ────────────── 引擎生命周期 ──────────────

    def run(self, strategy: BaseFuturesStrategy, symbols: List[str]):
        """
        启动引擎

        流程:
        1. 连接网关
        2. 订阅行情
        3. 初始化 K线聚合器
        4. 调用 strategy.on_start()
        5. 恢复持久化状态
        6. 启动后台主循环
        """
        self.strategy = strategy
        self.symbols = symbols
        self.symbol = symbols[0] if symbols else ""

        # 连接网关
        self.state = EngineState.CONNECTING
        if not self.gateway.connect():
            self.state = EngineState.ERROR
            logger.error("网关连接失败")
            return

        # 订阅行情
        all_symbols = list(symbols)

        # OI 追踪额外订阅
        if self.oi_tracker:
            extra = self.oi_tracker.get_required_subscriptions(symbols)
            all_symbols.extend(extra)
            if extra:
                logger.info(f"OI 追踪额外订阅 {len(extra)} 个合约")

        self.gateway.subscribe(all_symbols)

        # 初始化 K线聚合器
        for sym in symbols:
            self._bar_aggregators[sym] = BarAggregator(sym, self._bar_interval)

        # 初始化策略（设置 engine 引用，与回测一致）
        strategy.engine = self
        strategy.symbol = self.symbol
        strategy.on_start()

        # 恢复状态
        self._restore_state()

        # 启动合约管理器
        self.contract_manager.start()

        # 启动后台主循环
        self._running = True
        self.state = EngineState.RUNNING
        self._main_thread = threading.Thread(target=self._main_loop, daemon=True)
        self._main_thread.start()

        logger.success(f"实盘引擎启动: 品种={symbols}, 策略={strategy.name}")

    def stop(self):
        """停止引擎"""
        self._running = False
        if self._main_thread:
            self._main_thread.join(timeout=10)
        self.contract_manager.stop()
        if self.oi_tracker:
            self.oi_tracker.disable()
        self._save_state()
        self.gateway.close()
        self.state = EngineState.STOPPED
        logger.info("实盘引擎已停止")

    def pause(self):
        """暂停策略执行（风控和订单监控继续）"""
        if self.state == EngineState.RUNNING:
            self.state = EngineState.PAUSED
            logger.info("实盘引擎暂停")

    def resume(self):
        """恢复策略执行"""
        if self.state == EngineState.PAUSED:
            self.state = EngineState.RUNNING
            logger.info("实盘引擎恢复运行")

    # ────────────── 主循环（后台线程） ──────────────

    def _main_loop(self):
        """
        后台主循环 (~10Hz)

        每轮:
        1. 检查交易时段
        2. 检查挂单超时 → 撤单重发
        3. 周期风控检查
        4. 非交易时段刷新未完成 K线
        5. 定时持久化（每30秒）
        """
        last_persist = time.time()

        while self._running:
            try:
                now = datetime.now()
                phase = self._session.update(now)

                if self.state == EngineState.RUNNING:
                    if self._session.is_trading_time():
                        self._check_pending_orders()
                    else:
                        self._flush_bars()

                # 连接状态监控
                self._check_connection_status()

                # 周期风控 + 合约检查 + OI 追踪
                if self.state != EngineState.STOPPED:
                    self._check_risk_periodic()
                    self.contract_manager.periodic_check()
                    self._check_rollover_alerts()
                    if self.oi_tracker:
                        self.oi_tracker.check()

                # 定时持久化
                if time.time() - last_persist > 30:
                    self._save_state()
                    last_persist = time.time()

                time.sleep(0.1)

            except Exception as e:
                logger.error(f"主循环异常: {e}")
                self.state = EngineState.ERROR
                time.sleep(1)

    # ────────────── 网关回调 ──────────────

    def _on_tick(self, tick: TickData):
        """Tick 回调 → K线聚合 + OI 追踪"""
        # OI 追踪（处理所有 tick，包括 OI 额外订阅的合约）
        if self.oi_tracker and self.state == EngineState.RUNNING:
            self.oi_tracker.on_tick(tick)

        # K线聚合（只处理用户交易合约的 tick）
        aggregator = self._bar_aggregators.get(tick.symbol)
        if not aggregator:
            return

        bar = aggregator.update_tick(tick)
        if bar and self.state == EngineState.RUNNING and self.strategy:
            bar_dict = {
                "date": bar.datetime,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            }
            try:
                self.strategy.on_bar(bar_dict)
            except Exception as e:
                logger.error(f"策略 on_bar 异常: {e}")

    def _on_order(self, order: OrderData):
        """订单状态回调 → 更新挂单跟踪"""
        for info in list(self._pending_orders.values()):
            if info.engine_order_id == order.order_id:
                if order.status == OrderStatus.ALL_TRADED:
                    info.status = "filled"
                    info.filled_volume = order.traded
                elif order.status in (OrderStatus.CANCELED,):
                    info.status = "canceled"
                    # 记录撤单事件用于报撤单监控
                    if getattr(self.config, 'cancel_monitor_enabled', True):
                        self.risk_manager.record_cancel(order.symbol, info.volume)
                elif order.status in (OrderStatus.REJECTED, OrderStatus.ERROR):
                    info.status = "failed"
                elif order.status == OrderStatus.PART_TRADED:
                    info.status = "partial"
                    info.filled_volume = order.traded
                break

    def _on_trade(self, trade: TradeData):
        """成交回调"""
        logger.info(f"成交: {trade.symbol} {trade.direction.value} {trade.volume}手 @ {trade.price}")

        if self.alerter:
            dir_label = {
                OrderDirection.BUY: "开多",
                OrderDirection.SELL: "平多",
                OrderDirection.SHORT: "开空",
                OrderDirection.COVER: "平空",
            }.get(trade.direction, trade.direction.value)
            self.alerter.send_trade(trade.symbol, dir_label, trade.volume, trade.price)

    def _on_error(self, msg: str):
        """网关错误回调"""
        logger.error(f"网关异常: {msg}")
        if self.alerter:
            self.alerter.send_system_error(f"网关异常: {msg}")

    # ────────────── 连接监控 ──────────────

    def _on_gateway_disconnected(self, reason_type: str, reason_code: int):
        """网关断开回调"""
        self.state = EngineState.ERROR
        self._reconnect_alerted = False
        logger.warning(f"网关断开: {reason_type}(reason={reason_code})")

        if self.alerter:
            self.alerter.send_system_error(
                f"网关断开: {reason_type}, 原因码={reason_code}, 启动自动重连..."
            )

    def _check_connection_status(self):
        """定期检查网关连接状态（在主循环中调用）"""
        now = datetime.now()
        if (now.timestamp() - self._last_connected_check) < 5:
            return
        self._last_connected_check = now.timestamp()

        if hasattr(self.gateway, '_reconnecting') and self.gateway._reconnecting:
            if not self._reconnect_alerted and time.time() % 30 < 1:
                self._reconnect_alerted = True
                attempts = getattr(self.gateway, '_reconnect_attempts', 0)
                logger.warning(f"网关重连中... (第{attempts}次尝试)")
            if self.state != EngineState.ERROR:
                self.state = EngineState.ERROR
        else:
            if self.state == EngineState.ERROR and not getattr(self.gateway, '_reconnecting', False):
                # 检查是否已经恢复正常
                if self.gateway.connected:
                    self.state = EngineState.RUNNING
                    logger.info("网关重连成功，引擎恢复运行")
                    self._reconnect_alerted = False

    # ────────────── 挂单管理 ──────────────

    def _track_order(self, order_id: str, direction: str,
                     symbol: str, price: float, volume: int):
        """记录新挂单"""
        if not order_id:
            return
        self._strategy_order_counter += 1
        soid = f"SO_{self._strategy_order_counter:06d}"
        self._pending_orders[soid] = PendingOrderInfo(
            engine_order_id=order_id,
            strategy_order_id=soid,
            symbol=symbol,
            direction=direction,
            price=price,
            volume=volume,
            timeout_seconds=self.config.order_timeout_seconds,
            max_retries=self.config.max_retries,
        )

    def _check_pending_orders(self):
        """
        检查所有挂单，处理超时撤单重发

        超时策略: 未成交或部分成交超时 → 撤单 → 调整价格重发
        最多重试 max_retries 次，超过则放弃
        """
        now = datetime.now()
        to_remove: List[str] = []

        for soid, info in list(self._pending_orders.items()):
            if info.status in ("filled", "canceled", "failed"):
                to_remove.append(soid)
                continue

            elapsed = (now - info.create_time).total_seconds()
            if elapsed < info.timeout_seconds:
                continue

            # 超时处理
            if info.retry_count >= info.max_retries:
                logger.warning(
                    f"[{info.symbol}] 订单超时已达最大重试次数({info.max_retries}), 放弃: {soid}"
                )
                self.order_manager.cancel(info.engine_order_id)
                info.status = "failed"
                to_remove.append(soid)
                continue

            # 撤单重发
            logger.info(
                f"[{info.symbol}] 订单超时({elapsed:.0f}s), 撤单重发 "
                f"({info.retry_count + 1}/{info.max_retries}): {soid}"
            )
            self.order_manager.cancel(info.engine_order_id)

            new_price = self._calc_replace_price(info)
            new_order_id = self._resubmit_order(info, new_price)

            if new_order_id:
                info.engine_order_id = new_order_id
                info.price = new_price
                info.retry_count += 1
                info.create_time = now
                info.status = "pending"
                logger.info(f"  重发成功: {new_order_id} @ {new_price}")
            else:
                info.status = "failed"
                to_remove.append(soid)

        for soid in to_remove:
            self._pending_orders.pop(soid, None)

    def _calc_replace_price(self, info: PendingOrderInfo) -> float:
        """计算重发价格（买方提高、卖方降低）"""
        slippage = self.config.slippage or 0.0001
        factor = 1 + slippage * (info.retry_count + 1)
        if info.direction in ("open_long", "close_short"):
            return round(info.price * factor, 2)
        else:
            return round(info.price * (2 - factor), 2)

    def _resubmit_order(self, info: PendingOrderInfo, new_price: float) -> Optional[str]:
        """按方向重新提交订单"""
        try:
            if info.direction == "open_long":
                return self.risk_manager.buy(info.symbol, new_price, info.volume)
            elif info.direction == "close_long":
                return self.risk_manager.sell(info.symbol, new_price, info.volume)
            elif info.direction == "open_short":
                return self.order_manager.short(info.symbol, new_price, info.volume)
            elif info.direction == "close_short":
                return self.order_manager.cover(info.symbol, new_price, info.volume)
        except Exception as e:
            logger.error(f"重发订单异常: {e}")
        return None

    # ────────────── OI 主力合约变更回调 ──────────────

    def _on_oi_main_changed(self, base: str, old_contract: str, new_contract: str):
        """OI 追踪检测到主力变更时回调"""
        changed = self.contract_manager.update_main_contract(
            base, new_contract,
            open_interest_ratio=0.0,
            detected_method="open_interest",
        )
        if changed:
            self.contract_manager.detect_rollover(base, new_contract)
            logger.info(f"[{base}] OI 检测换月: {old_contract} → {new_contract}")
            if self.alerter:
                self.alerter.send_rollover(base, old_contract, new_contract)

    # ────────────── 换月通知 ──────────────

    _notified_rollovers: set = set()

    def _check_rollover_alerts(self):
        """检查是否有新完成的换月移仓，推送通知"""
        if not self.alerter:
            return
        for record in self.contract_manager.list_rollovers():
            key = f"{record.old_contract}->{record.new_contract}"
            if key not in self._notified_rollovers and record.action == RolloverAction.COMPLETED:
                self._notified_rollovers.add(key)
                self.alerter.send_rollover(record.base, record.old_contract, record.new_contract)

    # ────────────── 风控 ──────────────

    def _check_risk_periodic(self):
        """周期风控检查"""
        alerts = self.risk_manager.check_positions()
        for alert in alerts:
            logger.warning(f"风控告警: {alert['rule']} {alert['symbol']} {alert['message']}")

        # 推送到钉钉
        if self.alerter:
            for alert in alerts:
                rule = alert.get("rule", "")
                msg = alert.get("message", "")
                symbol = alert.get("symbol", "")
                level = alert.get("level", "warning")

                if "止损" in rule or "止损" in msg:
                    self.alerter.send_stop_loss(symbol, "", 0.0, 0.0, 0.0)
                elif "强平" in rule or "强平" in msg or level == "critical":
                    margin_status = self.risk_manager.get_margin_status()
                    self.alerter.send_liquidation_warning(
                        margin_status["risk_ratio"],
                        margin_status["total_equity"],
                        margin_status["total_margin"],
                    )
                elif "保证金" in rule or "风险度" in rule:
                    margin_status = self.risk_manager.get_margin_status()
                    self.alerter.send_margin_warning(
                        margin_status["total_equity"],
                        margin_status["total_margin"],
                        margin_status["risk_ratio"],
                    )
                elif "报撤" in rule or "报撤单" in rule or "大额" in msg:
                    if "大额" in msg and symbol:
                        self.alerter.send_cancel_warning(
                            large_cancel={"symbol": symbol, "volume": 0, "hold_seconds": 0},
                        )
                    elif "报撤比" in msg:
                        self.alerter.send_cancel_warning(
                            cancel_count=0, window_minutes=5,
                            cancel_ratio=0.5,
                        )
                    else:
                        self.alerter.send_cancel_warning(cancel_count=0, window_minutes=1)

        # 自动减仓执行
        if not self.config.auto_reduce_enabled:
            return

        actions = self.risk_manager.plan_auto_reduce()
        for action in actions:
            if action.reduce_volume <= 0:
                continue
            if action.direction == "long":
                self.close_long(
                    datetime.now(), action.symbol, 0, action.reduce_volume,
                    skip_risk_check=True,
                )
            elif action.direction == "short":
                self.close_short(
                    datetime.now(), action.symbol, 0, action.reduce_volume,
                    skip_risk_check=True,
                )
            logger.warning(
                f"自动减仓: {action.symbol} {action.direction} "
                f"减{action.reduce_volume}/{action.current_volume}手 "
                f"类型={action.reduce_type}"
            )
            if self.alerter:
                self.alerter.send_auto_reduce(
                    symbol=action.symbol,
                    direction=action.direction,
                    reduce_volume=action.reduce_volume,
                    current_volume=action.current_volume,
                    reduce_type=action.reduce_type,
                )

    # ────────────── K线刷新 ──────────────

    def _flush_bars(self):
        """非交易时段刷新未完成 K线"""
        if not self.strategy:
            return
        for symbol, aggregator in self._bar_aggregators.items():
            bar = aggregator.force_finish()
            if bar:
                bar_dict = {
                    "date": bar.datetime,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                }
                try:
                    self.strategy.on_bar(bar_dict)
                except Exception as e:
                    logger.error(f"策略 on_bar(flush) 异常: {e}")

    # ────────────── 状态持久化 ──────────────

    def _save_state(self):
        """保存引擎状态到磁盘"""
        now = datetime.now()
        state = {
            "timestamp": now.isoformat(),
            "trading_day": now.strftime("%Y-%m-%d"),
            "state": self.state.name,
            "positions": self._serialize_positions(),
            "pending_orders": self._serialize_pending_orders(),
            "account": self._serialize_account(),
        }
        state_file = self._state_dir / f"live_state_{now.strftime('%Y%m%d')}.json"
        try:
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False, default=str)
        except Exception as e:
            logger.error(f"状态持久化失败: {e}")

    def _restore_state(self):
        """从最近的状态文件恢复"""
        state_file = self._state_dir / f"live_state_{datetime.now().strftime('%Y%m%d')}.json"
        if not state_file.exists():
            logger.info("无历史状态需要恢复")
            return
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state = json.load(f)
            logger.info(f"状态恢复完成: {state_file.name} (state={state.get('state')})")
        except Exception as e:
            logger.error(f"状态恢复失败: {e}")

    def _serialize_positions(self) -> list:
        """序列化持仓"""
        return [
            {
                "symbol": p.symbol,
                "direction": p.direction.value,
                "volume": p.volume,
                "frozen": p.frozen,
                "price": p.price,
                "pnl": p.pnl,
            }
            for p in self.position_manager.get_all_positions()
        ]

    def _serialize_pending_orders(self) -> list:
        """序列化挂单"""
        return [
            {
                "strategy_order_id": info.strategy_order_id,
                "engine_order_id": info.engine_order_id,
                "symbol": info.symbol,
                "direction": info.direction,
                "price": info.price,
                "volume": info.volume,
                "filled_volume": info.filled_volume,
                "status": info.status,
                "retry_count": info.retry_count,
                "create_time": info.create_time.isoformat(),
            }
            for info in self._pending_orders.values()
        ]

    def _serialize_account(self) -> dict:
        """序列化账户"""
        account = self.position_manager.get_account()
        if account:
            return {
                "balance": account.balance,
                "available": account.available,
                "margin": account.margin,
                "pnl": account.pnl,
            }
        return {}
