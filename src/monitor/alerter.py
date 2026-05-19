"""
告警系统 - 钉钉消息推送

通过钉钉机器人 Webhook 推送交易告警消息。
支持 HMAC-SHA256 签名和频率限制。
"""
import hashlib
import hmac
import base64
import json
import time
from datetime import datetime, date
from enum import Enum
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from pathlib import Path

import requests
from loguru import logger


class AlertLevel(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertType(Enum):
    TRADE = "trade"                 # 开平仓通知
    STOP_LOSS = "stop_loss"         # 止损触发
    MARGIN = "margin"               # 保证金不足
    ROLLOVER = "rollover"           # 换月移仓
    LIQUIDATION = "liquidation"     # 强平预警
    POSITION_ABNORMAL = "position_abnormal"  # 持仓异常
    SYSTEM = "system"               # 系统故障


LEVEL_EMOJI = {
    AlertLevel.INFO: "ℹ️",
    AlertLevel.WARNING: "⚠️",
    AlertLevel.CRITICAL: "🚨",
}

TYPE_LABELS = {
    AlertType.TRADE: "交易通知",
    AlertType.STOP_LOSS: "止损触发",
    AlertType.MARGIN: "保证金告警",
    AlertType.ROLLOVER: "换月移仓",
    AlertType.LIQUIDATION: "强平预警",
    AlertType.POSITION_ABNORMAL: "持仓异常",
    AlertType.SYSTEM: "系统通知",
}


@dataclass
class AlertEvent:
    """告警事件"""
    alert_type: AlertType
    level: AlertLevel
    title: str
    message: str
    symbol: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    details: Dict[str, Any] = field(default_factory=dict)


class DingTalkSender:
    """
    钉钉机器人消息发送

    支持 HMAC-SHA256 签名（安全设置方式）。
    自动频率限制 18条/分钟。
    """

    def __init__(self, webhook_url: str = "", secret: str = ""):
        self.webhook_url = webhook_url
        self.secret = secret
        self._send_times: List[float] = []
        self._max_per_minute = 18

    @property
    def configured(self) -> bool:
        return bool(self.webhook_url)

    def send_markdown(self, title: str, text: str) -> bool:
        """发送 markdown 消息"""
        if not self.webhook_url:
            logger.debug("钉钉 Webhook 未配置，跳过推送")
            return False

        if not self._check_rate_limit():
            logger.warning("钉钉消息频率超限，跳过")
            return False

        url = self._sign_url()
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title[:64],
                "text": text,
            },
        }

        try:
            resp = requests.post(url, json=payload, timeout=5)
            result = resp.json()
            if result.get("errcode") == 0:
                self._record_send()
                return True
            else:
                logger.error(f"钉钉推送失败: {result.get('errmsg', '')}")
                return False
        except requests.RequestException as e:
            logger.error(f"钉钉推送请求失败: {e}")
            return False

    def _sign_url(self) -> str:
        """HMAC-SHA256 签名"""
        if not self.secret:
            return self.webhook_url

        timestamp = str(int(time.time() * 1000))
        sign_str = f"{timestamp}\n{self.secret}"
        signature = base64.b64encode(
            hmac.new(self.secret.encode(), sign_str.encode(), hashlib.sha256).digest()
        ).decode()

        sep = "&" if "?" in self.webhook_url else "?"
        return f"{self.webhook_url}{sep}timestamp={timestamp}&sign={signature}"

    def _check_rate_limit(self) -> bool:
        now = time.time()
        self._send_times = [t for t in self._send_times if now - t < 60]
        return len(self._send_times) < self._max_per_minute

    def _record_send(self):
        self._send_times.append(time.time())


class Alerter:
    """
    告警管理器

    收集交易系统中的各类事件，推送至钉钉。
    同时缓存当日事件以生成结算报告。
    """

    def __init__(
        self,
        webhook_url: str = "",
        secret: str = "",
        report_dir: str = "./reports/daily",
        enabled: bool = True,
    ):
        self.dingtalk = DingTalkSender(webhook_url, secret)
        self.report_dir = Path(report_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.enabled = enabled

        self._today_events: List[AlertEvent] = []
        self._today_date = datetime.now().date()

        self._dedup_cache: Dict[str, float] = {}

    # ────────────── 通用发送 ──────────────

    def send(self, event: AlertEvent):
        """发送一条告警"""
        if not self.enabled:
            return

        self._check_date()

        dedup_key = f"{event.alert_type.value}:{event.symbol}"
        now = time.time()
        last = self._dedup_cache.get(dedup_key, 0)
        if now - last < 60:
            return
        self._dedup_cache[dedup_key] = now

        self._today_events.append(event)

        emoji = LEVEL_EMOJI.get(event.level, "📢")
        label = TYPE_LABELS.get(event.alert_type, "通知")
        title = f"[{event.level.value}] {event.title}"

        lines = [
            f"### {emoji} {label}",
            f"---",
        ]
        if event.symbol:
            lines.append(f"**合约**: {event.symbol}")
        lines += [
            "",
            event.message,
            "",
            f"📅 {event.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
        ]

        self.dingtalk.send_markdown(title, "\n".join(lines))

        if event.level == AlertLevel.CRITICAL:
            logger.critical(f"[告警] {title}: {event.message}")
        else:
            logger.info(f"[告警] {title}: {event.message}")

    # ────────────── 便捷方法 ──────────────

    def send_trade(self, symbol: str, direction: str, volume: int, price: float):
        """开平仓通知"""
        self.send(AlertEvent(
            alert_type=AlertType.TRADE,
            level=AlertLevel.INFO,
            title=f"{symbol} {direction} {volume}手",
            message=f"价格: {price}\n数量: {volume}手",
            symbol=symbol,
            details={"direction": direction, "volume": volume, "price": price},
        ))

    def send_stop_loss(self, symbol: str, direction: str, loss: float,
                       entry_price: float, stop_price: float):
        """止损触发通知"""
        self.send(AlertEvent(
            alert_type=AlertType.STOP_LOSS,
            level=AlertLevel.WARNING,
            title=f"{symbol} 止损触发",
            message=(
                f"方向: {direction}\n"
                f"开仓价: {entry_price}\n"
                f"止损价: {stop_price}\n"
                f"亏损: {loss:,.0f}"
            ),
            symbol=symbol,
        ))

    def send_margin_warning(self, equity: float, margin: float, risk_ratio: float):
        """保证金告警"""
        level = AlertLevel.CRITICAL if risk_ratio >= 1.0 else AlertLevel.WARNING
        self.send(AlertEvent(
            alert_type=AlertType.MARGIN,
            level=level,
            title=f"保证金告警 风险度{risk_ratio:.1%}",
            message=(
                f"总权益: {equity:,.0f}\n"
                f"占用保证金: {margin:,.0f}\n"
                f"风险度: {risk_ratio:.1%}"
            ),
        ))

    def send_rollover(self, base: str, old_contract: str, new_contract: str):
        """换月移仓通知"""
        self.send(AlertEvent(
            alert_type=AlertType.ROLLOVER,
            level=AlertLevel.INFO,
            title=f"{base} 换月: {old_contract} → {new_contract}",
            message=f"旧合约: {old_contract}\n新合约: {new_contract}",
            symbol=base,
        ))

    def send_liquidation_warning(self, risk_ratio: float, equity: float, margin: float):
        """强平预警"""
        self.send(AlertEvent(
            alert_type=AlertType.LIQUIDATION,
            level=AlertLevel.CRITICAL,
            title=f"强平预警! 风险度{risk_ratio:.1%}",
            message=(
                f"总权益: {equity:,.0f}\n"
                f"占用保证金: {margin:,.0f}\n"
                f"风险度: {risk_ratio:.1%}\n"
                f"请立即减仓!"
            ),
        ))

    def send_system_error(self, message: str):
        """系统故障通知"""
        self.send(AlertEvent(
            alert_type=AlertType.SYSTEM,
            level=AlertLevel.CRITICAL,
            title="系统故障",
            message=message,
        ))

    def send_auto_reduce(self, symbol: str, direction: str,
                         reduce_volume: int, current_volume: int,
                         reduce_type: str):
        """自动减仓通知"""
        atype = "全部平仓" if reduce_type == "flat" else "部分减仓"
        self.send(AlertEvent(
            alert_type=AlertType.SYSTEM,
            level=AlertLevel.WARNING,
            title=f"{atype}: {symbol} {direction}",
            message=(
                f"品种: {symbol}\n"
                f"方向: {direction}\n"
                f"减仓: {reduce_volume}/{current_volume}手\n"
                f"类型: {atype}"
            ),
            symbol=symbol,
        ))

    def send_cancel_warning(self, cancel_count: int = 0, window_minutes: int = 1,
                            cancel_ratio: float = None, large_cancel: dict = None):
        """报撤单异常通知"""
        if large_cancel:
            symbol = large_cancel.get("symbol", "")
            volume = large_cancel.get("volume", 0)
            seconds = large_cancel.get("hold_seconds", 0)
            self.send(AlertEvent(
                alert_type=AlertType.SYSTEM,
                level=AlertLevel.WARNING,
                title=f"大额报撤单: {symbol}",
                message=(
                    f"品种: {symbol}\n"
                    f"手数: {volume}手\n"
                    f"持仓时间: {seconds:.0f}秒\n"
                    f"行为: 挂出大额订单后快速撤单"
                ),
                symbol=symbol,
            ))
        elif cancel_ratio is not None:
            level = AlertLevel.CRITICAL if cancel_ratio > 0.6 else AlertLevel.WARNING
            self.send(AlertEvent(
                alert_type=AlertType.SYSTEM,
                level=level,
                title=f"报撤比异常: {cancel_ratio:.0%}",
                message=(
                    f"最近{window_minutes}分钟报撤比: {cancel_ratio:.0%}\n"
                    f"撤单次数: {cancel_count}\n"
                    f"请检查是否存在异常撤单行为"
                ),
            ))
        else:
            self.send(AlertEvent(
                alert_type=AlertType.SYSTEM,
                level=AlertLevel.WARNING,
                title=f"撤单频率过高",
                message=(
                    f"最近{window_minutes}分钟撤单: {cancel_count}次\n"
                    f"请降低撤单频率以避免交易所风控"
                ),
            ))

    # ────────────── 每日结算报告 ──────────────

    def generate_daily_report(self) -> Optional[str]:
        """生成当日结算报告 Markdown 文件"""
        today_str = datetime.now().strftime("%Y%m%d")
        report_file = self.report_dir / f"daily_report_{today_str}.md"

        lines = [
            f"# 交易日报 {datetime.now().strftime('%Y-%m-%d')}",
            "",
            f"## 告警事件汇总",
            "",
            f"| 时间 | 类型 | 级别 | 合约 | 内容 |",
            f"|------|------|------|------|------|",
        ]
        for evt in self._today_events:
            t = evt.timestamp.strftime("%H:%M:%S")
            lev = LEVEL_EMOJI.get(evt.level, " ")
            lines.append(
                f"| {t} | {TYPE_LABELS.get(evt.alert_type, '')} | "
                f"{lev} | {evt.symbol or '-'} | {evt.title} |"
            )

        report_file.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"每日报告已生成: {report_file}")
        return str(report_file)

    def _check_date(self):
        """跨日时重置事件缓存并生成上日报告"""
        today = datetime.now().date()
        if today != self._today_date:
            if self._today_events:
                self.generate_daily_report()
            self._today_events.clear()
            self._today_date = today
