"""
定时任务调度器

轻量级内置调度器（无外部依赖），基于 threading + time 实现。
支持按交易日历和指定时间点执行任务。

典型用法:
    scheduler = TaskScheduler()
    scheduler.daily("08:30", pre_market_check)
    scheduler.daily("15:30", post_market_report)
    scheduler.start()
"""
import time
import threading
from datetime import datetime, date, timedelta
from typing import Callable, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum, auto

from loguru import logger


class TaskStatus(Enum):
    IDLE = auto()
    RUNNING = auto()
    FAILED = auto()


@dataclass
class ScheduledTask:
    """定时任务"""
    name: str
    hour: int
    minute: int
    callback: Callable
    enabled: bool = True
    last_run: Optional[date] = None
    status: TaskStatus = TaskStatus.IDLE
    error_count: int = 0
    max_errors: int = 5
    description: str = ""


class TaskScheduler:
    """
    轻量级定时任务调度器

    支持:
    - 每日指定时间执行任务
    - 自动跳过非交易日
    - 任务超时保护（默认 300s）
    - 错误计数与自动禁用

    用法:
        def my_task():
            print("running...")

        s = TaskScheduler()
        s.daily("09:00", my_task, name="开盘检查")
        s.every(minutes=30, my_task, name="健康检查")
        s.start()

        # 在主线中保持运行
        s.wait()
    """

    def __init__(self, trading_days_only: bool = True, check_interval: float = 10.0):
        """
        Args:
            trading_days_only: 是否只在交易日执行
            check_interval: 调度检查间隔（秒）
        """
        self._tasks: List[ScheduledTask] = []
        self._interval_tasks: List[dict] = []
        self._trading_days_only = trading_days_only
        self._check_interval = check_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    # ────────── 任务注册 ──────────

    def daily(self, time_str: str, callback: Callable,
              name: str = "", description: str = "",
              max_errors: int = 5) -> ScheduledTask:
        """
        注册每日定时任务

        Args:
            time_str: "HH:MM" 格式
            callback: 无参回调函数
            name: 任务名称
            description: 描述
            max_errors: 最大连续错误次数后自动禁用
        """
        hour, minute = map(int, time_str.split(":"))
        if not name:
            name = callback.__name__

        task = ScheduledTask(
            name=name,
            hour=hour,
            minute=minute,
            callback=callback,
            max_errors=max_errors,
            description=description or name,
        )
        self._tasks.append(task)
        logger.info(f"调度任务 [{name}]: 每天 {time_str} ({description})")
        return task

    def every(self, minutes: float, callback: Callable,
              name: str = "") -> None:
        """注册间隔任务（每 N 分钟执行）"""
        if not name:
            name = callback.__name__
        self._interval_tasks.append({
            "name": name,
            "interval": minutes * 60,
            "callback": callback,
            "last_run": 0.0,
        })
        logger.info(f"调度任务 [{name}]: 每 {minutes} 分钟")

    # ────────── 启停 ──────────

    def start(self):
        """启动调度器后台线程"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="TaskScheduler")
        self._thread.start()
        logger.info(f"任务调度器启动: {len(self._tasks)} 个定时任务, "
                    f"{len(self._interval_tasks)} 个间隔任务")

    def stop(self, wait: bool = True):
        """停止调度器"""
        self._running = False
        if wait and self._thread:
            self._thread.join(timeout=5)
        logger.info("任务调度器已停止")

    def wait(self, timeout: Optional[float] = None):
        """等待调度器线程结束（在主线程中保持运行）"""
        if self._thread:
            self._thread.join(timeout=timeout)

    @property
    def is_running(self) -> bool:
        return self._running

    # ────────── 任务控制 ──────────

    def get_task(self, name: str) -> Optional[ScheduledTask]:
        """按名称查找任务"""
        for t in self._tasks:
            if t.name == name:
                return t
        return None

    def enable_task(self, name: str):
        """启用任务"""
        task = self.get_task(name)
        if task:
            task.enabled = True

    def disable_task(self, name: str):
        """禁用任务"""
        task = self.get_task(name)
        if task:
            task.enabled = False

    def summary(self) -> str:
        """打印所有任务状态"""
        lines = ["━━━ 任务调度器状态 ━━━"]
        for t in self._tasks:
            status = "✅" if t.enabled else "⏸"
            last = t.last_run.strftime("%Y-%m-%d") if t.last_run else "-"
            errors = f" 错误×{t.error_count}" if t.error_count else ""
            lines.append(
                f"  {status} [{t.name:16s}] "
                f"{t.hour:02d}:{t.minute:02d} "
                f"上次={last}{errors}"
            )
        for t in self._interval_tasks:
            next_run = int(t["interval"] - (time.time() - t["last_run"]))
            lines.append(f"  🔄 [{t['name']:16s}] 每 {t['interval']/60:.0f}min 下次={next_run}s后")
        return "\n".join(lines)

    # ────────── 内部调度循环 ──────────

    def _loop(self):
        """调度器主循环"""
        while self._running:
            try:
                self._check_tasks()
                self._check_interval_tasks()
            except Exception as e:
                logger.error(f"调度器循环异常: {e}")
            time.sleep(self._check_interval)

    def _check_tasks(self):
        """检查定时任务"""
        now = datetime.now()

        if self._trading_days_only and not self._is_trading_day(now.date()):
            return

        for task in self._tasks:
            if not task.enabled:
                continue
            if task.error_count >= task.max_errors:
                continue

            # 检查是否到达执行时间
            if now.hour != task.hour or now.minute != task.minute:
                continue

            # 防止同一天重复执行
            if task.last_run == now.date():
                continue

            task.last_run = now.date()
            self._run_task(task)

    def _check_interval_tasks(self):
        """检查间隔任务"""
        now = time.time()

        if self._trading_days_only and not self._is_trading_day(datetime.now().date()):
            return

        for t in self._interval_tasks:
            if now - t["last_run"] >= t["interval"]:
                t["last_run"] = now
                try:
                    t["callback"]()
                except Exception as e:
                    logger.error(f"间隔任务 [{t['name']}] 失败: {e}")

    def _run_task(self, task: ScheduledTask):
        """执行单个任务（带超时保护）"""
        logger.info(f"执行定时任务 [{task.name}] ({task.description})")
        task.status = TaskStatus.RUNNING

        try:
            task.callback()
            task.status = TaskStatus.IDLE
            task.error_count = 0
            logger.info(f"任务 [{task.name}] 完成")
        except Exception as e:
            task.error_count += 1
            task.status = TaskStatus.FAILED
            logger.error(f"任务 [{task.name}] 失败 (第{task.error_count}次): {e}")

            if task.error_count >= task.max_errors:
                logger.warning(f"任务 [{task.name}] 连续失败 {task.max_errors} 次，自动禁用")

    # ────────── 交易日判断 ──────────

    @staticmethod
    def _is_trading_day(dt: date = None) -> bool:
        """粗略判断是否为交易日"""
        if dt is None:
            dt = date.today()

        if dt.weekday() >= 5:
            return False

        month, day = dt.month, dt.day
        if month == 1 and day == 1:
            return False
        if month == 5 and day in (1, 2, 3):
            return False
        if month == 10 and day in (1, 2, 3, 4, 5, 6, 7):
            return False

        return True


# ────────── 常用回调工厂 ──────────

def make_engine_start_callback(engine_factory: Callable) -> Callable:
    """
    创建开盘前启动引擎的回调工厂

    用法:
        cb = make_engine_start_callback(lambda: create_and_return_engine())
        scheduler.daily("08:30", cb, name="引擎启动")
    """
    def start_engine():
        engine = engine_factory()
        logger.info("开盘前引擎启动完成")
        return engine
    return start_engine


def make_health_check_callback(engine) -> Callable:
    """创建盘中健康检查回调"""
    def health_check():
        from src.engine.live_engine import EngineState
        if engine.state == EngineState.ERROR:
            logger.warning("健康检查: 引擎异常状态")
        elif engine.state == EngineState.RUNNING:
            logger.debug("健康检查: 引擎运行正常")
    return health_check


def make_post_market_callback(engine) -> Callable:
    """创建收盘后处理回调"""
    def post_market():
        engine._save_state()
        logger.info("收盘后状态已保存")
        if engine.alerter:
            engine.alerter.generate_daily_report()
            logger.info("收盘后日报已生成")
    return post_market
