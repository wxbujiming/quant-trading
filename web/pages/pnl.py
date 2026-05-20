"""
PnL 权益曲线 — 历史权益走势图。
"""

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd


def show():
    from web.state_reader import get_equity_history

    st.header("📈 盈亏权益曲线")

    data = get_equity_history()

    if not data:
        st.warning("暂无权益历史数据")
        st.info(
            "权益历史数据由引擎运行时自动记录。\n\n"
            "如需启用，请确保引擎运行时 EquityRecorder 正在记录。\n"
            "数据存储位置: data/live_state/trade.db (SQLite)"
        )
        return

    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp")

    # --------------------------------------------------------------
    # KPI 指标
    # --------------------------------------------------------------
    if len(df) > 1:
        first_equity = df["equity"].iloc[0]
        last_equity = df["equity"].iloc[-1]
        total_return = last_equity - first_equity
        return_pct = (total_return / first_equity) * 100 if first_equity else 0

        max_equity = df["equity"].max()
        min_equity = df["equity"].min()
        max_drawdown = (max_equity - min_equity) / max_equity * 100 if max_equity else 0

        current_pnl = df["pnl"].iloc[-1]
        current_equity = df["equity"].iloc[-1]
        current_available = df["available"].iloc[-1]

        cols = st.columns(5)
        with cols[0]:
            st.metric("当前权益", f"¥{current_equity:,.2f}")
        with cols[1]:
            st.metric("可用资金", f"¥{current_available:,.2f}")
        with cols[2]:
            st.metric("累计收益", f"¥{total_return:+,.2f} ({return_pct:+.2f}%)")
        with cols[3]:
            st.metric("最大回撤", f"{max_drawdown:.2f}%")
        with cols[4]:
            st.metric("当前浮动盈亏", f"¥{current_pnl:+,.2f}")

    # --------------------------------------------------------------
    # 权益曲线图（双轴：权益 + 可用资金）
    # --------------------------------------------------------------
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.7, 0.3],
    )

    # 权益曲线
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["equity"],
            mode="lines",
            name="总权益",
            line=dict(color="#2196F3", width=2),
        ),
        row=1, col=1,
    )

    # 可用资金曲线
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["available"],
            mode="lines",
            name="可用资金",
            line=dict(color="#4CAF50", width=1.5, dash="dash"),
        ),
        row=1, col=1,
    )

    # PnL 曲线（副图）
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["pnl"],
            mode="lines",
            name="浮动盈亏",
            line=dict(color="#FF9800", width=1.5),
            fill="tozeroy",
            fillcolor="rgba(255, 152, 0, 0.1)",
        ),
        row=2, col=1,
    )

    # 布局
    fig.update_layout(
        height=600,
        hovermode="x unified",
        showlegend=True,
        template="plotly_white",
        margin=dict(l=60, r=60, t=40, b=40),
        legend=dict(orientation="h", y=1.02, x=0.5, xanchor="center"),
    )

    fig.update_yaxes(title_text="金额 (¥)", row=1, col=1)
    fig.update_yaxes(title_text="浮动盈亏 (¥)", row=2, col=1)
    fig.update_xaxes(title_text="时间", row=2, col=1)

    st.plotly_chart(fig, use_container_width=True)

    # --------------------------------------------------------------
    # 原始数据表
    # --------------------------------------------------------------
    with st.expander("查看原始数据"):
        display_df = df.copy()
        display_df["timestamp"] = display_df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
        display_df = display_df[["timestamp", "equity", "available", "margin", "pnl"]]
        display_df.columns = ["时间", "总权益", "可用资金", "占用保证金", "浮动盈亏"]
        st.dataframe(display_df.iloc[::-1], use_container_width=True, hide_index=True)


if __name__ == "__main__":
    show()
