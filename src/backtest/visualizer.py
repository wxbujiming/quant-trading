"""
回测可视化模块
提供资金曲线、回撤图、交易标记K线图等
"""
from typing import List, Optional
from datetime import datetime

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from loguru import logger

from src.backtest.engine import BacktestResult, TradeRecord


def plot_equity_curve(
    result: BacktestResult,
    title: str = "资金曲线",
    show_benchmark: bool = False,
    benchmark_data: Optional[pd.DataFrame] = None,
    html_path: Optional[str] = None,
) -> go.Figure:
    """
    绘制资金曲线图（含回撤子图）

    Args:
        result: 回测结果
        title: 图表标题
        show_benchmark: 是否显示基准(买入持有)
        benchmark_data: 基准数据(需包含close列)
        html_path: 保存HTML路径，None则不保存

    Returns:
        plotly Figure对象
    """
    df = result.daily_values.copy()
    if df is None or df.empty:
        logger.warning("无回测数据可绘制")
        return go.Figure()

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.7, 0.3],
        subplot_titles=(title, "回撤"),
    )

    # 资金曲线
    fig.add_trace(
        go.Scatter(
            x=df["date"], y=df["total_value"],
            mode="lines",
            name="策略资金",
            line=dict(color="#2196F3", width=2),
        ),
        row=1, col=1,
    )

    # 基准线(买入持有)
    if show_benchmark and benchmark_data is not None:
        bm = benchmark_data.reindex(df["date"], method="ffill")
        if not bm.empty:
            init_price = bm.iloc[0]["close"]
            bm_values = result.initial_cash * (bm["close"] / init_price)
            fig.add_trace(
                go.Scatter(
                    x=df["date"], y=bm_values,
                    mode="lines",
                    name="买入持有",
                    line=dict(color="#9E9E9E", width=1.5, dash="dash"),
                ),
                row=1, col=1,
            )

    # 回撤曲线
    df["drawdown"] = df["drawdown"] if "drawdown" in df.columns else 0
    fig.add_trace(
        go.Scatter(
            x=df["date"], y=-df["drawdown"] * 100,
            mode="lines",
            name="回撤",
            fill="tozeroy",
            line=dict(color="#F44336", width=1),
            fillcolor="rgba(244, 67, 54, 0.15)",
        ),
        row=2, col=1,
    )

    # 布局
    fig.update_layout(
        height=600,
        hovermode="x unified",
        showlegend=True,
        template="plotly_white",
        margin=dict(l=60, r=60, t=60, b=40),
    )
    fig.update_yaxes(title_text="资金 (元)", row=1, col=1)
    fig.update_yaxes(title_text="回撤 (%)", row=2, col=1)
    fig.update_xaxes(title_text="日期", row=2, col=1)

    # 添加关键指标注释
    _add_kpi_annotations(fig, result)

    if html_path:
        fig.write_html(html_path)
        logger.info(f"资金曲线已保存: {html_path}")

    return fig


def plot_trade_signals(
    result: BacktestResult,
    data: pd.DataFrame,
    title: str = "交易信号 K线图",
    indicators: Optional[List[dict]] = None,
    html_path: Optional[str] = None,
) -> go.Figure:
    """
    绘制K线图 + 买卖标记 + 指标叠加

    Args:
        result: 回测结果
        data: 原始行情数据(需date/open/close/high/low/volume)
        title: 图表标题
        indicators: 指标列表 [{"name": "MA10", "values": [...]}]
        html_path: 保存HTML路径

    Returns:
        plotly Figure对象
    """
    df = data.reset_index() if data.index.name == "date" else data.copy()
    if "date" not in df.columns:
        df["date"] = df.index

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.7, 0.3],
        subplot_titles=(title, "成交量"),
    )

    # K线图
    fig.add_trace(
        go.Candlestick(
            x=df["date"],
            open=df["open"], high=df["high"],
            low=df["low"], close=df["close"],
            name="K线",
            increasing_line_color="#26A69A",
            decreasing_line_color="#EF5350",
        ),
        row=1, col=1,
    )

    # 叠加指标
    if indicators:
        for ind in indicators:
            values = ind.get("values", [])
            if len(values) != len(df):
                continue
            fig.add_trace(
                go.Scatter(
                    x=df["date"], y=values,
                    mode="lines",
                    name=ind["name"],
                    line=dict(color=ind.get("color", "#FF9800"), width=1.5),
                ),
                row=1, col=1,
            )

    # 买入标记
    buy_trades = [t for t in result.trades if t.action == "BUY"]
    if buy_trades:
        fig.add_trace(
            go.Scatter(
                x=[t.date for t in buy_trades],
                y=[t.price for t in buy_trades],
                mode="markers",
                name="买入",
                marker=dict(
                    symbol="triangle-up", size=12,
                    color="#26A69A", line=dict(width=1, color="white"),
                ),
            ),
            row=1, col=1,
        )

    # 卖出标记
    sell_trades = [t for t in result.trades if t.action == "SELL"]
    if sell_trades:
        fig.add_trace(
            go.Scatter(
                x=[t.date for t in sell_trades],
                y=[t.price for t in sell_trades],
                mode="markers",
                name="卖出",
                marker=dict(
                    symbol="triangle-down", size=12,
                    color="#EF5350", line=dict(width=1, color="white"),
                ),
            ),
            row=1, col=1,
        )

    # 成交量柱（兼容中英文列名）
    vol_col = next((c for c in ["volume", "成交量", "vol", "amount"] if c in df.columns), None)
    if vol_col:
        colors = ["#26A69A" if df["close"].iloc[i] >= df["open"].iloc[i] else "#EF5350"
                  for i in range(len(df))]
        fig.add_trace(
            go.Bar(
                x=df["date"], y=df[vol_col],
                name="成交量",
                marker_color=colors,
                opacity=0.5,
            ),
            row=2, col=1,
        )

    # 布局
    fig.update_layout(
        height=700,
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        showlegend=True,
        template="plotly_white",
        margin=dict(l=60, r=60, t=60, b=40),
    )
    fig.update_yaxes(title_text="价格", row=1, col=1)
    fig.update_yaxes(title_text="成交量", row=2, col=1)

    if html_path:
        fig.write_html(html_path)
        logger.info(f"K线图已保存: {html_path}")

    return fig


def plot_strategy_comparison(
    results: List[tuple],
    title: str = "策略对比",
    html_path: Optional[str] = None,
) -> go.Figure:
    """
    多策略资金曲线对比

    Args:
        results: [(策略名, BacktestResult), ...]
        title: 图表标题
        html_path: 保存路径

    Returns:
        plotly Figure
    """
    fig = go.Figure()

    colors = ["#2196F3", "#FF9800", "#4CAF50", "#F44336", "#9C27B0", "#00BCD4"]

    for i, (name, result) in enumerate(results):
        df = result.daily_values
        if df is None or df.empty:
            continue

        color = colors[i % len(colors)]
        fig.add_trace(
            go.Scatter(
                x=df["date"], y=df["total_value"],
                mode="lines",
                name=f"{name} ({result.total_return:.1%})",
                line=dict(color=color, width=2),
            )
        )

    fig.update_layout(
        title=title,
        height=500,
        hovermode="x unified",
        showlegend=True,
        template="plotly_white",
        xaxis_title="日期",
        yaxis_title="资金 (元)",
        margin=dict(l=60, r=60, t=60, b=40),
    )

    if html_path:
        fig.write_html(html_path)
        logger.info(f"策略对比已保存: {html_path}")

    return fig


def plot_drawdown_heatmap(
    result: BacktestResult,
    title: str = "月度收益热力图",
    html_path: Optional[str] = None,
) -> go.Figure:
    """
    月度收益率热力图

    Args:
        result: 回测结果
        title: 图表标题
        html_path: 保存路径

    Returns:
        plotly Figure
    """
    df = result.daily_values.copy()
    if df is None or df.empty:
        return go.Figure()

    df["date"] = pd.to_datetime(df["date"])
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month
    df["daily_return"] = df["total_value"].pct_change()

    # 月收益率
    monthly = df.groupby(["year", "month"])["daily_return"].apply(
        lambda x: (1 + x).prod() - 1
    ).reset_index()
    monthly.columns = ["year", "month", "return"]

    # 透视
    heat_data = monthly.pivot(index="year", columns="month", values="return")
    heat_data = heat_data * 100  # 转百分比

    # NaN替换为0并格式化文本
    heat_vals = heat_data.fillna(0).values
    text_vals = [[f"{heat_vals[r][c]:.1f}%"
                  for c in range(len(heat_data.columns))]
                 for r in range(len(heat_data))]

    month_labels = ["1月", "2月", "3月", "4月", "5月", "6月",
                    "7月", "8月", "9月", "10月", "11月", "12月"]

    fig = go.Figure(
        go.Heatmap(
            z=heat_vals,
            x=[month_labels[m - 1] for m in heat_data.columns],
            y=heat_data.index,
            text=text_vals,
            texttemplate="%{text}",
            textfont=dict(size=11),
            colorscale="RdYlGn",
            zmid=0,
            zmin=-15,
            zmax=15,
            colorbar=dict(title="月收益率 (%)"),
        )
    )

    fig.update_layout(
        title=title,
        height=400,
        template="plotly_white",
        xaxis_title="月份",
        yaxis_title="年份",
        margin=dict(l=60, r=60, t=60, b=40),
    )

    if html_path:
        fig.write_html(html_path)
        logger.info(f"热力图已保存: {html_path}")

    return fig


def _add_kpi_annotations(fig: go.Figure, result: BacktestResult):
    """在图表右上角添加关键指标"""
    kpi_text = (
        f"总收益率: {result.total_return:.1%}<br>"
        f"年化收益: {result.annual_return:.1%}<br>"
        f"最大回撤: {result.max_drawdown:.1%}<br>"
        f"夏普比率: {result.sharpe_ratio:.2f}<br>"
        f"交易: {result.total_trades}次 | 胜率: {result.win_rate:.0%}"
    )
    fig.add_annotation(
        xref="paper", yref="paper",
        x=0.98, y=0.98,
        text=kpi_text,
        showarrow=False,
        font=dict(size=12, color="#666"),
        align="left",
        bgcolor="rgba(255,255,255,0.9)",
        bordercolor="#ddd",
        borderwidth=1,
        borderpad=6,
    )


def generate_report(
    result: BacktestResult,
    data: pd.DataFrame,
    strategy_name: str = "策略",
    indicators: Optional[List[dict]] = None,
    output_dir: str = "./reports",
) -> str:
    """
    生成完整回测报告(HTML)

    Args:
        result: 回测结果
        data: 原始行情数据
        strategy_name: 策略名称
        indicators: 指标列表
        output_dir: 输出目录

    Returns:
        HTML文件路径
    """
    from pathlib import Path
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = str(out / f"backtest_{strategy_name}_{timestamp}.html")

    # 生成各图表
    fig1 = plot_equity_curve(result, title=f"{strategy_name} - 资金曲线")
    fig2 = plot_trade_signals(result, data, title=f"{strategy_name} - 交易信号", indicators=indicators)
    fig3 = plot_drawdown_heatmap(result)

    # 合并HTML
    html_parts = [f"""
    <html><head><meta charset="utf-8">
    <title>回测报告 - {strategy_name}</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body {{ font-family: 'Microsoft YaHei', sans-serif; max-width: 1200px; margin: 20px auto; padding: 0 20px; background: #f5f5f5; }}
        .section {{ background: white; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); margin: 20px 0; padding: 15px; }}
        h1 {{ text-align: center; color: #333; }}
        .kpi-grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin: 15px 0; }}
        .kpi-card {{ background: linear-gradient(135deg, #667eea, #764ba2); color: white; border-radius: 8px; padding: 12px; text-align: center; }}
        .kpi-card:nth-child(2) {{ background: linear-gradient(135deg, #f093fb, #f5576c); }}
        .kpi-card:nth-child(3) {{ background: linear-gradient(135deg, #4facfe, #00f2fe); }}
        .kpi-card:nth-child(4) {{ background: linear-gradient(135deg, #43e97b, #38f9d7); }}
        .kpi-card:nth-child(5) {{ background: linear-gradient(135deg, #fa709a, #fee140); }}
        .kpi-value {{ font-size: 1.6em; font-weight: bold; }}
        .kpi-label {{ font-size: 0.8em; opacity: 0.85; }}
    </style></head><body>
    <h1>📈 回测报告 - {strategy_name}</h1>
    <div class="kpi-grid">
        <div class="kpi-card">
            <div class="kpi-value">{result.total_return:.1%}</div>
            <div class="kpi-label">总收益率</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-value">{result.annual_return:.1%}</div>
            <div class="kpi-label">年化收益率</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-value">{result.max_drawdown:.1%}</div>
            <div class="kpi-label">最大回撤</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-value">{result.sharpe_ratio:.2f}</div>
            <div class="kpi-label">夏普比率</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-value">{result.win_rate:.0%}</div>
            <div class="kpi-label">胜率 ({result.profit_trades}/{result.loss_trades})</div>
        </div>
    </div>
    <div class="section">
    """]

    # 添加各图表的HTML
    for fig in [fig1, fig2, fig3]:
        html_parts.append(fig.to_html(full_html=False, include_plotlyjs=False))
        html_parts.append('</div><div class="section">')

    html_parts.append("""
    </div></body></html>
    """)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(html_parts))

    logger.success(f"回测报告已生成: {report_path}")
    return report_path
