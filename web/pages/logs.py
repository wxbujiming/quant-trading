"""
实时日志查看 — 读取日志文件并高亮显示。
"""

import streamlit as st
import re


def show():
    from web.state_reader import get_log_lines, get_log_files

    st.header("📝 实时日志")

    # --------------------------------------------------------------
    # 日志文件选择
    # --------------------------------------------------------------
    log_files = get_log_files()
    if not log_files:
        st.warning("未找到日志文件")
        return

    available = ["live_engine.log", "app.log"]
    valid_files = [f for f in available if f in log_files]
    if not valid_files:
        valid_files = log_files

    # 日志文件中文显示名
    log_names = {
        "live_engine.log": "🚀 实盘引擎",
        "app.log": "📁 应用日志",
    }
    log_display = {log_names.get(f, f): f for f in valid_files}
    selected_label = st.selectbox("选择日志文件", list(log_display.keys()), key="log_selector")
    selected_log = log_display[selected_label]

    # --------------------------------------------------------------
    # 读取日志
    # --------------------------------------------------------------
    max_lines = st.slider("显示行数", 50, 500, 200, key="log_line_count")
    lines = get_log_lines(selected_log, n=max_lines)

    if not lines:
        st.info("日志文件为空")
        return

    # --------------------------------------------------------------
    # 显示日志（带语法高亮）
    # --------------------------------------------------------------
    html_lines = []
    for line in lines:
        color = "#CCCCCC"  # 默认
        if re.search(r"\bERROR\b", line):
            color = "#FF6B6B"  # 红色
        elif re.search(r"\bWARNING\b", line):
            color = "#FFD93D"  # 黄色
        elif re.search(r"\bCRITICAL\b", line):
            color = "#FF4444"  # 亮红
        elif re.search(r"\bINFO\b", line):
            color = "#6BCB77"  # 绿色
        elif re.search(r"\bDEBUG\b", line):
            color = "#888888"  # 灰色
        html_lines.append(
            f'<div style="color:{color}; font-family: monospace; font-size: 13px; '
            f'white-space: pre; line-height: 1.4;">'
            f'{line}</div>'
        )

    log_html = "".join(html_lines)

    st.markdown(
        f"""
        <div style="background-color: #1E1E1E; padding: 12px; border-radius: 6px;
                     height: 600px; overflow-y: auto; font-family: monospace;">
            {log_html}
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.caption(f"共显示 {len(lines)} 行 (最新)，来自 {selected_label}")


if __name__ == "__main__":
    show()
