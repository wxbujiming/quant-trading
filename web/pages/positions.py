"""
持仓看板 — 当前持仓列表及盈亏。
"""

import streamlit as st


def show():
    from web.state_reader import get_all_positions

    st.header("💼 持仓看板")

    positions = get_all_positions()

    if not positions:
        st.info("当前无持仓")
        return

    rows = []
    total_pnl = 0.0
    total_mv = 0.0

    for pos in positions:
        direction = pos.get("direction", "")
        volume = pos.get("volume", 0)
        available = pos.get("available", 0)
        price = pos.get("price", 0.0)
        pnl = pos.get("pnl", 0.0)
        symbol = pos.get("symbol", "")
        exchange = pos.get("exchange", "")
        frozen = pos.get("frozen", 0)
        mv = volume * price

        total_pnl += pnl
        total_mv += mv

        rows.append({
            "合约": symbol,
            "交易所": exchange.upper() if exchange else "",
            "方向": "📈 多" if direction in ("buy", "BUY") else "📉 空",
            "手数": volume,
            "可平": available,
            "冻结": frozen,
            "均价": price,
            "浮动盈亏": pnl,
            "市值": mv,
        })

    # --------------------------------------------------------------
    # 表格
    # --------------------------------------------------------------
    df_col_config = {
        "均价": st.column_config.NumberColumn(format="%.2f"),
        "浮动盈亏": st.column_config.NumberColumn(format="¥%+.2f"),
        "市值": st.column_config.NumberColumn(format="¥%,.0f"),
    }

    st.dataframe(
        rows,
        column_config=df_col_config,
        use_container_width=True,
        hide_index=True,
    )

    # --------------------------------------------------------------
    # 底部统计
    # --------------------------------------------------------------
    st.divider()
    cols = st.columns(4)
    with cols[0]:
        st.metric("持仓品种数", len(positions))
    with cols[1]:
        st.metric("总手数", sum(p.get("volume", 0) for p in positions))
    with cols[2]:
        st.metric("持仓市值", f"¥{total_mv:,.0f}")
    with cols[3]:
        st.metric(
            "总浮动盈亏",
            f"¥{total_pnl:+,.0f}",
            delta_color="inverse",
        )


if __name__ == "__main__":
    show()
