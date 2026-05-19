"""
风控状态 — 风险度仪表盘 + 告警列表 + 自动减仓预案。
"""

import streamlit as st


def show():
    from web.state_reader import get_risk_status

    st.header("🛡️ 风控状态")

    risk = get_risk_status()
    margin_status = risk.get("margin_status", {})
    alerts = risk.get("alerts", [])
    reduce_plan = risk.get("auto_reduce_plan", [])

    # --------------------------------------------------------------
    # 风险度仪表盘
    # --------------------------------------------------------------
    st.subheader("风险度概览")

    risk_ratio = margin_status.get("risk_ratio", 0.0) * 100
    risk_level = margin_status.get("risk_level", "normal")
    total_equity = margin_status.get("total_equity", 0)
    total_margin = margin_status.get("total_margin", 0)
    available_margin = margin_status.get("available_margin", 0)

    # 风险度颜色
    if risk_level == "liquidation":
        bar_color = "#FF4444"
        level_label = "🔴 强平"
    elif risk_level == "danger":
        bar_color = "#FF8800"
        level_label = "🟠 危险"
    elif risk_level == "warning":
        bar_color = "#FFD93D"
        level_label = "🟡 警告"
    else:
        bar_color = "#6BCB77"
        level_label = "🟢 正常"

    # 大数字 + 进度条
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        st.metric("风险度", f"{risk_ratio:.1f}%")
        st.caption(f"等级: {level_label}")
    with col2:
        st.metric("总权益", f"¥{total_equity:,.2f}")
    with col3:
        st.metric("占用保证金", f"¥{total_margin:,.2f}")

    # 进度条
    display_ratio = min(risk_ratio / 100.0, 1.5)
    st.progress(
        min(display_ratio, 1.0),
        text=f"风险度: {risk_ratio:.1f}% — {level_label}",
    )

    # 阈值标记
    st.markdown(
        f"""
        <div style="display: flex; gap: 20px; font-size: 12px; color: #888;">
            <span>🟢 正常 &lt; 80%</span>
            <span>🟡 警告 ≥ 80%</span>
            <span>🟠 危险 ≥ 90%</span>
            <span style="color:#FF4444">🔴 强平 ≥ 100%</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # --------------------------------------------------------------
    # 风控告警
    # --------------------------------------------------------------
    st.divider()
    st.subheader("风控告警")

    if alerts:
        alert_rows = []
        level_map = {"critical": "严重", "danger": "危险", "warning": "警告", "info": "通知"}
        for a in alerts:
            alert_rows.append({
                "规则": a.get("rule", ""),
                "合约": a.get("symbol", ""),
                "级别": level_map.get(a.get("level", ""), a.get("level", "")),
                "内容": a.get("message", ""),
            })
        st.dataframe(alert_rows, use_container_width=True, hide_index=True)
    else:
        st.info("当前无风控告警 ✅")

    # --------------------------------------------------------------
    # 自动减仓预案
    # --------------------------------------------------------------
    st.divider()
    st.subheader("自动减仓预案")

    if reduce_plan:
        plan_rows = []
        for act in reduce_plan:
            dir_cn = {"long": "多头", "short": "空头"}.get(act.get("direction", ""), act.get("direction", ""))
            plan_rows.append({
                "合约": act.get("symbol", ""),
                "方向": dir_cn,
                "当前持仓": act.get("current_volume", 0),
                "建议减仓": act.get("reduce_volume", 0),
                "类型": "🔥 全平" if act.get("reduce_type") == "flat" else "✂️ 部分减仓",
            })
        st.warning("以下持仓建议减仓/平仓:")
        st.dataframe(plan_rows, use_container_width=True, hide_index=True)
    else:
        st.info("无需减仓 ✅")


if __name__ == "__main__":
    show()
