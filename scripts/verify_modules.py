"""验证所有模块导入"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print(f"架构: {sys.maxsize.bit_length()+1}位")
print(f"版本: {sys.version.split()[0]}")

from src.core.logger import setup_logger, get_logger
from src.core.config import Config
from src.data.collector import DataCollector
from src.data.indicators import TechnicalIndicators
from src.strategy.base import BaseStrategy, Signal
from src.strategy.trend_strategy import SmaCrossStrategy, MACDStrategy
from src.backtest.engine import BacktestEngine
from src.trade.gateway import BaseGateway, OrderData, OrderDirection
from src.trade.ctp_gateway import CtpGateway
from src.trade.order_manager import OrderManager
from src.trade.position_manager import PositionManager
from src.trade.risk_manager import RiskManager

print("全部模块导入成功!")
print(f"共 {len(sys.modules)} 个模块加载")

