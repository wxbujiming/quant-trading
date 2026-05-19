"""
配置管理模块
支持YAML配置文件加载和环境变量覆盖
"""
from pathlib import Path
from typing import Any, Dict, Optional
from dataclasses import dataclass, field
import os

try:
    import yaml
except ImportError:
    yaml = None  # PyYAML 可选，仅 secrets.yaml 加载需要


@dataclass
class DataConfig:
    """数据配置"""
    source: str = "akshare"
    cache_dir: str = "./data/cache"
    raw_dir: str = "./data/raw"
    processed_dir: str = "./data/processed"
    default_start_date: str = "20200101"
    default_end_date: str = "20241231"


@dataclass
class BacktestConfig:
    """回测配置"""
    initial_cash: float = 100000.0
    commission: float = 0.0003  # 万三
    slippage: float = 0.0001    # 万一
    stamp_duty: float = 0.001   # 千一印花税


@dataclass
class LoggingConfig:
    """日志配置"""
    level: str = "DEBUG"
    format: str = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
    file: str = "./logs/app.log"
    rotation: str = "10 MB"
    retention: str = "7 days"


@dataclass
class StrategyConfig:
    """策略配置"""
    stop_loss: float = 0.05
    take_profit: float = 0.10
    max_position: float = 0.2


@dataclass
class AIConfig:
    """AI配置"""
    model_dir: str = "./models"
    train_test_split: float = 0.8
    random_state: int = 42


@dataclass
class NotifyConfig:
    """通知配置"""
    enabled: bool = False
    webhook_url: str = ""

    # 钉钉机器人
    dingtalk_webhook: str = ""
    dingtalk_secret: str = ""

    notify_on_error: bool = True
    notify_on_success: bool = False


@dataclass
class ScheduleConfig:
    """定时任务配置"""
    enabled: bool = True
    run_time: str = "16:00"         # 每日运行时间（收盘后）
    collect_symbols: list = None    # 要采集的股票列表, None=全部已缓存股票
    max_workers: int = 3            # 并发采集数
    incremental: bool = True        # 增量更新（只获取最新数据）


@dataclass
class LiveConfig:
    """实盘引擎配置"""
    # 网关
    gateway_name: str = "SimNow"
    broker_id: str = "9999"
    user_id: str = ""
    password: str = ""
    app_id: str = "simnow_client_test"
    auth_code: str = "0000000000000000"
    environment: str = "simnow"           # simnow / simnow_7x24

    # 资金
    initial_capital: float = 1000000.0

    # 品种参数（与 FuturesBacktestEngine 保持一致）
    contract_multiplier: int = 10
    margin_rate: float = 0.10
    commission_open: float = 0.0001
    commission_close: float = 0.0001
    commission_close_today: Optional[float] = None
    slippage: float = 0.0001

    # K线聚合
    bar_interval_minutes: int = 1

    # 订单超时
    order_timeout_seconds: int = 30
    max_retries: int = 3

    # 断线重连
    reconnect_enabled: bool = True
    reconnect_initial_delay: float = 1.0       # 初始重连延迟（秒）
    reconnect_max_delay: float = 30.0          # 最大重连延迟
    reconnect_max_attempts: int = 0            # 最大重试次数，0=无限

    # 状态持久化
    state_dir: str = "./data/live_state"

    # CTP 真实接口
    real_mode: bool = False
    td_address: str = ""
    md_address: str = ""

    # 策略
    symbols: list = None             # 品种列表
    strategy_name: str = "DualMaCrossStrategy"
    strategy_params: dict = None

    # OI 主力合约追踪
    oi_tracker_enabled: bool = True
    oi_threshold_ratio: float = 0.20         # OI 领先 20% 触发
    oi_confirmation_count: int = 5           # 确认次数
    oi_check_interval_seconds: int = 10      # 检测间隔
    oi_snapshot_interval_seconds: int = 60   # 快照记录间隔
    oi_min_oi_absolute: int = 100            # 最小 OI 绝对值
    oi_old_leader_suppress_minutes: int = 60 # 旧主力抑制期
    oi_subscription_count: int = 6           # 每品种跟踪合约数

    # 自动减仓预案
    auto_reduce_enabled: bool = True
    auto_reduce_trigger_ratio: float = 0.95    # 风险度 > 95% 触发减仓
    auto_reduce_target_ratio: float = 0.70     # 减仓目标风险度
    flat_all_trigger_ratio: float = 1.00       # 风险度 >= 100% 全部平仓

    # 大额报撤单监控
    cancel_monitor_enabled: bool = True
    max_cancels_per_minute: int = 5            # 每分钟最大撤单数
    max_cancel_ratio: float = 0.30             # 报撤比阈值（撤单/报单）
    cancel_ratio_window_minutes: int = 5       # 报撤比统计时间窗口（分钟）
    large_order_volume: int = 100              # 大额定单手数阈值


@dataclass
class Config:
    """主配置类"""
    project: Dict[str, Any] = field(default_factory=lambda: {
        "name": "AI量化交易平台",
        "version": "0.1.0",
        "debug": True
    })
    data: DataConfig = field(default_factory=DataConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    live: LiveConfig = field(default_factory=LiveConfig)
    
    @classmethod
    def load(cls, secrets_path: str = "./config/secrets.yaml") -> "Config":
        """加载配置（优先从环境变量或配置文件）"""
        config = cls()

        # 从环境变量加载（如果存在）
        data_raw = os.getenv("DATA_RAW_DIR", config.data.raw_dir)
        config.data.raw_dir = data_raw

        # 从 secrets.yaml 加载（如果存在） — 主要是钉钉和券商密钥
        secrets_file = Path(secrets_path)
        if secrets_file.exists() and yaml:
            try:
                with open(secrets_file, "r", encoding="utf-8") as f:
                    secrets = yaml.safe_load(f) or {}

                # 钉钉机器人
                dingtalk = secrets.get("dingtalk", {})
                if dingtalk.get("webhook"):
                    config.notify.dingtalk_webhook = dingtalk["webhook"]
                if dingtalk.get("secret"):
                    config.notify.dingtalk_secret = dingtalk["secret"]

                # CTP 交易凭据
                ctp = secrets.get("ctp", {})
                if ctp.get("userid"):
                    config.live.user_id = ctp["userid"]
                if ctp.get("password"):
                    config.live.password = ctp["password"]
                if ctp.get("brokerid"):
                    config.live.broker_id = ctp["brokerid"]
                if ctp.get("app_id"):
                    config.live.app_id = ctp["app_id"]
                if ctp.get("auth_code"):
                    config.live.auth_code = ctp["auth_code"]
                if ctp.get("td_address"):
                    config.live.td_address = ctp["td_address"]
                if ctp.get("md_address"):
                    config.live.md_address = ctp["md_address"]

            except Exception as e:
                import logging
                logging.warning(f"加载 secrets.yaml 失败: {e}")

        return config


# 全局配置实例
_config: Optional[Config] = None


def get_config() -> Config:
    """获取全局配置实例"""
    global _config
    if _config is None:
        _config = Config.load()
    return _config


def reload_config() -> Config:
    """重新加载配置"""
    global _config
    _config = Config.load()
    return _config

