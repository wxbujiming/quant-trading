"""
配置管理模块
支持YAML配置文件加载和环境变量覆盖
"""
from pathlib import Path
from typing import Any, Dict, Optional
from dataclasses import dataclass, field
import os


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

    # 状态持久化
    state_dir: str = "./data/live_state"

    # CTP 真实接口
    real_mode: bool = False
    td_address: str = "tcp://182.254.243.31:30001"
    md_address: str = "tcp://182.254.243.31:30011"

    # 策略
    symbols: list = None             # 品种列表
    strategy_name: str = "DualMaCrossStrategy"
    strategy_params: dict = None


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
    def load(cls) -> "Config":
        """加载配置（优先从环境变量或配置文件）"""
        config = cls()
        
        # 从环境变量加载（如果存在）
        data_raw = os.getenv("DATA_RAW_DIR", config.data.raw_dir)
        config.data.raw_dir = data_raw
        
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

