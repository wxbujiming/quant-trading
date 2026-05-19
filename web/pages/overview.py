"""
总览仪表盘 — 关键账户指标 + 今日告警。
"""

import streamlit as st
from datetime import datetime


def show():
    from web.state_reader import (
        get_account_summary,
        get_engine_state,
        get_risk_status,
        get_recent_alerts,
        get_order_statistics,
    )

    st.header("📊 总览")

    account = get_account_summary()
    eng_state = get_engine_state()
    risk = get_risk_status()
    alerts = get_recent_alerts(limit=20)
    order_stats = get_order_statistics()

    # ------------------------------------------------------------------
    # 第1行：账户指标
    # ------------------------------------------------------------------
    cols1 = st.columns(4)
    with cols1[0]:
        balance = account.get("total_balance", 0)
        delta_pnl = account.get("total_pnl", 0)
        st.metric(
            "总权益",
            f"¥{balance:,.2f}",
            delta=f"¥{delta_pnl:+,.2f}" if delta_pnl else None,
            delta_color="normal",
        )
    with cols1[1]:
        available = account.get("total_cash", 0)
        st.metric("可用资金", f"¥{available:,.2f}")
    with cols1[2]:
        pnl = account.get("total_pnl", 0)
        st.metric(
            "浮动盈亏",
            f"¥{pnl:+,.2f}",
            delta_color="inverse",
        )
    with cols1[3]:
        pos_count = account.get("position_count", 0)
        st.metric("持仓品种数", pos_count)

    # ------------------------------------------------------------------
    # 第2行：风控 + 运行指标
    # ------------------------------------------------------------------
    cols2 = st.columns(4)
    margin_status = risk.get("margin_status", {})
    risk_ratio = margin_status.get("risk_ratio", 0.0) * 100
    risk_level = margin_status.get("risk_level", "normal")

    with cols2[0]:
        ratio_color = "normal"
        if risk_ratio >= 100:
            ratio_color = "inverse"
        elif risk_ratio >= 80:
            ratio_color = "off"
        st.metric("风险度", f"{risk_ratio:.1f}%", delta_color=ratio_color)
    with cols2[1]:
        margin = margin_status.get("total_margin", 0)
        st.metric("占用保证金", f"¥{margin:,.2f}")
    with cols2[2]:
        traded_count = order_stats.get("traded", 0)
        st.metric("今日成交笔数", traded_count)
    with cols2[3]:
        from web.state_reader import cn_state, cn_phase, cn_risk_level
        state = eng_state.get("state", "N/A")
        phase = eng_state.get("phase", "")
        st.metric("引擎状态", cn_state(state))
        st.caption(f"阶段: {cn_phase(phase)}" if phase else "")

    # ------------------------------------------------------------------
    # 风险度进度条
    # ------------------------------------------------------------------
    risk_pct = min(risk_ratio / 100.0, 1.5)
    if risk_level == "liquidation":
        bar_color = "red"
    elif risk_level == "danger":
        bar_color = "orange"
    elif risk_level == "warning":
        bar_color = "yellow"
    else:
        bar_color = "green"

    risk_label = cn_risk_level(risk_level)
    st.progress(min(risk_pct, 1.0), text=f"风险度: {risk_ratio:.1f}% ({risk_label})")

    # ------------------------------------------------------------------
    # 告警列表
    # ------------------------------------------------------------------
    st.divider()
    st.subheader("🔔 今日告警")

    if alerts:
        alert_rows = []
        for a in alerts:
            level_str = a.get("level", "")
            # 英文级别 → 中文
            level_cn = {"INFO": "通知", "WARNING": "警告", "CRITICAL": "严重", "ERROR": "错误"}.get(level_str.upper(), level_str)
            type_str = a.get("type", "")
            title = a.get("title", "")
            symbol = a.get("symbol", "")
            msg = a.get("message", "")
            t = a.get("time", "")

            if t and len(t) > 19:
                t = t[:19]
            else:
                t = t[:19] if len(t) > 19 else t

            alert_rows.append({
                "时间": t,
                "级别": level_cn,
                "类型": type_str,
                "合约": symbol,
                "内容": title or msg,
            })

        st.dataframe(
            alert_rows,
            column_config={
                "时间": st.column_config.TextColumn(width=160),
                "级别": st.column_config.TextColumn(width=80),
                "类型": st.column_config.TextColumn(width=100),
                "合约": st.column_config.TextColumn(width=100),
                "内容": st.column_config.TextColumn(width=500),
            },
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("暂无告警")


if __name__ == "__main__":
    show()
