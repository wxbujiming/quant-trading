"""
订单列表 — 活跃订单 + 历史成交。
"""

import streamlit as st


def show():
    from web.state_reader import get_orders, get_trades, get_order_statistics

    st.header("📋 订单")

    stats = get_order_statistics()

    # --------------------------------------------------------------
    # 统计指标行
    # --------------------------------------------------------------
    cols = st.columns(5)
    with cols[0]:
        st.metric("总订单", stats.get("total", 0))
    with cols[1]:
        st.metric("已成交", stats.get("traded", 0))
    with cols[2]:
        st.metric("已取消", stats.get("canceled", 0))
    with cols[3]:
        st.metric("活跃中", stats.get("active", 0))
    with cols[4]:
        st.metric("成交率", f"{stats.get('trade_rate', 0):.1f}%")

    # --------------------------------------------------------------
    # Tab: 活跃订单 / 历史成交
    # --------------------------------------------------------------
    tab1, tab2 = st.tabs(["活跃订单", "历史成交"])

    with tab1:
        active_orders = get_orders(status="active")
        if active_orders:
            rows = []
            for o in active_orders:
                rows.append({
                    "时间": str(o.get("create_time", ""))[:19],
                    "订单号": o.get("order_id", ""),
                    "合约": o.get("symbol", ""),
                    "方向": _fmt_direction(o),
                    "价格": o.get("price", 0.0),
                    "数量": o.get("volume", 0),
                    "已成交": o.get("traded", 0),
                    "状态": _fmt_status(o.get("status", "")),
                })
            st.dataframe(
                rows,
                column_config={
                    "价格": st.column_config.NumberColumn(format="%.2f"),
                },
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("暂无活跃订单")

    with tab2:
        trades = get_trades()
        if trades:
            rows = []
            for t in trades:
                rows.append({
                    "成交时间": str(t.get("trade_time", ""))[:19],
                    "成交编号": t.get("trade_id", ""),
                    "合约": t.get("symbol", ""),
                    "方向": _fmt_trade_direction(t),
                    "成交价": t.get("price", 0.0),
                    "数量": t.get("volume", 0),
                })
            st.dataframe(
                rows,
                column_config={
                    "成交价": st.column_config.NumberColumn(format="%.2f"),
                },
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("暂无历史成交")


def _fmt_direction(o: dict) -> str:
    """格式化方向显示。"""
    d = o.get("direction", "")
    offset = o.get("offset", "")
    if offset == "open":
        return f"📈 开多" if d in ("buy", "BUY") else f"📉 开空"
    elif offset == "close":
        return f"📉 平多" if d in ("sell", "SELL") else f"📈 平空"
    return d.upper() if d else "-"


def _fmt_trade_direction(t: dict) -> str:
    """格式化成交方向显示。"""
    d = t.get("direction", "")
    offset = t.get("offset", "")
    if offset == "open":
        return f"📈 开多" if d in ("buy", "BUY") else f"📉 开空"
    elif offset == "close":
        return f"📉 平多" if d in ("sell", "SELL") else f"📈 平空"
    return d.upper() if d else "-"


def _fmt_status(status: str) -> str:
    """格式化并着色订单状态。"""
    status_map = {
        "submitting": "⏳ 提交中",
        "not_traded": "⏸️ 未成交",
        "part_traded": "🔄 部分成交",
        "all_traded": "✅ 全部成交",
        "canceled": "❌ 已取消",
        "rejected": "🚫 已拒绝",
        "error": "⚠️ 错误",
    }
    return status_map.get(status.lower(), status)


if __name__ == "__main__":
    show()
