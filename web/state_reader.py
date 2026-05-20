"""
统一状态读取接口。

提供两种数据源模式：
1. Live 模式：从运行中的 LiveEngine 直接读取
2. Snapshot 模式：从 data/live_state/ 的 JSON 快照文件读取

自动降级：优先尝试 Live 模式，失败则回退到 Snapshot 模式。
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQLite 数据库读取器（跨进程读取替代 JSON 快照）
# ---------------------------------------------------------------------------
_DB_READER = None


def _get_db_reader():
    global _DB_READER
    if _DB_READER is None:
        try:
            from src.storage.database import TradeDatabase
            _DB_READER = TradeDatabase()
        except Exception:
            _DB_READER = False  # 标记不可用
    return _DB_READER if _DB_READER else None


# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "live_state"
LOG_DIR = PROJECT_ROOT / "logs"
EQUITY_HISTORY_CSV = STATE_DIR / "equity_history.csv"
COMMANDS_FILE = STATE_DIR / "commands.json"

# ---------------------------------------------------------------------------
# 中文映射表
# ---------------------------------------------------------------------------
ENGINE_STATE_CN = {
    "IDLE": "空闲",
    "CONNECTING": "连接中",
    "RUNNING": "运行中",
    "PAUSED": "已暂停",
    "STOPPED": "已停止",
    "ERROR": "错误",
    "UNKNOWN": "未知",
}

SESSION_PHASE_CN = {
    "PRE_OPEN": "开盘前",
    "CONTINUOUS": "连续交易",
    "BREAK": "休市中",
    "CLOSED": "已收盘",
    "N/A": "未知",
}

RISK_LEVEL_CN = {
    "normal": "正常",
    "warning": "警告",
    "danger": "危险",
    "liquidation": "强平",
}


def cn_state(en: str) -> str:
    """引擎状态 英→中"""
    return ENGINE_STATE_CN.get(en, en)


def cn_phase(en: str) -> str:
    """交易阶段 英→中"""
    return SESSION_PHASE_CN.get(en, en)


def cn_risk_level(en: str) -> str:
    """风险等级 英→中"""
    return RISK_LEVEL_CN.get(en, en)


# ---------------------------------------------------------------------------
# 引擎引用（惰性加载）
# ---------------------------------------------------------------------------
_engine = None
_engine_loaded = False
_has_engine = False


def _load_engine():
    """尝试加载 LiveEngine 模块（惰性加载，不阻塞启动）。"""
    global _engine, _engine_loaded, _has_engine
    if _engine_loaded:
        return _has_engine
    _engine_loaded = True

    # 将项目根目录加入 sys.path（如果尚未在）
    root_str = str(PROJECT_ROOT)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    try:
        from src.engine.live_engine import LiveEngine
        # 查找全局引擎实例 —— 如果引擎在同一个进程中运行，
        # 通常会被赋值给模块级变量或可通过某种单例访问。
        # 这里我们尝试 import src.engine 并查找实例。
        import importlib

        engine_mod = importlib.import_module("src.engine")
        for attr_name in dir(engine_mod):
            attr = getattr(engine_mod, attr_name)
            if isinstance(attr, LiveEngine):
                _engine = attr
                _has_engine = True
                logger.info("state_reader: 发现运行中的 LiveEngine 实例: %s", attr_name)
                return True

        # 如果没有现成实例，尝试从引擎模块全局搜索
        import src.engine.live_engine as le_mod
        for attr_name in dir(le_mod):
            attr = getattr(le_mod, attr_name)
            if isinstance(attr, LiveEngine):
                _engine = attr
                _has_engine = True
                logger.info("state_reader: 发现 LiveEngine 实例: %s", attr_name)
                return True

        logger.info("state_reader: 未找到运行中的 LiveEngine 实例")
        return False
    except Exception as exc:
        logger.debug("state_reader: 加载引擎失败: %s", exc)
        return False


def _get_engine():
    """返回缓存的引擎引用（如果可用）。"""
    if _load_engine():
        return _engine
    return None


# ---------------------------------------------------------------------------
# 快照文件读取
# ---------------------------------------------------------------------------
def _get_latest_state_file() -> Optional[Path]:
    """返回最新的 live_state_YYYYMMDD.json 文件路径。"""
    if not STATE_DIR.exists():
        return None
    files = sorted(STATE_DIR.glob("live_state_*.json"), reverse=True)
    return files[0] if files else None


def _read_state_snapshot() -> Optional[dict]:
    """读取最新的 JSON 状态快照。"""
    path = _get_latest_state_file()
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("state_reader: 读取快照 %s 失败: %s", path, exc)
        return None


def _get_snapshot_mtime() -> Optional[str]:
    """获取快照文件的修改时间（ISO 格式）。"""
    path = _get_latest_state_file()
    if not path:
        return None
    try:
        mtime = path.stat().st_mtime
        return datetime.fromtimestamp(mtime).isoformat(sep=" ", timespec="seconds")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------
def has_engine() -> bool:
    """引擎是否在同一个进程中运行且可用。"""
    return _load_engine() and _engine is not None


def is_engine_recent(max_age: int = 60) -> bool:
    """检测引擎是否在运行（跨进程）。

    通过检查状态文件最近是否更新来判断引擎是否在另一个进程中运行。

    Args:
        max_age: 状态文件最大允许延迟（秒），默认 60

    Returns:
        bool
    """
    path = _get_latest_state_file()
    if not path:
        return False
    try:
        age = time.time() - path.stat().st_mtime
        return age < max_age
    except Exception:
        return False


def get_engine_state() -> dict:
    """获取引擎运行状态。

    Returns:
        dict: {state, connected, logined, trading_day, mode, phase, uptime}
    """
    engine = _get_engine()
    if engine:
        try:
            from src.engine.live_engine import EngineState
            phase_str = "N/A"
            if hasattr(engine, "_session") and engine._session:
                phase_str = engine._session.phase.name if hasattr(
                    engine._session, "phase") else str(type(engine._session.phase).__name__)

            return {
                "source": "live",
                "state": engine.state.name if isinstance(engine.state, EngineState) else str(engine.state),
                "connected": getattr(engine.gateway, "connected", False) if engine.gateway else False,
                "logined": getattr(engine.gateway, "logined", False) if engine.gateway else False,
                "trading_day": getattr(engine, "_trading_day", str(date.today())),
                "mode": getattr(engine, "_mode", "simulated"),
                "phase": phase_str,
                "running": getattr(engine, "_running", False),
            }
        except Exception as exc:
            logger.warning("state_reader: 读取引擎状态异常: %s", exc)

    # 回退到快照
    snap = _read_state_snapshot()
    if snap:
        # 优先用 JSON 内时间戳（引擎写入的），回退到文件修改时间
        snap_time = snap.get("timestamp")
        if snap_time and len(snap_time) > 19:
            snap_time = snap_time[:19]
        elif not snap_time:
            snap_time = _get_snapshot_mtime()
        return {
            "source": "snapshot",
            "state": snap.get("state", "UNKNOWN"),
            "connected": False,
            "logined": False,
            "trading_day": snap.get("trading_day", ""),
            "mode": snap.get("mode", "snapshot"),
            "phase": "N/A",
            "running": False,
            "snap_time": snap_time,
        }
    return {"source": "none", "state": "IDLE", "connected": False, "logined": False,
            "trading_day": str(date.today()), "mode": "unknown", "phase": "N/A",
            "running": False, "snap_time": None}


def get_account_summary() -> dict:
    """获取账户摘要。

    Returns:
        dict: {total_cash, total_balance, total_market_value, total_volume,
               total_pnl, position_count, position_ratio}
    """
    engine = _get_engine()
    if engine and engine.position_manager:
        try:
            summary = engine.position_manager.get_summary()
            summary["source"] = "live"
            return summary
        except Exception as exc:
            logger.warning("state_reader: 读取账户摘要异常: %s", exc)

    snap = _read_state_snapshot()
    if snap and "account" in snap:
        acct = snap["account"]
        positions = snap.get("positions", [])
        total_pnl = sum(p.get("pnl", 0.0) for p in positions)
        total_volume = sum(p.get("volume", 0) for p in positions)
        total_mv = sum(p.get("volume", 0) * p.get("price", 0.0) for p in positions)
        balance = acct.get("balance", 0.0)
        return {
            "source": "snapshot",
            "total_cash": acct.get("available", 0.0),
            "total_balance": balance,
            "total_market_value": total_mv,
            "total_volume": total_volume,
            "total_pnl": total_pnl,
            "position_count": len(positions),
            "position_ratio": (total_mv / balance * 100) if balance > 0 else 0.0,
        }
    return {"source": "none", "total_cash": 0, "total_balance": 0, "total_market_value": 0,
            "total_volume": 0, "total_pnl": 0, "position_count": 0, "position_ratio": 0}


def get_all_positions() -> list:
    """获取所有持仓列表。

    Returns:
        list[dict]: 每个持仓包含 {symbol, direction, volume, frozen, available, price, pnl, exchange}
    """
    engine = _get_engine()
    if engine and engine.position_manager:
        try:
            positions = engine.position_manager.get_all_positions()
            result = []
            for pos in positions:
                result.append({
                    "symbol": pos.symbol,
                    "direction": pos.direction.value if hasattr(pos.direction, "value") else str(pos.direction),
                    "volume": pos.volume,
                    "frozen": pos.frozen,
                    "available": pos.volume - pos.frozen,
                    "price": pos.price,
                    "pnl": pos.pnl,
                    "exchange": pos.exchange,
                })
            return result
        except Exception as exc:
            logger.warning("state_reader: 读取持仓异常: %s", exc)

    snap = _read_state_snapshot()
    if snap:
        return snap.get("positions", [])
    return []


def get_orders(status: Optional[str] = None) -> list:
    """获取订单列表。

    Args:
        status: 可选过滤状态，如 "active" 或具体的 OrderStatus

    Returns:
        list[dict]: 订单列表
    """
    engine = _get_engine()
    if engine and engine.order_manager:
        try:
            from src.trade.gateway import OrderStatus
            if status == "active":
                orders = engine.order_manager.get_active_orders()
            elif status and hasattr(OrderStatus, status.upper()):
                s = getattr(OrderStatus, status.upper())
                orders = engine.order_manager.get_orders(status=s)
            else:
                orders = engine.order_manager.get_orders()

            result = []
            for o in orders:
                result.append({
                    "order_id": o.order_id,
                    "symbol": o.symbol,
                    "direction": o.direction.value if hasattr(o.direction, "value") else str(o.direction),
                    "offset": o.offset,
                    "price": o.price,
                    "volume": o.volume,
                    "traded": o.traded,
                    "status": o.status.value if hasattr(o.status, "value") else str(o.status),
                    "create_time": str(o.create_time) if o.create_time else "",
                    "update_time": str(o.update_time) if o.update_time else "",
                    "gateway_name": o.gateway_name,
                })
            return result
        except Exception as exc:
            logger.warning("state_reader: 读取订单异常: %s", exc)

    snap = _read_state_snapshot()
    if snap:
        return snap.get("pending_orders", [])
    return []


def get_trades() -> list:
    """获取历史成交列表。

    Returns:
        list[dict]: 成交列表
    """
    engine = _get_engine()
    if engine and engine.order_manager:
        try:
            trades = engine.order_manager.get_trades()
            result = []
            for t in trades:
                result.append({
                    "trade_id": t.trade_id,
                    "order_id": t.order_id,
                    "symbol": t.symbol,
                    "direction": t.direction.value if hasattr(t.direction, "value") else str(t.direction),
                    "offset": t.offset,
                    "price": t.price,
                    "volume": t.volume,
                    "trade_time": str(t.trade_time) if t.trade_time else "",
                    "gateway_name": t.gateway_name,
                })
            return result
        except Exception as exc:
            logger.warning("state_reader: 读取成交异常: %s", exc)

    # 回退到 SQLite
    db = _get_db_reader()
    if db:
        try:
            return db.get_trades()
        except Exception as exc:
            logger.warning("state_reader: 读取 DB 成交异常: %s", exc)
    return []


def get_order_statistics() -> dict:
    """获取订单统计。

    Returns:
        dict: {total, traded, canceled, rejected, active, trade_rate}
    """
    engine = _get_engine()
    if engine and engine.order_manager:
        try:
            stats = engine.order_manager.get_order_statistics()
            stats["source"] = "live"
            return stats
        except Exception as exc:
            logger.warning("state_reader: 读取订单统计异常: %s", exc)
    return {"source": "none", "total": 0, "traded": 0, "canceled": 0,
            "rejected": 0, "active": 0, "trade_rate": 0}


def get_risk_status() -> dict:
    """获取风控状态。

    Returns:
        dict: {margin_status, alerts, auto_reduce_plan}
    """
    engine = _get_engine()
    result = {"margin_status": {}, "alerts": [], "auto_reduce_plan": []}

    if engine and engine.risk_manager:
        try:
            rm = engine.risk_manager
            result["margin_status"] = rm.get_margin_status()
            result["alerts"] = rm.check_positions()
            result["auto_reduce_plan"] = [
                {
                    "symbol": a.symbol,
                    "direction": a.direction,
                    "current_volume": a.current_volume,
                    "reduce_volume": a.reduce_volume,
                    "reduce_type": a.reduce_type,
                }
                for a in rm.plan_auto_reduce()
            ]
            result["source"] = "live"
            return result
        except Exception as exc:
            logger.warning("state_reader: 读取风控状态异常: %s", exc)

    # 快照模式：基于账户数据简单估算
    snap = _read_state_snapshot()
    if snap and "account" in snap:
        acct = snap["account"]
        balance = acct.get("balance", 0.0)
        margin = acct.get("margin", 0.0)
        risk_ratio = margin / balance if balance > 0 else 0.0
        if risk_ratio >= 1.0:
            level = "liquidation"
        elif risk_ratio >= 0.9:
            level = "danger"
        elif risk_ratio >= 0.8:
            level = "warning"
        else:
            level = "normal"
        result["margin_status"] = {
            "total_equity": balance,
            "total_margin": margin,
            "available_margin": balance - margin,
            "risk_ratio": risk_ratio,
            "risk_level": level,
        }
        result["source"] = "snapshot"
    else:
        result["source"] = "none"
    return result


def get_recent_alerts(limit: int = 50) -> list:
    """获取最近告警。

    Args:
        limit: 返回条数上限

    Returns:
        list[dict]: 告警事件列表
    """
    engine = _get_engine()
    if engine and engine.alerter:
        try:
            events = getattr(engine.alerter, "_today_events", [])
            result = []
            for ev in reversed(events[-limit:]):
                result.append({
                    "time": str(ev.timestamp) if hasattr(ev, "timestamp") else "",
                    "type": ev.alert_type.value if hasattr(ev.alert_type, "value") else str(getattr(ev, "alert_type", "")),
                    "level": ev.level.value if hasattr(ev.level, "value") else str(getattr(ev, "level", "")),
                    "title": ev.title if hasattr(ev, "title") else "",
                    "message": ev.message if hasattr(ev, "message") else "",
                    "symbol": ev.symbol if hasattr(ev, "symbol") else "",
                })
            return result
        except Exception as exc:
            logger.warning("state_reader: 读取告警异常: %s", exc)
    return []


def get_equity_history() -> "list[dict]":
    """获取权益历史数据。

    Returns:
        list[dict]: [{timestamp, equity, available, margin, pnl}, ...]
    """
    # 优先从 SQLite 读取
    db = _get_db_reader()
    if db:
        try:
            rows = db.get_equity_history()
            if rows:
                return rows
        except Exception as exc:
            logger.warning("state_reader: 读取 DB 权益历史异常: %s", exc)

    # 回退到 CSV 文件
    csv_path = EQUITY_HISTORY_CSV
    if not csv_path.exists():
        return []

    import csv
    try:
        rows = []
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append({
                    "timestamp": row.get("timestamp", ""),
                    "equity": float(row.get("equity", 0)),
                    "available": float(row.get("available", 0)),
                    "margin": float(row.get("margin", 0)),
                    "pnl": float(row.get("pnl", 0)),
                })
        return rows
    except Exception as exc:
        logger.warning("state_reader: 读取权益历史异常: %s", exc)
        return []


def get_log_lines(log_file: str = "live_engine.log", n: int = 200) -> list:
    """获取日志文件末尾 N 行。

    Args:
        log_file: 日志文件名，如 live_engine.log、app.log
        n: 读取行数

    Returns:
        list[str]: 日志行列表
    """
    log_path = LOG_DIR / log_file
    if not log_path.exists():
        return [f"[日志文件不存在: {log_path}]"]

    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return [line.rstrip("\n") for line in lines[-n:]]
    except Exception as exc:
        return [f"[读取日志失败: {exc}]"]


def get_log_files() -> list:
    """获取可用的日志文件名列表。"""
    if not LOG_DIR.exists():
        return []
    return sorted(f.name for f in LOG_DIR.glob("*.log"))


def get_scheduler_tasks() -> list:
    """获取定时任务状态列表。

    Returns:
        list[dict]: [{name, enabled, status, last_run, error_count, description}, ...]
    """
    engine = _get_engine()
    if engine and hasattr(engine, "_scheduler") and engine._scheduler:
        try:
            scheduler = engine._scheduler
            tasks = getattr(scheduler, "_tasks", [])
            result = []
            for t in tasks:
                result.append({
                    "name": t.name,
                    "enabled": t.enabled,
                    "status": t.status.name if hasattr(t.status, "name") else str(t.status),
                    "last_run": str(t.last_run) if t.last_run else "",
                    "error_count": t.error_count,
                    "description": getattr(t, "description", ""),
                })
            return result
        except Exception as exc:
            logger.warning("state_reader: 读取调度器任务异常: %s", exc)
    return []


def execute_engine_command(command: str, **kwargs) -> dict:
    """执行引擎命令（手动控制）。

    优先同进程执行，否则通过命令文件跨进程发送给引擎。

    Args:
        command: 命令名，如 pause, resume, stop, close_all, cancel_all
        **kwargs: 额外参数

    Returns:
        dict: {success, message}
    """
    engine = _get_engine()
    if engine:
        try:
            if command == "pause":
                engine.pause()
                return {"success": True, "message": "引擎已暂停"}
            elif command == "resume":
                engine.resume()
                return {"success": True, "message": "引擎已恢复"}
            elif command == "stop":
                engine.stop()
                return {"success": True, "message": "引擎已停止"}
            elif command == "close_all":
                return _close_all_positions(engine)
            elif command == "cancel_all":
                return _cancel_all_orders(engine)
            else:
                return {"success": False, "message": f"未知命令: {command}"}
        except Exception as exc:
            return {"success": False, "message": f"命令执行失败: {exc}"}

    # 跨进程：写入命令文件，由引擎主循环读取执行
    if not is_engine_recent():
        return {"success": False, "message": "引擎未运行，无法发送命令"}

    try:
        cmd_id = f"{int(time.time()*1000)}_{command}"
        cmd = {
            "id": cmd_id,
            "command": command,
            "kwargs": kwargs,
            "timestamp": datetime.now().isoformat(sep=" ", timespec="seconds"),
            "status": "pending",
        }
        COMMANDS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(COMMANDS_FILE, "w", encoding="utf-8") as f:
            json.dump(cmd, f, ensure_ascii=False, indent=2)
        return {"success": True, "message": f"命令已发送: {command}"}
    except Exception as exc:
        return {"success": False, "message": f"发送命令失败: {exc}"}


def _close_all_positions(engine) -> dict:
    """平掉所有持仓。"""
    try:
        from src.trade.gateway import OrderDirection
        positions = engine.position_manager.get_all_positions()
        if not positions:
            return {"success": False, "message": "当前无持仓"}
        count = 0
        for pos in positions:
            if pos.direction == OrderDirection.BUY:
                engine.order_manager.sell(pos.symbol, pos.price, pos.volume)
                count += 1
            elif pos.direction == OrderDirection.SHORT:
                engine.order_manager.cover(pos.symbol, pos.price, pos.volume)
                count += 1
        return {"success": True, "message": f"已提交 {count} 个平仓订单"}
    except Exception as exc:
        return {"success": False, "message": f"全平失败: {exc}"}


def _cancel_all_orders(engine) -> dict:
    """取消所有活跃订单。"""
    try:
        active = engine.order_manager.get_active_orders()
        if not active:
            return {"success": False, "message": "当前无活跃订单"}
        count = 0
        for o in active:
            engine.order_manager.cancel(o.order_id)
            count += 1
        return {"success": True, "message": f"已提交 {count} 个撤单请求"}
    except Exception as exc:
        return {"success": False, "message": f"撤单失败: {exc}"}


def get_strategy_signals(symbol: str = "", limit: int = 200) -> list:
    """获取策略信号记录（从 SQLite）。

    Returns:
        list[dict]: [{symbol, signal_type, price, volume, reason, bar_time, strategy_name, created_at}, ...]
    """
    db = _get_db_reader()
    if db:
        try:
            return db.get_signals(symbol=symbol, limit=limit)
        except Exception as exc:
            logger.warning("state_reader: 读取策略信号异常: %s", exc)
    return []
