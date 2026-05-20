"""
K线图表页面 — 查看合约日线/分钟线数据
"""
import sys
from pathlib import Path

_root = str(Path(__file__).resolve().parent.parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta

from src.data.futures_collector import FuturesDataCollector


# 常用期货品种
PRODUCTS = {
    "RB": "螺纹钢", "CU": "沪铜", "IF": "沪深300",
    "SC": "原油", "P": "棕榈油", "HC": "热卷",
    "MA": "甲醇", "TA": "PTA", "RM": "菜粕",
}

TIMEFRAMES = {
    "日线": "daily",
    "60分钟": "60",
    "30分钟": "30",
    "15分钟": "15",
    "5分钟": "5",
    "1分钟": "1",
}

PERIOD_OPTIONS = {
    "日": 1, "周": 7, "月": 30, "季": 90, "年": 365, "2年": 730, "全部": 0,
}


@st.cache_data(ttl=300)
def load_daily(symbol: str, days: int = 365) -> pd.DataFrame:
    """加载日线数据（缓存5分钟）"""
    collector = FuturesDataCollector()
    df = collector.get_contract_daily(symbol)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    if days > 0:
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=days)
        df = df[df["date"] >= cutoff]
    return df.sort_values("date")


@st.cache_data(ttl=60)
def load_minute(symbol: str, period: str = "5") -> pd.DataFrame:
    """加载分钟线数据（缓存1分钟）"""
    import akshare as ak
    df = ak.futures_zh_minute_sina(symbol=symbol, period=period)
    if df.empty:
        return df
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df.sort_values("datetime")


def plot_candlestick(df: pd.DataFrame, symbol: str, title: str,
                     show_ma: bool = True, time_unit: str = "日线"):
    """绘制 K线图 + 成交量 + 可选均线"""
    df = df.copy()

    if time_unit == "日线":
        x_col = "date"
        text_x = "date"
    else:
        x_col = "datetime"
        text_x = "datetime"

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.75, 0.25],
    )

    # K线
    fig.add_trace(go.Candlestick(
        x=df[x_col],
        open=df["open"], high=df["high"],
        low=df["low"], close=df["close"],
        name="K线",
        increasing_line_color="#ef5350",
        decreasing_line_color="#26a69a",
    ), row=1, col=1)

    # 均线
    if show_ma and len(df) >= 10:
        close = df["close"]
        for period, color, dash in [
            (5, "#FFD700", None), (10, "#FF8C00", None),
            (20, "#E91E63", "dash"), (60, "#7C4DFF", "dash"),
        ]:
            if len(close) >= period:
                ma = close.rolling(period).mean()
                fig.add_trace(go.Scatter(
                    x=df[x_col], y=ma,
                    name=f"MA{period}",
                    line=dict(color=color, width=1, dash=dash),
                    showlegend=True,
                ), row=1, col=1)

    # 成交量
    colors = ["#ef5350" if df["close"].iloc[i] >= df["open"].iloc[i]
              else "#26a69a" for i in range(len(df))]
    fig.add_trace(go.Bar(
        x=df[x_col], y=df["volume"],
        name="成交量", marker_color=colors,
        showlegend=False,
    ), row=2, col=1)

    fig.update_layout(
        title=f"{symbol} {title}",
        xaxis_title="",
        yaxis_title="价格",
        height=600,
        margin=dict(l=0, r=0, t=40, b=0),
        template="plotly_dark",
        hovermode="x unified",
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", y=1.02, x=0.5, xanchor="center"),
    )
    fig.update_yaxes(title_text="价格", row=1, col=1)
    fig.update_yaxes(title_text="成交量", row=2, col=1)

    return fig


def show():
    st.header("📊 合约 K线图")

    # 参数选择
    col1, col2, col3, col4 = st.columns([2, 1, 1, 2])

    with col1:
        product = st.selectbox("品种", options=list(PRODUCTS.keys()),
                               format_func=lambda x: f"{x} ({PRODUCTS[x]})",
                               index=0)

    with col2:
        contract_suffix = st.text_input("合约月份", value="2610",
                                        help="如 2610 = 2026年10月")

    with col3:
        timeframe = st.selectbox("周期", options=list(TIMEFRAMES.keys()),
                                 index=0)

    with col4:
        period_label = st.selectbox("时间范围", options=list(PERIOD_OPTIONS.keys()),
                                    index=3)

    contract = f"{product}{contract_suffix}"
    period_days = PERIOD_OPTIONS[period_label]
    tf_value = TIMEFRAMES[timeframe]
    is_daily = tf_value == "daily"

    # 加载数据
    with st.spinner(f"加载 {contract} 数据..."):
        if is_daily:
            df = load_daily(contract, days=period_days)
        else:
            df = load_minute(contract, period=tf_value)
            if period_days > 0 and not df.empty:
                cutoff = pd.Timestamp.now() - pd.Timedelta(days=period_days)
                df = df[df["datetime"] >= cutoff]

    if df.empty:
        st.warning(f"没有找到 {contract} 的数据，请检查合约代码是否正确")
        # 显示示例合约
        st.info("示例合约: RB2610 (螺纹钢2510), CU2607 (沪铜2607), IF2606 (沪深300)")
        return

    x_col = "date" if is_daily else "datetime"

    # 数据概览
    latest = df.iloc[-1]
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("最新价", f"{latest['close']:.1f}")
    col2.metric("最高", f"{latest['high']:.1f}")
    col3.metric("最低", f"{latest['low']:.1f}")
    col4.metric("成交量", f"{int(latest['volume']):,}")
    if "hold" in latest and pd.notna(latest["hold"]):
        col5.metric("持仓量", f"{int(latest['hold']):,}")

    st.caption(f"数据区间: {df.iloc[0][x_col].date()} ~ {df.iloc[-1][x_col].date()}  "
               f"共 {len(df)} 根K线")

    # 均线开关
    show_ma = st.toggle("显示均线 (MA5/10/20/60)", value=True)

    # 图表
    fig = plot_candlestick(df, contract, timeframe, show_ma, timeframe)
    st.plotly_chart(fig, use_container_width=True)

    # 数据表格
    with st.expander("📋 查看原始数据"):
        display_cols = [x_col] + [c for c in ["open", "high", "low", "close",
                                                "volume", "hold", "settle"]
                                  if c in df.columns]
        st.dataframe(
            df[display_cols].iloc[::-1].head(50).reset_index(drop=True),
            use_container_width=True, hide_index=True,
        )


if __name__ == "__main__":
    show()
