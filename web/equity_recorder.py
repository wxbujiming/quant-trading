"""
权益历史记录器。

记录引擎运行时各时刻的权益快照到 CSV 文件，供 PnL 曲线页面展示。
可在 live_engine.py 的 _save_state() 旁调用 record() 集成。

使用示例:
    from web.equity_recorder import EquityRecorder
    recorder = EquityRecorder()
    recorder.record(timestamp, equity=1000000.0, available=800000.0,
                    margin=200000.0, pnl=5000.0)
"""

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "live_state" / "equity_history.csv"


class EquityRecorder:
    """权益历史 CSV 记录器。"""

    def __init__(self, csv_path: Optional[Path] = None):
        self.csv_path = csv_path or DEFAULT_CSV_PATH
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_header()

    def _ensure_header(self):
        """确保 CSV 文件存在且包含表头。"""
        if not self.csv_path.exists():
            try:
                with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["timestamp", "equity", "available", "margin", "pnl"])
            except Exception as exc:
                logger.error("EquityRecorder: 创建 CSV 失败 %s: %s", self.csv_path, exc)

    def record(self, timestamp, equity: float, available: float, margin: float, pnl: float):
        """追加一条权益快照记录。

        Args:
            timestamp: datetime 对象或 ISO 格式字符串
            equity: 总权益
            available: 可用资金
            margin: 占用保证金
            pnl: 浮动盈亏
        """
        if isinstance(timestamp, datetime):
            ts = timestamp.isoformat(sep=" ", timespec="seconds")
        else:
            ts = str(timestamp)

        try:
            with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([ts, equity, available, margin, pnl])
        except Exception as exc:
            logger.error("EquityRecorder: 写入记录失败: %s", exc)

    def get_history(self) -> list:
        """读取全部历史记录。

        Returns:
            list[dict]: [{timestamp, equity, available, margin, pnl}, ...]
        """
        if not self.csv_path.exists():
            return []
        try:
            rows = []
            with open(self.csv_path, encoding="utf-8") as f:
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
            logger.error("EquityRecorder: 读取历史失败: %s", exc)
            return []

    def clear(self):
        """清空历史记录。"""
        try:
            if self.csv_path.exists():
                self.csv_path.unlink()
            self._ensure_header()
        except Exception as exc:
            logger.error("EquityRecorder: 清空失败: %s", exc)
