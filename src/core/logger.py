"""
日志系统
使用loguru实现结构化日志
"""
import sys
from pathlib import Path
from loguru import logger


def setup_logger(
    level: str = "DEBUG",
    log_file: str = "./logs/app.log",
    rotation: str = "10 MB",
    retention: str = "7 days"
):
    """
    初始化日志系统
    
    Args:
        level: 日志级别
        log_file: 日志文件路径
        rotation: 日志轮转大小
        retention: 日志保留时间
    """
    # 移除默认handler
    logger.remove()
    
    # 控制台输出 - 带颜色
    logger.add(
        sys.stdout,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
               "<level>{message}</level>",
        colorize=True,
    )
    
    # 文件输出
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    logger.add(
        log_file,
        level=level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation=rotation,
        retention=retention,
        compression="zip",
        encoding="utf-8",
    )
    
    logger.info("日志系统初始化完成")
    return logger


def get_logger():
    """获取logger实例"""
    return logger
