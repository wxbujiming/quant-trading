"""
SQLite 持久化数据库。

替代 JSON 快照 + CSV 权益历史，统一存储引擎状态、成交记录、权益曲线。

用法:
    db = TradeDatabase()
    db.save_state(trading_day="20260520", state="RUNNING", ...)
    snap = db.load_latest_state()
    db.record_equity(timestamp, equity=10000, ...)
    rows = db.get_equity_history()
"""
import sqlite3
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional


DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "live_state" / "trading.db"


class TradeDatabase:
    """交易数据库（线程安全，支持同进程 Web 面板并发读）。"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_tables()

    # ────────── 连接管理 ──────────

    def _conn(self) -> sqlite3.Connection:
        """创建新连接（每次调用独立，线程安全）。"""
        c = sqlite3.connect(str(self.db_path))
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")       # 写不阻塞读
        c.execute("PRAGMA synchronous=NORMAL")      # 安全与性能平衡
        return c

    # ────────── 建表 ──────────

    def _init_tables(self):
        with self._lock:
            c = self._conn()
            try:
                c.executescript("""
                CREATE TABLE IF NOT EXISTS engine_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    trading_day TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'IDLE',
                    balance REAL NOT NULL DEFAULT 0,
                    available REAL NOT NULL DEFAULT 0,
                    margin REAL NOT NULL DEFAULT 0,
                    pnl REAL NOT NULL DEFAULT 0,
                    positions TEXT NOT NULL DEFAULT '[]',
                    pending_orders TEXT NOT NULL DEFAULT '[]',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS equity_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    equity REAL NOT NULL,
                    available REAL NOT NULL DEFAULT 0,
                    margin REAL NOT NULL DEFAULT 0,
                    pnl REAL NOT NULL DEFAULT 0,
                    trading_day TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_eq_ts ON equity_history(timestamp);

                CREATE TABLE IF NOT EXISTS trade_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    offset_flag TEXT NOT NULL DEFAULT '',
                    volume INTEGER NOT NULL,
                    price REAL NOT NULL,
                    trade_time TEXT NOT NULL,
                    trade_id TEXT,
                    order_id TEXT,
                    trading_day TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
                );
                CREATE INDEX IF NOT EXISTS idx_tr_sym ON trade_records(symbol);
                CREATE INDEX IF NOT EXISTS idx_tr_day ON trade_records(trading_day);
                CREATE INDEX IF NOT EXISTS idx_tr_ts ON trade_records(trade_time);

                CREATE TABLE IF NOT EXISTS order_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    offset_flag TEXT NOT NULL DEFAULT '',
                    price REAL NOT NULL,
                    volume INTEGER NOT NULL,
                    traded INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    create_time TEXT NOT NULL,
                    update_time TEXT,
                    trading_day TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ol_oid ON order_log(order_id);

                CREATE TABLE IF NOT EXISTS strategy_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    price REAL NOT NULL,
                    volume INTEGER,
                    reason TEXT,
                    bar_time TEXT,
                    strategy_name TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
                );
                CREATE INDEX IF NOT EXISTS idx_ss_sym ON strategy_signals(symbol);
                CREATE INDEX IF NOT EXISTS idx_ss_ts ON strategy_signals(created_at);
                """)
            finally:
                c.close()

    # ────────── 引擎状态 ──────────

    def save_state(self, trading_day: str, state: str,
                   balance: float = 0, available: float = 0,
                   margin: float = 0, pnl: float = 0,
                   positions: list = None, pending_orders: list = None):
        """写入最新引擎状态快照（upsert 单行）。"""
        now = datetime.now().isoformat(sep=" ", timespec="seconds")
        with self._lock:
            c = self._conn()
            try:
                c.execute("""
                    INSERT INTO engine_state (id, trading_day, state,
                        balance, available, margin, pnl,
                        positions, pending_orders, updated_at)
                    VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        trading_day=excluded.trading_day,
                        state=excluded.state,
                        balance=excluded.balance,
                        available=excluded.available,
                        margin=excluded.margin,
                        pnl=excluded.pnl,
                        positions=excluded.positions,
                        pending_orders=excluded.pending_orders,
                        updated_at=excluded.updated_at
                """, (
                    trading_day, state,
                    balance, available, margin, pnl,
                    json.dumps(positions or [], ensure_ascii=False),
                    json.dumps(pending_orders or [], ensure_ascii=False),
                    now,
                ))
                c.commit()
            finally:
                c.close()

    def load_latest_state(self) -> Optional[dict]:
        """读取最新引擎状态。"""
        c = self._conn()
        try:
            row = c.execute("SELECT * FROM engine_state WHERE id = 1").fetchone()
            if not row:
                return None
            return dict(row)
        finally:
            c.close()

    # ────────── 权益历史 ──────────

    def record_equity(self, timestamp, equity: float,
                      available: float = 0, margin: float = 0,
                      pnl: float = 0, trading_day: str = ""):
        """追加一条权益快照。"""
        if isinstance(timestamp, datetime):
            ts = timestamp.isoformat(sep=" ", timespec="seconds")
        else:
            ts = str(timestamp)
        with self._lock:
            c = self._conn()
            try:
                c.execute(
                    "INSERT INTO equity_history (timestamp, equity, available, margin, pnl, trading_day) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (ts, equity, available, margin, pnl, trading_day),
                )
                c.commit()
            finally:
                c.close()

    def get_equity_history(self, limit: int = 10000) -> list:
        """获取权益历史（按时间升序）。"""
        c = self._conn()
        try:
            rows = c.execute(
                "SELECT * FROM equity_history ORDER BY timestamp ASC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            c.close()

    # ────────── 成交记录 ──────────

    def record_trade(self, symbol: str, direction: str, volume: int, price: float,
                     trade_time: str = "", trade_id: str = "",
                     order_id: str = "", offset_flag: str = "",
                     trading_day: str = ""):
        """记录一笔成交。"""
        with self._lock:
            c = self._conn()
            try:
                c.execute(
                    """INSERT INTO trade_records
                       (symbol, direction, offset_flag, volume, price,
                        trade_time, trade_id, order_id, trading_day)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (symbol, direction, offset_flag, volume, price,
                     trade_time, trade_id, order_id, trading_day),
                )
                c.commit()
            finally:
                c.close()

    def get_trades(self, symbol: str = "", limit: int = 500) -> list:
        """获取成交记录（按时间降序）。"""
        c = self._conn()
        try:
            if symbol:
                rows = c.execute(
                    "SELECT * FROM trade_records WHERE symbol=? ORDER BY trade_time DESC LIMIT ?",
                    (symbol, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM trade_records ORDER BY trade_time DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            c.close()

    # ────────── 订单日志 ──────────

    def record_order(self, order_id: str, symbol: str, direction: str,
                     price: float, volume: int, status: str,
                     traded: int = 0, offset_flag: str = "",
                     create_time: str = "", update_time: str = "",
                     trading_day: str = ""):
        """记录订单状态。"""
        with self._lock:
            c = self._conn()
            try:
                c.execute(
                    """INSERT INTO order_log
                       (order_id, symbol, direction, offset_flag,
                        price, volume, traded, status,
                        create_time, update_time, trading_day)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (order_id, symbol, direction, offset_flag,
                     price, volume, traded, status,
                     create_time, update_time, trading_day),
                )
                c.commit()
            finally:
                c.close()

    def get_orders(self, limit: int = 500) -> list:
        """获取订单日志（按时间降序）。"""
        c = self._conn()
        try:
            rows = c.execute(
                "SELECT * FROM order_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            c.close()

    # ────────── 策略信号 ──────────

    def record_signal(self, symbol: str, signal_type: str, price: float,
                      volume: int = 0, reason: str = "",
                      bar_time: str = "", strategy_name: str = ""):
        """记录一次策略信号触发。"""
        with self._lock:
            c = self._conn()
            try:
                c.execute(
                    """INSERT INTO strategy_signals
                       (symbol, signal_type, price, volume, reason, bar_time, strategy_name)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (symbol, signal_type, price, volume, reason, bar_time, strategy_name),
                )
                c.commit()
            finally:
                c.close()

    def get_signals(self, symbol: str = "", limit: int = 200) -> list:
        """获取策略信号记录。"""
        c = self._conn()
        try:
            if symbol:
                rows = c.execute(
                    "SELECT * FROM strategy_signals WHERE symbol=? ORDER BY id DESC LIMIT ?",
                    (symbol, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM strategy_signals ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            c.close()

    # ────────── 工具方法 ──────────

    def migrate_from_json(self, state_dir: Path):
        """从 JSON 状态文件迁移历史数据（一次性迁移工具）。"""
        import csv
        state_dir = Path(state_dir)
        if not state_dir.exists():
            return

        # 迁移权益历史 CSV
        csv_file = state_dir / "equity_history.csv"
        if csv_file.exists():
            with open(csv_file, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                count = 0
                for row in reader:
                    self.record_equity(
                        timestamp=row.get("timestamp", ""),
                        equity=float(row.get("equity", 0)),
                        available=float(row.get("available", 0)),
                        margin=float(row.get("margin", 0)),
                        pnl=float(row.get("pnl", 0)),
                    )
                    count += 1
            print(f"[migrate] 已迁移 {count} 条权益记录")

        # 迁移最新状态 JSON
        json_files = sorted(state_dir.glob("live_state_*.json"), reverse=True)
        if json_files:
            with open(json_files[0], encoding="utf-8") as f:
                data = json.load(f)
            acct = data.get("account", {})
            self.save_state(
                trading_day=data.get("trading_day", ""),
                state=data.get("state", "UNKNOWN"),
                balance=acct.get("balance", 0),
                available=acct.get("available", 0),
                margin=acct.get("margin", 0),
                pnl=acct.get("pnl", 0),
                positions=data.get("positions", []),
                pending_orders=data.get("pending_orders", []),
            )
            print(f"[migrate] 已迁移引擎状态: {json_files[0].name}")
